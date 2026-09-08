"""Bundled gate protocol; runs on the approval machine using only the stdlib.

Reads first. Writes only through the installed owner gate, after matching the
fingerprint the owner reviewed. Never force-approves or retires a card.
"""
import fcntl
import signal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FOLDERS = {'entity': 'entities', 'concept': 'concepts', 'synthesis': 'syntheses', 'plan': 'syntheses', 'review': 'syntheses'}
LIMIT = 128 * 1024


def read_card(path, root):
    if path.is_symlink() or root.resolve() not in path.resolve().parents:
        raise ValueError('Card path is not a regular archive file')
    if path.stat().st_size > LIMIT:
        raise ValueError('Card is too large to review safely')
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    parts = re.fullmatch(r'---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)', text, re.S)
    if parts is None:
        raise ValueError('Card has no valid label block')
    labels = dict(re.findall(r'(?m)^(\w+):[ \t]*(.*)$', parts[1]))
    return {'path': str(path.relative_to(root)), 'type': labels.get('type', ''),
            'title': labels.get('title') or path.stem, 'source': labels.get('source', ''),
            'created': labels.get('created', ''), 'body': parts[2].strip(),
            'sha256': hashlib.sha256(raw).hexdigest()}


def check(root, lane, slug):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,120}', slug):
        return {'state': 'invalid'}
    base = root / 'raw/workspaces' / lane / 'proposals'
    proposal = next((p for p in [base / (slug+'.md'), base / 'audit' / (slug+'.md')] if p.exists()), None)
    if proposal is None:
        return {'state': 'missing'}
    card = read_card(proposal, root)
    if card['type'] not in FOLDERS or not card['source'] or (card['created'] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', card['created'])):
        return {'state': 'invalid', 'proposal': card}
    existing = []
    for folder in ['entities', 'concepts', 'syntheses']:
        path = root / 'knowledge' / folder / (slug+'.md')
        if path.exists():
            existing.append(read_card(path, root))
    try:
        meta = json.loads((base / '.meta.json').read_text())
        entry = meta.get(slug, {}) if isinstance(meta, dict) else {}
        update = isinstance(entry, dict) and entry.get('update_of') == slug
    except (OSError, ValueError):
        update = False
        entry = {}
    destination = 'knowledge/'+FOLDERS[card['type']]+'/'+slug+'.md'
    state = 'type_conflict' if any(c['path'] != destination for c in existing) else 'update_conflict' if existing and not update else 'ready'
    digest = hashlib.sha256(json.dumps({'proposal': card, 'existing': existing, 'update': update, 'metadata': entry}, sort_keys=True).encode()).hexdigest()
    notes = []
    if isinstance(entry, dict):
        for flag, reason, label in [('screen_flagged','screen_reason','Source screening'),('taste_flagged','taste_reason','Curator review')]:
            if entry.get(flag): notes.append(label+': '+str(entry.get(reason) or 'needs your review'))
    return {'state': state, 'review_notes': notes, 'fingerprint': digest, 'proposal': card, 'existing': existing, 'destination': destination, 'update': update}


def lock_path(root):
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    return Path.home()/'.sovereign/gate-locks'/(key+'.lock')


def operation_busy(root):
    path = lock_path(root)
    if not path.exists():
        return False
    with path.open('r') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def run_gate(args, env, lock_fd):
    # The command inherits the lock: losing the SSH/helper process cannot allow
    # another console decision while its surviving command still runs.
    with subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True, pass_fds=(lock_fd,)) as process:
        try:
            out, err = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.communicate()
            raise
        return subprocess.CompletedProcess(args, process.returncode, out, err)


def execute(root, lane, slug, verb, expected, command):
    path = lock_path(root); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {'state': 'busy'}
        return execute_locked(root,lane,slug,verb,expected,command,lock.fileno())


def execute_locked(root, lane, slug, verb, expected, command, lock_fd):
    before = check(root, lane, slug)
    if not expected or before.get('fingerprint') != expected:
        return {'state': 'changed', 'check': before}
    if before['state'] != 'ready' and verb == 'approve':
        return {'state': before['state'], 'check': before}
    env = dict(os.environ, SOVS_VAULT=str(root), CURATOR_LANE=lane, CURATOR_ACTOR='console-owner',
               PATH=str(Path.home()/'brain-bin')+':/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin')
    try:
        result = run_gate([str(command), 'gate', verb, slug, 'Owner reviewed in Sovereign'], env, lock_fd)
    except subprocess.TimeoutExpired:
        return {'state': 'uncertain'}
    except OSError:
        return {'state': 'unavailable'}
    detail = result.stdout+'\n'+result.stderr
    prop = root / before['proposal']['path']
    if verb == 'approve':
        destination = root / before['destination']
    else:
        destination = root / 'raw/workspaces' / lane / 'rejected' / (slug+'.md')
    applied = (not prop.exists() and destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == before['proposal']['sha256'])
    if applied:
        warning = result.returncode != 0 or re.search(r'(?i)push failed|warning:|refused|fatal:|error:', detail)
        # The legacy gate can exit zero after a failed commit or push. Check the
        # affected paths and upstream state rather than promising durability.
        is_repo = subprocess.run(['git','-C',str(root),'rev-parse','--git-dir'],capture_output=True).returncode == 0
        if is_repo:
            dirty = subprocess.run(['git','-C',str(root),'status','--porcelain','--',before['proposal']['path'],str(destination.relative_to(root)),'raw/workspaces/'+lane+'/decisions.log'],capture_output=True,text=True)
            ahead = subprocess.run(['git','-C',str(root),'rev-list','--count','@{upstream}..HEAD'],capture_output=True,text=True)
            warning = warning or dirty.returncode != 0 or bool(dirty.stdout.strip()) or ahead.returncode != 0 or ahead.stdout.strip() != '0'
        return {'state': 'sync_pending' if warning else 'approved' if verb == 'approve' else 'rejected', 'verb': verb, 'detail': detail}
    if prop.is_file() and hashlib.sha256(prop.read_bytes()).hexdigest() == before['proposal']['sha256']:
        return {'state': 'failed', 'detail': detail}
    return {'state': 'uncertain', 'detail': detail}


def main():
    try:
        mode, slug = sys.argv[1:3]
        if mode not in ('check','approve','reject'):
            raise ValueError('Unsupported gate operation')
        home = Path.home()
        root = Path((home/'.brain-root').read_text().strip()).expanduser()
        lane = (home/'.curator-lane').read_text().strip() if (home/'.curator-lane').exists() else 'curator'
        if not root.is_absolute() or not (root/'knowledge').is_dir() or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*',lane):
            raise ValueError('Archive configuration is unavailable')
        result = ({'state':'busy'} if operation_busy(root) else check(root,lane,slug)) if mode == 'check' else execute(root,lane,slug,mode,sys.argv[3] if len(sys.argv)>3 else '',home/'brain-bin/sov')
    except (OSError, ValueError, IndexError, UnicodeError):
        result = {'state': 'unavailable'}
    print(json.dumps(result))

if __name__ == '__main__':
    main()
