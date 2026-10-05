import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

from sovereign_intake.common import IntakeError, directory, read_under, atomic, exclusive, locked
from .core import absolute, crypto_tool, MAX_FILE, write_jobs, validate, within

MAX_TOTAL = 480 * 1024 * 1024
MAX_MEMBERS = 100000


def check_key(path, archive=None, hub=None):
    path = absolute(path)
    for root in (archive, hub):
        if root and within(path, root):
            raise ValueError('Keep the recovery key outside both the archive and Hub folder.')
    try:
        raw, info = read_under(path.parent, path.name, 32)
    except (IsADirectoryError, IntakeError) as exc:
        # A folder, or a file of the wrong kind or size: say what it is, never the boundary code.
        if isinstance(exc, IntakeError) and str(exc) not in ('input_type_or_size', 'input_changed_or_too_large'):
            raise
        raise ValueError('That file is not a Sovereign recovery key.') from None
    if len(raw) != 32 or info.st_mode & 0o077:
        raise ValueError('The recovery key must contain 32 bytes and be readable only by its owner (0600).')
    return path


def inside_archive(path):
    return any((p / 'knowledge').is_dir() and (p / 'raw').is_dir() for p in path.parents)


def recovery_key(output, apply=False):
    output = absolute(output)
    if inside_archive(output):
        raise ValueError('Keep the recovery key outside every archive.')
    directory(output.parent)
    if output.exists():
        raise ValueError('The recovery key destination already exists.')
    if apply:
        exclusive(output, secrets.token_bytes(32))
    return {'key_file': str(output), 'applied': apply, 'note': 'Keep an independent secure copy. Losing this key makes its capsules unrecoverable.'}


def configure(config, folder, key, apply=False):
    folder = directory(folder); key = check_key(key, Path(config['archive']), Path(config['destination']))
    if within(key, folder):
        raise ValueError('Store capsules separately from the recovery key.')
    for root in (Path(config['archive']), Path(config['destination'])):
        if within(folder, root):
            raise ValueError('Store capsules outside the archive and Hub folder.')
    updated = dict(config, snapshot_folder=str(folder), recovery_key=str(key))
    if apply:
        with locked(Path(config['destination']) / 'operation.lock'):
            atomic(Path(config['destination']) / 'config.json', updated)
    return {'config': updated, 'applied': apply, 'scheduled': False}


def inventory(config):
    entries = []; total = 0
    for prefix, root in [('archive', Path(config['archive'])), ('hub', Path(config['destination']))]:
        for current, dirs, files in os.walk(root, followlinks=False):
            current = Path(current)
            if current == root and prefix == 'archive':
                dirs[:] = [x for x in dirs if x != 'repos']
            if prefix == 'hub':
                # Operational locks and logs are disposable; the state, code and runtime are retained.
                dirs[:] = [x for x in dirs if x not in ('logs', '__pycache__')]
                files = [x for x in files if x != 'operation.lock' and not x.endswith('.pyc')]
            for name in dirs:
                if (current / name).is_symlink():
                    raise ValueError('Snapshot refused a linked directory: ' + str(current / name))
            rel = current.relative_to(root)
            entries.append((str(PurePosixPath(prefix) / rel), None, None))
            for name in sorted(files):
                path = current / name
                if path.is_symlink():
                    raise ValueError('Snapshot refused a linked file: ' + str(path))
                raw, info = read_under(root, str(rel / name), MAX_FILE)
                total += len(raw)
                if total > MAX_TOTAL or len(entries) >= MAX_MEMBERS: raise ValueError('Recovery capsule exceeds its size limit.')
                entries.append((str(PurePosixPath(prefix) / rel / name), raw, info))
    if len(entries) > MAX_MEMBERS or sum(len(raw) for _, raw, _ in entries if raw is not None) > MAX_TOTAL:
        raise ValueError('This recovery capsule exceeds the pilot limit (480 MiB or 100,000 entries).')
    return entries


