"""Bundled gate protocol; runs on the approval machine using only the stdlib.

Reads first. Writes only through the installed owner gate, after matching the
fingerprint the owner reviewed. Resolutions preserve the existing classification and retain both originals.
Never force-approves or retires a card.
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
import tempfile

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


def check(root, lane, slug, *, resolving=False):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,120}', slug):
        return {'state': 'invalid'}
    if not resolving and resolution_pending(root, lane, slug):
        return {'state': 'resolution_pending'}
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
        target = entry.get('update_of')
        if target and target != slug:
            state = 'target_conflict'
            notes.append('This update targets '+str(target)+'. Consolidate it under the target card before approval.')
        sources = entry.get('source_refs')
        if isinstance(sources, list) and len(sources) > 1:
            notes.append('Combined source evidence requires owner review: '+ '; '.join(
                str(row.get('source', 'unknown')) for row in sources if isinstance(row, dict)))
        for flag, reason, label in [('screen_flagged','screen_reason','Source screening'),('taste_flagged','taste_reason','Curator review')]:
            if entry.get(flag): notes.append(label+': '+str(entry.get(reason) or 'needs your review'))
    return {'state': state, 'review_notes': notes, 'fingerprint': digest, 'proposal': card, 'existing': existing, 'destination': destination, 'update': update, 'metadata_fingerprint': hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()}


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
        if verb == 'resolve':
            return resolve_locked(root,lane,slug,expected,command,lock.fileno())
        if verb not in ('approve','reject'):
            return {'state':'invalid'}
        return execute_locked(root,lane,slug,verb,expected,command,lock.fileno())


def rejection_paths(root, lane, slug):
    folder = root / 'raw/workspaces' / lane / 'rejected'
    pattern = re.compile(re.escape(slug) + r'(?:--rejected-\d{8}-\d{6})?\.md')
    return {p for p in folder.glob(slug+'*.md') if pattern.fullmatch(p.name)}


def matches_reviewed(path, root, expected):
    return (not path.is_symlink() and root.resolve() in path.resolve().parents
            and path.is_file() and path.stat().st_size <= LIMIT
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected)


def execute_locked(root, lane, slug, verb, expected, command, lock_fd, *, resolving=False):
    before = check(root, lane, slug, resolving=resolving)
    if not expected or before.get('fingerprint') != expected:
        return {'state': 'changed', 'check': before}
    if before['state'] != 'ready' and verb == 'approve':
        return {'state': before['state'], 'check': before}
    env = dict(os.environ, SOVS_VAULT=str(root), CURATOR_LANE=lane, CURATOR_ACTOR='console-owner',
               PATH=str(Path.home()/'brain-bin')+':/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin')
    prior_rejections = rejection_paths(root, lane, slug) if verb == 'reject' else set()
    try:
        result = run_gate([str(command), 'gate', verb, slug, 'Owner approved update retaining existing classification in Sovereign' if resolving else 'Owner reviewed in Sovereign'], env, lock_fd)
    except subprocess.TimeoutExpired:
        return {'state': 'uncertain'}
    except OSError:
        return {'state': 'unavailable'}
    detail = result.stdout+'\n'+result.stderr
    prop = root / before['proposal']['path']
    if verb == 'approve':
        destination = root / before['destination']
    else:
        # Only newly created destinations count. An older matching rejection is
        # not evidence that this decision completed.
        matches = [p for p in rejection_paths(root,lane,slug) - prior_rejections
                   if matches_reviewed(p,root,before['proposal']['sha256'])]
        destination = matches[0] if len(matches) == 1 else None
    applied = (not prop.exists() and destination is not None
               and matches_reviewed(destination,root,before['proposal']['sha256']))
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


def resolution_record(root, lane, slug):
    key = hashlib.sha256((str(root.resolve())+'\0'+lane+'\0'+slug).encode()).hexdigest()
    return lock_path(root).parent / 'resolutions' / (key+'.json')


def resolution_pending(root, lane, slug):
    record = resolution_record(root,lane,slug)
    if not record.exists():
        return False
    try:
        return json.loads(record.read_text()).get('status') not in ('completed','restored')
    except (OSError, ValueError, AttributeError):
        return True


def can_resolve(review):
    existing = review.get('existing', [])
    if review.get('state') != 'type_conflict' or not review.get('update') or len(existing) != 1:
        return False
    card = existing[0]
    kind = card.get('type')
    return (kind in FOLDERS and card['path'].split('/')[-2] == FOLDERS[kind]
            and kind != review['proposal']['type'])


def atomic_write(path, data):
    # The temporary file and replacement share a directory. Flush both file and
    # directory so an interrupted decision retains a durable recovery record.
    fd, name = tempfile.mkstemp(prefix='.resolution-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(name,path)
        directory = os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def resolve_locked(root, lane, slug, expected, command, lock_fd):
    before = check(root,lane,slug)
    if not expected or before.get('fingerprint') != expected:
        return {'state':'changed','check':before}
    if not can_resolve(before):
        return {'state':before['state'],'check':before}
    prop = root / before['proposal']['path']
    existing = root / before['existing'][0]['path']
    original = prop.read_bytes(); trusted = existing.read_bytes()
    if (hashlib.sha256(original).hexdigest() != before['proposal']['sha256']
            or hashlib.sha256(trusted).hexdigest() != before['existing'][0]['sha256']):
        return {'state':'changed'}
    # Only the reviewed classification changes; no generated merge or content edit.
    text = original.decode('utf-8')
    match = re.fullmatch(r'---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)',text,re.S)
    if match is None: return {'state':'invalid'}
    labels = match[1]
    if len(re.findall(r'(?m)^type:',labels)) != 1:
        return {'state':'invalid'}
    kind = before['existing'][0]['type']
    labels = re.sub(r'(?m)^type:[^\r\n]*', 'type: '+kind, labels)
    resolved = (text[:match.start(1)]+labels+text[match.end(1):]).encode('utf-8')
    record = resolution_record(root,lane,slug)
    record.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='originals-',dir=record.parent))
    atomic_write(backup/'proposal.md',original)
    atomic_write(backup/'existing.md',trusted)
    receipt = {'status':'pending','slug':slug,'lane':lane,'root':str(root),
               'fingerprint':expected,'retained_type':kind,'originals':str(backup),
               'proposal_sha256':before['proposal']['sha256'],
               'existing_sha256':before['existing'][0]['sha256'],
               'resolved_sha256':hashlib.sha256(resolved).hexdigest()}
    # All backups precede mutation; the durable pending marker blocks another
    # console decision after interruption. No draft is rewritten before final approval.
    if check(root,lane,slug).get('fingerprint') != expected:
        return {'state':'changed'}
    atomic_write(record,(json.dumps(receipt,sort_keys=True)+'\n').encode())
    try:
        atomic_write(prop,resolved)
        current = check(root,lane,slug,resolving=True)
        expected_proposal = dict(before['proposal'],type=kind,sha256=receipt['resolved_sha256'])
        if (current.get('proposal') != expected_proposal or current.get('existing') != before['existing']
                or current.get('metadata_fingerprint') != before.get('metadata_fingerprint')):
            result = {'state':'changed'}
        else:
            result = execute_locked(root,lane,slug,'approve',current.get('fingerprint'),command,lock_fd,resolving=True)
        if result['state'] in ('approved','sync_pending'):
            receipt['status']='completed'
        elif (matches_reviewed(prop,root,receipt['resolved_sha256'])
              and matches_reviewed(existing,root,receipt['existing_sha256'])):
            # A known no-change failure restores the original proposal. An
            # uncertain command may have surviving effects; never restore it blindly.
            if result['state'] in ('failed','unavailable','changed','ready','type_conflict','update_conflict'):
                atomic_write(prop,original);receipt['status']='restored'
        atomic_write(record,(json.dumps(receipt,sort_keys=True)+'\n').encode())
        if receipt['status']=='pending':
            return {'state':'resolution_pending','detail':result.get('detail','')}
        return dict(result, resolution={'retained_type':kind,'originals_saved':True})
    except (OSError, ValueError):
        # Originals and the pending record survive partial work. A subsequent
        # check must report recovery required, never retry approval automatically.
        return {'state':'resolution_pending'}


def main():
    try:
        mode, slug = sys.argv[1:3]
        if mode not in ('check','approve','reject','resolve'):
            raise ValueError('Unsupported gate operation')
        home = Path.home()
        pointer = home / '.brain-root'
        legacy_pointer = pointer.read_text().strip() if pointer.exists() else ''
        configured_root = (os.environ.get('BRAIN_ROOT') or os.environ.get('SOVS_VAULT') or legacy_pointer
                           or os.environ.get('SOVEREIGN_ROOT') or os.environ.get('SOVEREIGN_VAULT'))
        if not configured_root:
            raise ValueError('Archive configuration is unavailable')
        root = Path(configured_root).expanduser()
        lane = (home/'.curator-lane').read_text().strip() if (home/'.curator-lane').exists() else 'curator'
        if not root.is_absolute() or not (root/'knowledge').is_dir() or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*',lane):
            raise ValueError('Archive configuration is unavailable')
        result = ({'state':'busy'} if operation_busy(root) else check(root,lane,slug)) if mode == 'check' else execute(root,lane,slug,mode,sys.argv[3] if len(sys.argv)>3 else '',home/'brain-bin/sov')
    except (OSError, ValueError, IndexError, UnicodeError):
        result = {'state': 'unavailable'}
    print(json.dumps(result))

if __name__ == '__main__':
    main()
