#!/usr/bin/env python3
"""Remove a declared producer and only its managed read wiring. Raw history stays.

The installer owns scheduler changes. This wrapper validates cleanup first and
holds the runner lock until cleanup finishes. Retry is safe after a partial stop.
"""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CATALOG = Path(__file__).resolve().parent.parent


def atomic(path, data, mode=0o600):
    fd, temp = tempfile.mkstemp(prefix='.sov-remove-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def cleanup_plan(harness, vault):
    """Return exact before/after bytes; reject ambiguous managed text before writes."""
    folder = CATALOG / harness
    meta = json.loads((folder / 'harness.json').read_text())
    hook = str(folder / 'session-start.py')
    edits = []

    def edit(path, transform, structured=False):
        path = Path(path).expanduser()
        if not path.exists():
            return
        if path.is_symlink():
            raise ValueError('Refusing to replace a linked configuration: ' + str(path))
        before = path.read_bytes()
        original = json.loads(before) if structured else before.decode('utf-8')
        result = transform(copy.deepcopy(original))
        if result != original:
            after = (json.dumps(result, indent=2, ensure_ascii=False) + '\n') if structured else result
            edits.append((path, before, after.encode('utf-8'), path.stat().st_mode & 0o777))

    if harness in ('claude-code', 'codex', 'cursor'):
        moves = {}
        hook_path = Path(meta['hook_file']).expanduser()

        def json_hooks(data):
            hooks = data.get('hooks', {})
            event = 'sessionStart' if harness == 'cursor' else 'SessionStart'
            if event not in hooks:
                return data
            groups = hooks[event]
            if not isinstance(groups, list):
                raise ValueError('Invalid hook list in ' + str(hook_path))
            if harness == 'cursor':
                hooks[event] = [h for h in groups if h.get('command') != hook]
            else:
                kept = []
                for gi, group in enumerate(groups):
                    handlers = []
                    for hi, handler in enumerate(group.get('hooks', [])):
                        key = '%s:session_start:%d:%d' % (hook_path, gi, hi)
                        if handler.get('command') == hook:
                            moves[key] = None
                        else:
                            moves[key] = '%s:session_start:%d:%d' % (hook_path, len(kept), len(handlers))
                            handlers.append(handler)
                    if handlers or not group.get('hooks'):
                        group['hooks'] = handlers
                        kept.append(group)
                hooks[event] = kept
            return data

        edit(hook_path, json_hooks, True)
        if harness == 'codex' and moves:
            # Trust keys include array positions. Move existing records along with
            # surviving handlers, without granting trust or changing their hashes.
            def trust(text):
                pattern = r'(?m)^\[hooks\.state\.("(?:[^"\\]|\\.)*")\][^\n]*\n(?:(?!\[)[^\n]*\n?)*'
                def replace(match):
                    old = json.loads(match.group(1))
                    if old not in moves:
                        return match.group(0)
                    new = moves[old]
                    return '' if new is None else match.group(0).replace(match.group(1), json.dumps(new), 1)
                return re.sub(pattern, replace, text)
            edit(hook_path.parent / 'config.toml', trust)
    elif harness == 'hermes':
        home = Path(os.environ.get('HERMES_HOME', '~/.hermes')).expanduser()
        def hermes(text):
            entry = '    - command: "%s"\n      timeout: 30\n' % hook
            if hook in text and text.count(entry) != text.count(hook):
                raise ValueError('Hermes hook was edited; restore its managed entry before removing it.')
            text = text.replace(entry, '')
            text = re.sub(r'(?m)^  pre_llm_call:\s*\n(?=\S|  \S|\Z)', '', text)
            return text
        edit(home / 'config.yaml', hermes)
        def allow(data):
            data['approvals'] = [a for a in data.get('approvals', [])
                                 if not (a.get('event') == 'pre_llm_call' and a.get('command') == hook)]
            return data
        edit(home / 'shell-hooks-allowlist.json', allow, True)
    elif meta.get('read') == 'instruction':
        def managed(source):
            return '[Sovereign] ' + ' '.join(source.strip().replace('{{VAULT}}', vault).split())
        block = managed((folder / 'INSTRUCTION.md').read_text())
        # An instruction installed before the wording changed is still ours, and refusing
        # to remove it strands the lane: the 2026-09-17 rename turned "the brain" into
        # "the archive" in every INSTRUCTION.md, and from that day disconnect refused
        # four already-connected lanes on the grounds that its own earlier text was a
        # stranger's edit. Prior wordings live beside the current one, one paragraph each,
        # so this recognises them by record rather than by loosening the check.
        prior = folder / 'INSTRUCTION.prior.md'
        blocks = [block] + ([managed(b) for b in prior.read_text().split('\n\n') if b.strip()]
                            if prior.is_file() else [])
        def strip(text):
            if '[Sovereign]' in text and sum(text.count(b) for b in blocks) != text.count('[Sovereign]'):
                raise ValueError('Managed instruction differs from this archive; no configuration was changed.')
            # Remove exactly our paragraph, preserving owner text on either side.
            for b in blocks:
                text = text.replace('\n\n' + b, '').replace(b, '')
            return text
        if meta.get('instruction_text_file'):
            edit(meta['instruction_text_file'], strip)
        else:
            base = Path(os.environ.get('COWORK_SESSIONS', '~/Library/Application Support/Claude/local-agent-mode-sessions')).expanduser()
            def spaces(data):
                values = data.get('spaces') if isinstance(data, dict) else data
                if not isinstance(values, list):
                    raise ValueError('Unrecognized Cowork spaces configuration.')
                for item in values:
                    if isinstance(item, dict) and isinstance(item.get('instructions'), str):
                        item['instructions'] = strip(item['instructions'])
                return data
            for path in sorted(base.glob('*/*/spaces.json')):
                edit(path, spaces, True)
    return edits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('harness')
    parser.add_argument('--vault', required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]*', args.harness) or not (CATALOG / args.harness / 'harness.json').is_file():
        raise ValueError('Unknown producer')
    state = Path(os.environ.get('SOV_STATE_DIR', '~/.local/state/sovereign')).expanduser()
    manifest = Path(os.environ.get('SOV_MANIFEST', str(state / 'connectors.json')))
    data = json.loads(manifest.read_text()) if manifest.exists() else {}
    record = (data.get('harnesses') or {}).get(args.harness) or (data.get('retired_harnesses') or {}).get(args.harness) or {}
    edits = cleanup_plan(args.harness, args.vault)
    print('Remove producer: %s on %s' % (args.harness, args.host), flush=True)
    print('Archive: ' + args.vault)
    print('Stop this producer collection and remove its Sovereign context integration.')
    print('Keep collected history, original tool data, credentials and other producers.')
    print('History: ' + str(record.get('lane_dir') or 'existing lane directories stay in place'))
    for path, _, _, _ in edits:
        print('Update managed configuration: ' + str(path))
    print('Restart the tool to clear context already loaded in an open session.', flush=True)
    if not args.apply:
        print('dry run. No changes made. Apply to remove this producer.')
        return 0
    state.mkdir(parents=True, exist_ok=True)
    lock = state / 'runner.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('A collector is running. Nothing removed; retry after it finishes.')
    try:
        # Re-read after acquiring the same lock the scheduled runner holds.
        edits = cleanup_plan(args.harness, args.vault)
        env = os.environ.copy()
        env['SOV_DISCONNECT_LOCKED'] = args.harness
        result = subprocess.run(['/bin/bash', str(CATALOG / args.harness / 'install.sh'),
                                 '--disconnect', '--apply', '--vault', args.vault, '--host', args.host], env=env)
        if result.returncode:
            return result.returncode
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        for path, before, after, mode in edits:
            if path.is_symlink() or path.read_bytes() != before:
                raise ValueError('Collection stopped, but configuration changed during removal: ' + str(path) + '. Retry cleanup.')
            backup = path.with_name(path.name + '.before-remove-' + stamp)
            atomic(backup, before, mode)
            atomic(path, after, mode)
        data = json.loads(manifest.read_text())
        retired = data.setdefault('retired_harnesses', {}).setdefault(args.harness, {})
        retired.update(cleanup_pending=False, removed_at=stamp)
        atomic(manifest, (json.dumps(data, indent=1, sort_keys=True) + '\n').encode())
        print('Producer removed. History preserved. Add it again to reconnect.')
    finally:
        lock.rmdir()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError, KeyError) as error:
        print('Cannot finish producer removal: ' + str(error), file=sys.stderr)
        sys.exit(65)