def snapshot(config, output, key, apply=False):
    output = absolute(output); archive = Path(config['archive']); hub = Path(config['destination'])
    key = check_key(key, archive, hub)
    for root in (archive, hub):
        if within(output, root):
            raise ValueError('Place the recovery capsule outside the archive and Hub folder.')
    if within(key, output.parent):
        raise ValueError('Store capsules separately from the recovery key.')
    directory(output.parent)
    if output.exists():
        raise ValueError('The capsule destination already exists.')
    result = {'output': str(output), 'applied': apply, 'encrypted': True,
              'includes': ['archive, including curator state and Git history', 'Hub settings, tools and Python runtime'],
              'excludes': ['repos working trees', 'machine SSH keys, external service credentials and other home files'],
              'activation': 'Restored jobs stay inactive until explicitly activated.'}
    if not apply:
        return result
    with locked(hub / 'operation.lock'), tempfile.TemporaryDirectory(prefix='sov-recovery-', dir=output.parent) as tmp:
        tmp = Path(tmp); entries = inventory(config)
        hashes = {}; signatures = {}
        plain = tmp / 'capsule.tar.gz'
        with tarfile.open(plain, 'w:gz') as tar:
            for name, raw, info in entries:
                header = tarfile.TarInfo(name); header.mode = 0o700 if raw is None else (0o700 if info.st_mode & 0o111 else 0o600)
                header.mtime = int(time.time()); header.type = tarfile.DIRTYPE if raw is None else tarfile.REGTYPE
                if raw is not None:
                    header.size = len(raw); hashes[name] = hashlib.sha256(raw).hexdigest()
                    signatures[name] = (info.st_mtime_ns, info.st_size)
                tar.addfile(header, io.BytesIO(raw) if raw is not None else None)
            payload = json.dumps({'version': 1, 'hashes': hashes, 'created': time.time()}, sort_keys=True).encode()
            if len(payload) > 32 * 1024 * 1024 or sum(len(raw) for _, raw, _ in entries if raw is not None) + len(payload) > MAX_TOTAL:
                raise ValueError('Recovery contents and manifest exceed the supported size limit.')
            h = tarfile.TarInfo('manifest.json'); h.size = len(payload); h.mode = 0o600; tar.addfile(h, io.BytesIO(payload))
        # Refuse an archive changing during the read, rather than claim a consistent backup.
        current = inventory(config)
        if {name for name, _, _ in current} != {name for name, _, _ in entries}:
            raise ValueError('Files changed during the snapshot. Retry when writers are idle.')
        for name, raw, info in current:
            if raw is not None and (hashlib.sha256(raw).hexdigest() != hashes[name] or (info.st_mtime_ns, info.st_size) != signatures[name]):
                raise ValueError('Files changed during the snapshot. Retry when writers are idle.')
        encrypted = tmp / 'encrypted'
        subprocess.run([str(crypto_tool()), 'seal', str(key), str(plain), str(encrypted)], check=True, capture_output=True, timeout=120)
        if encrypted.stat().st_size > MAX_TOTAL:
            raise ValueError('Encrypted capsule exceeds the supported size limit.')
        os.link(encrypted, output, follow_symlinks=False)
        result.update(files=len(hashes), sha256=hashlib.sha256(encrypted.read_bytes()).hexdigest(), finished=time.time())
        atomic(hub / 'receipts/snapshot.json', result)
    return result


def validated_members(tar):
    members = tar.getmembers()
    if len(members) > MAX_MEMBERS + 1 or sum(m.size for m in members) > MAX_TOTAL:
        raise ValueError('Recovery capsule exceeds the supported size limit.')
    seen = set()
    for member in members:
        path = PurePosixPath(member.name)
        if member.name in seen or path.is_absolute() or any(p in ('', '.', '..') for p in member.name.split('/')) or '\\' in member.name or any(ord(c) < 32 for c in member.name):
            raise ValueError('Recovery capsule has an unsafe or duplicate path.')
        if not (member.isfile() or member.isdir()) or (member.name != 'manifest.json' and path.parts[0] not in ('archive', 'hub')):
            raise ValueError('Recovery capsule contains an unsupported entry.')
        if member.size > MAX_FILE:
            raise ValueError('Recovery capsule contains an oversized file.')
        seen.add(member.name)
    manifest = tar.getmember('manifest.json')
    if manifest.size > 32 * 1024 * 1024:
        raise ValueError('Recovery manifest is too large.')
    metadata = json.load(tar.extractfile(manifest))
    if metadata.get('version') != 1:
        raise ValueError('Unsupported recovery format.')
    hashes = metadata['hashes']
    if set(hashes) != {m.name for m in members if m.isfile() and m.name != 'manifest.json'}:
        raise ValueError('Recovery inventory does not match its manifest.')
    for m in members:
        if m.isfile() and m.name != 'manifest.json':
            if hashlib.sha256(tar.extractfile(m).read()).hexdigest() != hashes[m.name]:
                raise ValueError('Recovery file failed verification.')
    for required in ('hub/config.json', 'hub/bin/sov', 'hub/python/bin/python3', 'archive/CLAUDE.md'):
        if required not in hashes:
            raise ValueError('Recovery capsule is incomplete: ' + required)
    if not any(name in hashes for name in ('hub/engine/bin/sov-managed-hub', 'hub/engine/bin/brain-hub')):
        raise ValueError('Recovery capsule is incomplete: managed hub command')
    return members


def restore(capsule, destination, key, apply=False):
    capsule = absolute(capsule); destination = absolute(destination); key = check_key(key)
    if destination.exists():
        raise ValueError('Restore only into a new directory. Existing archives are never overwritten.')
    # A restore carries a whole archive with its Git history, the Hub and its runtime.
    if inside_archive(destination):
        raise ValueError('Restore into a new folder outside every archive.')
    # The native helper authenticates the whole capsule before tar data is inspected.
    raw, _ = read_under(capsule.parent, capsule.name, MAX_TOTAL)
    with tempfile.TemporaryDirectory(prefix='sov-restore-', dir=destination.parent) as tmp:
        tmp = Path(tmp); private = tmp / 'input'; private.write_bytes(raw); private.chmod(0o600); plain = tmp / 'capsule.tar.gz'
        subprocess.run([str(crypto_tool()), 'open', str(key), str(private), str(plain)], check=True, capture_output=True, timeout=120)
        with tarfile.open(plain, 'r:gz') as tar:
            members = validated_members(tar)
            result = {'destination': str(destination), 'files_verified': sum(m.isfile() for m in members) - 1, 'applied': apply, 'scheduled': False, 'activation_required': True}
            if not apply:
                return result
            staged = tmp / 'restored'; staged.mkdir(mode=0o700)
            for m in members:
                if m.name == 'manifest.json': continue
                p = staged / m.name
                if m.isdir():
                    p.mkdir(mode=0o700, parents=True, exist_ok=True)
                else:
                    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with p.open('xb') as out: shutil.copyfileobj(tar.extractfile(m), out)
                    p.chmod(0o700 if m.mode & 0o111 else 0o600)
        for name in ('archive/repos', 'hub/logs', 'hub/receipts'):
            (staged / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        cpath = staged / 'hub/config.json'; config = json.loads(cpath.read_text())
        config.update(archive=str(destination / 'archive'), destination=str(destination / 'hub'), snapshot_folder=None, recovery_key=None)
        cpath.write_text(json.dumps(config, indent=2)+'\n')
        # Rename only a newly reserved destination; never use replace against existing data.
        destination.mkdir(mode=0o700)
        try:
            for child in staged.iterdir(): child.rename(destination / child.name)
            validate(config); write_jobs(config)
            git_config = destination / 'archive/.git/config'
            if git_config.exists():
                subprocess.run(['git', '-C', str(destination / 'archive'), 'config', 'core.hooksPath', '/dev/null'], check=True, capture_output=True)
                remotes = subprocess.run(['git', '-C', str(destination / 'archive'), 'remote'], check=True, capture_output=True, text=True).stdout.splitlines()
                for remote in remotes:
                    subprocess.run(['git', '-C', str(destination / 'archive'), 'config', '--replace-all', 'remote.' + remote + '.pushurl', 'disabled://restored-hub-needs-review'], check=True, capture_output=True)
            activation = destination / 'hub/receipts/activation.json'
            if activation.exists(): activation.unlink()
            atomic(destination / 'hub/receipts/restore.json', dict(result, finished=time.time()))
        except BaseException:
            shutil.rmtree(destination)
            raise
    return result
