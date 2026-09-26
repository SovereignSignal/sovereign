"""Archive recovery independent of producer transport and VM backup monitoring.

The JSON command routes client requests to the declared authority. Local operations
never change roles, producer definitions, schedules, remotes, or trusted knowledge.
Version-2 backups stream through the native authenticated-encryption helper; the
legacy capsule reader remains available through sov hub restore.
"""
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

import brain_discovery
from sovereign_intake.common import atomic, directory, exclusive, json_read, locked, read_under
from . import core, recovery

PROTOCOL = 1
FORMAT = 2
MAX_ENTRIES = 500000
MAX_BYTES = 1024 ** 4
MAX_MANIFEST = 64 * 1024 * 1024
BLOCK = 1024 * 1024
EXCLUDES = ['repository working trees (repos/)', 'local model weights and caches',
            'external credentials and machine keys', 'unsent work and other hosts or VM images']


def absolute(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('Choose a valid absolute path on the archive host.')
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ValueError('Choose an absolute path on the archive host.')
    return Path(os.path.abspath(p))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(BLOCK), b''): h.update(block)
    return h.hexdigest()


def within(path, root):
    return path == root or root in path.parents


def context(root):
    root = directory(absolute(root))
    for required in ('CLAUDE.md', 'knowledge', 'raw', 'workstreams'):
        if not (root / required).exists():
            raise ValueError('Select a Sovereign archive.')
    machine = brain_discovery.describe()['machine']
    configured = machine.get('vault')
    same = configured and Path(configured).resolve() == root.resolve()
    if same and (machine.get('role') == 'client' or machine.get('hub_pointer')):
        raise ValueError('This archive is maintained by another host. Back up its authoritative copy.')
    if same and machine.get('client_mode') == 'contribute-only':
        raise ValueError('A contribute-only connection cannot back up an archive.')
    state = brain_discovery.state_dir().absolute()
    kind = 'archive'
    managed = None
    cfg = core.config_path()
    if cfg.exists():
        c = core.load(cfg)
        if Path(c['archive']).resolve() == root.resolve():
            managed = c; kind = 'managed'
    inst = json_read(state / 'hub.json', {}) if state.exists() else {}
    if inst and Path(inst.get('vault', '/')).resolve() == root.resolve(): kind = 'template'
    # This index is local lookup only. Persistent archive identity is the UUID in
    # the backup configuration and encrypted manifest, never the path hash.
    store = state / 'archive-backups' / hashlib.sha256(str(root).encode()).hexdigest()[:24]
    return dict(root=root, state=state, store=store, kind=kind, managed=managed,
                machine=machine, owns_state=bool(same), instance=inst if kind == 'template' else {})


def configuration(ctx):
    return json_read(ctx['store'] / 'config.json', {}) if ctx['store'].exists() else {}


def recovery_runtime():
    try:
        return core.python_runtime().resolve()
    except ValueError:
        # A template authority invoked through SSH has no app-provided environment.
        # Reuse discovery's installed app location rather than its system interpreter.
        if os.environ.get('SOV_PYTHON_RUNTIME'): raise
        app = brain_discovery.describe().get('installed_app')
        if app:
            runtime = Path(app) / 'Contents/Resources/runtime'
            if (runtime / 'bin/python3').is_file(): return runtime.resolve()
        raise


def roots(ctx):
    result = [('archive', ctx['root'], {'repos'})]
    if ctx['managed']:
        result.append(('hub', Path(ctx['managed']['destination']), {'logs', 'receipts', '__pycache__'}))
    else:
        engine = Path(__file__).resolve().parents[2]
        for part in ('bin', 'lib', 'connectors', 'templates'):
            if (engine / part).is_dir(): result.append(('engine/' + part, engine / part, {'__pycache__'}))
        runtime = recovery_runtime()
        # A relocatable bundled runtime is required, never copy a system Python tree.
        if not (runtime / 'bin/python3').is_file() or runtime in (Path('/usr'), Path('/System'), Path('/Library/Developer/CommandLineTools/usr')):
            raise ValueError('Use the app with its bundled Python runtime to create a portable backup.')
        result.append(('runtime', runtime, {'__pycache__'}))
    return result


def extra_files(ctx):
    out = []
    if ctx['owns_state'] or ctx['kind'] == 'template':
        for name in ('hub.json', 'connectors.json', 'runs.json', 'clients.json', 'ingest-src.json'):
            p = ctx['state'] / name
            if p.exists(): out.append(('state/' + name, p))
        for p in sorted(ctx['state'].glob('intake-*.json')):
            out.append(('state/' + p.name, p))
        for name in ('.brain-root', '.brain-host', '.brain-core', '.brain-aliases.json', '.curator-lane', '.sovereign-hub'):
            p = Path.home() / name
            if p.exists(): out.append(('pointers/' + name, p))
    if not ctx['managed']:
        engine = Path(__file__).resolve().parents[2]
        if (engine / 'CLAUDE.md').exists(): out.append(('engine/CLAUDE.md', engine / 'CLAUDE.md'))
        out.append(('engine/bin/hub-crypto', core.crypto_tool()))
    return out


def inventory(ctx):
    entries = {}; total = 0
    for prefix, base, excluded in roots(ctx):
        base = directory(base)
        for current, dirs, files in os.walk(base, followlinks=False):
            current = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in excluded)
            for name in list(dirs):
                if (current / name).is_symlink():
                    if prefix == 'archive':
                        dirs.remove(name); continue # recorded without following by link_inventory
                    raise ValueError('A linked directory cannot be backed up: ' + str(current / name))
            for name in sorted(files):
                if name.endswith('.pyc') or name in ('operation.lock', '.DS_Store'): continue
                p = current / name
                if p.is_symlink() and prefix == 'archive': continue
                # Bundled engines/runtime may use internal file aliases. Materialize
                # only links confined to that explicit source tree, never archive links.
                if p.is_symlink() and prefix != 'archive':
                    resolved = p.resolve(strict=True)
                    if not within(resolved, base) or not resolved.is_file():
                        raise ValueError('A dependency link leaves its source tree: ' + str(p))
                    p = resolved
                info = p.lstat()
                if not stat.S_ISREG(info.st_mode): raise ValueError('Unsupported backup entry: ' + str(p))
                rel = str(PurePosixPath(prefix) / (current / name).relative_to(base))
                entries[rel] = (p, signature(info))
                total += info.st_size
                if total > MAX_BYTES or len(entries) > MAX_ENTRIES: raise ValueError('Archive exceeds the supported backup size.')
    for name, p in extra_files(ctx):
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode): raise ValueError('Linked configuration cannot be backed up.')
        if name in entries: total -= entries[name][1][2]
        entries[name] = (p, signature(info)); total += info.st_size
    if total > MAX_BYTES or len(entries) > MAX_ENTRIES: raise ValueError('Archive exceeds the supported backup size.')
    return entries, total


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, stat.S_IMODE(info.st_mode))


def directory_inventory(ctx):
    names = set()
    for prefix, base, excluded in roots(ctx):
        for current, dirs, _ in os.walk(directory(base), followlinks=False):
            current = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in excluded)
            if prefix == 'archive': dirs[:] = [d for d in dirs if not (current/d).is_symlink()]
            if any((current / d).is_symlink() for d in dirs):
                raise ValueError('Linked directories cannot be backed up.')
            names.add(str(PurePosixPath(prefix) / current.relative_to(base)))
            if len(names) > MAX_ENTRIES: raise ValueError('Too many recovery directories.')
    return sorted(names)


def link_inventory(ctx):
    # Preserve references, never follow them while collecting archive content.
    # Flatten their resolved target to a portable path confined to this archive.
    root = ctx['root']; links = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d != 'repos']
        for name in dirs + files:
            path = Path(current)/name
            if not path.is_symlink(): continue
            try: target = path.resolve(strict=False)
            except (RuntimeError,OSError): raise ValueError('A cyclic or unreadable archive link cannot be backed up.') from None
            if not within(target,root): raise ValueError('An archive link leaves the archive: '+str(path))
            links[str(PurePosixPath('archive')/path.relative_to(root))] = str(PurePosixPath('archive')/target.relative_to(root))
            if len(links)>MAX_ENTRIES: raise ValueError('Too many archive links.')
        dirs[:] = [d for d in dirs if not (Path(current)/d).is_symlink()]
    return links


@contextlib.contextmanager
def safe_open(path):
    # Walk every component under directory descriptors, including during the second
    # consistency pass. A symlink swapped into a parent must not escape the source.
    path = absolute(str(path)); parts = path.parts
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        item = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally: os.close(fd)
    with os.fdopen(item, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise ValueError('Backup source is not a regular file.')
        yield f


class HashReader:
    def __init__(self, f): self.f = f; self.hash = hashlib.sha256()
    def read(self, n=-1):
        b = self.f.read(n); self.hash.update(b); return b


def target_identity(folder):
    folder = directory(folder)
    marker = folder / '.sovereign-backup-destination.json'
    value = json_read(marker, {})
    if value and (value.get('version') != 1 or not re.fullmatch(r'[a-f0-9]{32}', value.get('id', ''))):
        raise ValueError('Invalid destination identity.')
    return value.get('id')


def check_target(ctx, config):
    folder = directory(config['folder'])
    if target_identity(folder) != config['destination_id']:
        raise ValueError('The backup destination is disconnected or has changed. Reconnect the original disk or NAS.')
    recovery.check_key(config['key'], ctx['root'], Path(ctx['managed']['destination']) if ctx['managed'] else ctx['state'])
    if within(Path(config['key']), folder): raise ValueError('Keep the recovery key outside the backup destination.')
    return folder


def receipt(ctx, filename):
    return json_read(ctx['store'] / filename, {}) if ctx['store'].exists() else {}


def status(ctx):
    config = configuration(ctx); destinations = []
    if config:
        try:
            folder = check_target(ctx, config)
            problem = None; available = True
            same_disk = folder.stat().st_dev == ctx['root'].stat().st_dev
        except (OSError, ValueError) as e:
            problem = str(e); available = False; same_disk = None
        destinations.append(dict(folder=config['folder'], available=available, problem=problem,
                                 same_disk=same_disk, key=config['key'],
                                 last_success=receipt(ctx, 'last-success.json'), last_attempt=receipt(ctx, 'last-attempt.json'),
                                 last_verification=receipt(ctx, 'verification.json'), last_restore=receipt(ctx, 'restore.json')))
    return dict(protocol=PROTOCOL, host=ctx['machine']['host'], root=str(ctx['root']), mode=ctx['kind'],
                archive_id=config.get('archive_id'), home=str(Path.home()), destinations=destinations, observed_at=time.time(),
                excludes=EXCLUDES, scheduled=False, remote=False,
                scope='Content accepted onto this archive host; producer freshness and VM recovery are separate.')


def prepare(ctx, req):
    action = req['action']; config = configuration(ctx)
    plan = dict(protocol=PROTOCOL, action=action, root=str(ctx['root']), host=ctx['machine']['host'],
                mode=ctx['kind'], scheduled=False, excludes=EXCLUDES)
    if action == 'configure':
        folder = directory(absolute(req.get('folder')))
        for root in (ctx['root'], ctx['state']):
            if within(folder, root) or within(root, folder): raise ValueError('Choose a separate backup folder outside the archive and operating state.')
        if ctx['managed'] and (within(folder, Path(ctx['managed']['destination'])) or within(Path(ctx['managed']['destination']), folder)):
            raise ValueError('Choose a separate backup folder outside the installed Hub.')
        key = absolute(req.get('key'))
        directory(key.parent)
        if within(key, folder) or within(key, ctx['root']) or within(key, ctx['state']):
            raise ValueError('Keep the recovery key outside the archive, operating state and backup destination.')
        if key.exists(): recovery.check_key(key, ctx['root'], Path(ctx['managed']['destination']) if ctx['managed'] else None)
        if key.is_symlink(): raise ValueError('Recovery keys cannot be linked.')
        plan.update(folder=str(folder), key=str(key), create_key=not key.exists(),
                    key_hash=file_hash(key) if key.exists() else None,
                    destination_id=target_identity(folder), folder_identity=[folder.stat().st_dev, folder.stat().st_ino],
                    same_disk=folder.stat().st_dev == ctx['root'].stat().st_dev)
    elif action in ('backup', 'verify', 'restore'):
        if action == 'restore':
            key = recovery.check_key(absolute(req.get('key') or config.get('key')), ctx['root'])
            plan.update(config={'key': str(key)}, key_hash=file_hash(key))
            folder = Path(config['folder']) if config else None
        else:
            if not config: raise ValueError('Add a backup destination first.')
            folder = check_target(ctx, config)
            plan.update(config=config, key_hash=file_hash(Path(config['key'])))
        if action == 'backup':
            entries, size = inventory(ctx)
            links = link_inventory(ctx)
            plan.update(files=len(entries)+len(links), source_bytes=size,
                        free_bytes=shutil.disk_usage(folder).free,
                        includes=['archive and Git history', 'governance state and source-host configuration', 'recovery engine and runtime'])
        else:
            backup = absolute(req.get('backup'))
            if action != 'restore' and (backup.parent != folder or not re.fullmatch(r'[a-f0-9]{32}\.sovbackup', backup.name)):
                raise ValueError('Choose a completed backup in this destination.')
            with safe_open(backup) as f: info = os.fstat(f.fileno())
            plan.update(backup=str(backup), backup_identity=signature(info))
            if action == 'restore':
                destination = absolute(req.get('destination'))
                directory(destination.parent)
                if destination.exists() or destination.is_symlink(): raise ValueError('Restore into a new folder; existing files are preserved.')
                for source in (ctx['root'], ctx['state'], backup.parent):
                    if within(destination, source) or within(source, destination): raise ValueError('Restore outside the archive, backup destination and operating state.')
                plan.update(destination=str(destination), activation_required=True)
    else: raise ValueError('Unknown backup operation.')
    # Free space changes while unrelated jobs run; token binds source and target
    # configuration, not transient counts. Apply inventories again under the lock.
    binding = {k:v for k,v in plan.items() if k not in ('files','source_bytes','free_bytes')}
    plan['token'] = digest(binding)
    return plan


def crypt(mode, key, source, dest):
    subprocess.run([str(core.crypto_tool()), mode + '-stream', str(key), str(source), str(dest)],
                   check=True, capture_output=True, timeout=7200)


def publish(source, destination):
    # macOS exclusive rename publishes complete bytes without requiring hard-link
    # support from a mounted NAS. Unsupported filesystems fail without fallback.
    rename = ctypes.CDLL(None, use_errno=True).renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(source), os.fsencode(destination), 0x00000004): # RENAME_EXCL
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def make_backup(ctx, config):
    folder = check_target(ctx, config); ident = uuid.uuid4().hex
    output = folder / (ident + '.sovbackup')
    entries, size = inventory(ctx); directories = directory_inventory(ctx); links = link_inventory(ctx)
    # Plaintext staging stays in a private local temporary directory. Only
    # authenticated ciphertext is ever written to the selected destination.
    if shutil.disk_usage(folder).free < size + 128 * 1024 * 1024 or shutil.disk_usage(tempfile.gettempdir()).free < 2 * size + 128 * 1024 * 1024:
        raise ValueError('Insufficient space on the destination or in local temporary storage for a complete backup.')
    with tempfile.TemporaryDirectory(prefix='sov-backup-') as work, tempfile.TemporaryDirectory(prefix='.sovereign-incomplete-', dir=folder) as encrypted_work:
        work = Path(work); plain = work / 'data.tar'; sealed = Path(encrypted_work) / 'encrypted'
        manifest = dict(version=FORMAT, archive_id=config['archive_id'], backup_id=ident, created=time.time(),
                        host=ctx['machine']['host'], mode=ctx['kind'], source_root=str(ctx['root']),
                        scheduled=False, excludes=EXCLUDES, directories=directories, links=links, files={})
        with tarfile.open(plain, 'w') as tar:
            for name, (path, before) in sorted(entries.items()):
                with safe_open(path) as f:
                    if signature(os.fstat(f.fileno())) != before: raise ValueError('Source changed before backup. Retry when writers are idle.')
                    header = tarfile.TarInfo(name); header.size=before[2]; header.mode=0o700 if before[5] & 0o111 else 0o600
                    reader = HashReader(f); tar.addfile(header, reader)
                    if signature(os.fstat(f.fileno())) != before: raise ValueError('Source changed during backup. Retry when writers are idle.')
                    manifest['files'][name] = {'sha256':reader.hash.hexdigest(),'size':header.size,'mode':header.mode}
            raw=json.dumps(manifest, sort_keys=True).encode()
            if len(raw)>MAX_MANIFEST: raise ValueError('Recovery manifest is too large.')
            h=tarfile.TarInfo('manifest.json');h.size=len(raw);h.mode=0o600;tar.addfile(h,io.BytesIO(raw))
        after,_=inventory(ctx)
        if after != entries or directory_inventory(ctx) != directories or link_inventory(ctx) != links: raise ValueError('Source inventory changed during backup. Retry when writers are idle.')
        for name,(path,before) in entries.items():
            with safe_open(path) as f:
                reader=HashReader(f)
                while reader.read(BLOCK): pass
                if reader.hash.hexdigest()!=manifest['files'][name]['sha256'] or signature(os.fstat(f.fileno()))!=before:
                    raise ValueError('Source changed during backup. Retry when writers are idle.')
        crypt('seal',config['key'],plain,sealed)
        # Authenticate the saved bytes and manifest before publishing success.
        checked=work/'checked.tar';crypt('open',config['key'],sealed,checked)
        inspect_tar(checked)
        check_target(ctx,config)
        with open(sealed,'rb') as f: os.fsync(f.fileno())
        publish(sealed,output)
        result=dict(state='completed',backup=str(output),backup_id=ident,archive_id=config['archive_id'],
                    finished=time.time(),files=len(entries)+len(links),bytes=output.stat().st_size,
                    sha256=file_hash(output),integrity_verified=True,restore_tested=False)
    atomic(ctx['store']/'last-success.json',result)
    return result


def inspect_tar(path, extract=None):
    actual={}; metadata=None; total=0
    with tarfile.open(path,'r:') as tar:
        for member in tar:
            name=member.name;p=PurePosixPath(name)
            if (not member.isfile() or p.is_absolute() or any(x in ('','.','..') for x in name.split('/'))
                or '\\' in name or any(ord(c)<32 for c in name) or name in actual
                or (p.parts[0]=='manifest.json' and name!='manifest.json')
                or p.parts[0] not in ('archive','hub','engine','runtime','state','pointers','manifest.json')):
                raise ValueError('Unsafe or duplicate recovery entry.')
            total+=member.size
            if total>MAX_BYTES or len(actual)>MAX_ENTRIES or member.size<0: raise ValueError('Recovery exceeds supported size.')
            if name=='manifest.json':
                if metadata is not None or member.size>MAX_MANIFEST: raise ValueError('Invalid recovery manifest.')
                metadata=json.load(tar.extractfile(member));continue
            h=hashlib.sha256()
            target=None
            if extract:
                target=extract/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with contextlib.ExitStack() as stack:
                src=stack.enter_context(tar.extractfile(member))
                dst=stack.enter_context(target.open('xb')) if target else None
                for block in iter(lambda:src.read(BLOCK),b''):
                    h.update(block)
                    if dst:dst.write(block)
            if target:target.chmod(0o700 if member.mode&0o111 else 0o600)
            actual[name]={'sha256':h.hexdigest(),'size':member.size,'mode':0o700 if member.mode&0o111 else 0o600}
    if not isinstance(metadata,dict) or metadata.get('version')!=FORMAT or metadata.get('files')!=actual:
        raise ValueError('Recovery inventory failed verification.')
    directories = metadata.get('directories')
    if not isinstance(directories,list) or len(directories)>MAX_ENTRIES:
        raise ValueError('Invalid recovery directories.')
    seen = set()
    for name in directories:
        if (not isinstance(name,str) or not name or name in seen or name in actual
            or any(x in ('','.','..') for x in name.split('/')) or '\\' in name or any(ord(c)<32 for c in name)
            or PurePosixPath(name).parts[0] not in ('archive','hub','engine','runtime','state','pointers')
            or any(str(parent) in actual for parent in PurePosixPath(name).parents)):
            raise ValueError('Unsafe recovery directory.')
        seen.add(name)
    links = metadata.get('links')
    if not isinstance(links,dict) or len(links)>MAX_ENTRIES: raise ValueError('Invalid archive links.')
    for name,target in links.items():
        for value in (name,target):
            if (not isinstance(value,str) or not value or any(x in ('','.','..') for x in value.split('/'))
                or '\\' in value or any(ord(c)<32 for c in value) or PurePosixPath(value).parts[0]!='archive'):
                raise ValueError('Unsafe archive link.')
        if name=='archive' or name in actual or name in seen or target in links:
            raise ValueError('Conflicting archive link.')
        if any(str(parent) in links for parent in PurePosixPath(target).parents):
            raise ValueError('Archive link target traverses another link.')
    for name in list(actual)+list(seen)+list(links):
        if any(str(parent) in links for parent in PurePosixPath(name).parents):
            raise ValueError('Recovery entry traverses an archive link.')
    if extract:
        for name in directories: (extract/name).mkdir(parents=True,exist_ok=True,mode=0o700)
        # All regular writes and validation finish before creating confined links.
        for name,target in links.items():
            path=extract/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            path.symlink_to(os.path.relpath(extract/target,path.parent))
    if 'archive/CLAUDE.md' not in actual: raise ValueError('Recovery archive is incomplete.')
    required = ('hub/config.json','hub/bin/sov','hub/python/bin/python3') if metadata.get('mode')=='managed' else ('engine/bin/sov','runtime/bin/python3')
    if any(x not in actual for x in required): raise ValueError('Recovery engine is incomplete.')
    return metadata


def verify_or_restore(ctx,config,plan):
    restore=plan['action']=='restore'
    folder=None if restore else check_target(ctx,config)
    key=plan['config']['key']
    parent=Path(plan['destination']).parent if restore else Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix='.sovereign-restore-',dir=parent) as work:
        work=Path(work);encrypted=work/'input';plain=work/'data.tar'
        with safe_open(Path(plan['backup'])) as src, encrypted.open('xb') as dst:
            if list(signature(os.fstat(src.fileno())))!=list(plan['backup_identity']): raise ValueError('Backup changed since preview.')
            shutil.copyfileobj(src,dst,BLOCK)
        crypt('open',key,encrypted,plain)
        metadata=inspect_tar(plain)
        if not restore and metadata.get('archive_id')!=config['archive_id']: raise ValueError('This backup belongs to a different archive.')
        result=dict(state='verified',backup=plan['backup'],backup_id=metadata['backup_id'],finished=time.time(),
                    files=len(metadata['files']),integrity_verified=True,scheduled=False)
        if restore:
            staged=work/'restored';staged.mkdir(mode=0o700);inspect_tar(plain,staged)
            destination=Path(plan['destination'])
            # Restore is inert. No pointers, credentials, jobs, role declarations or
            # producer connections are installed into this machine's live home.
            for name in ('knowledge','raw','workstreams','archive','repos'):
                (staged/'archive'/name).mkdir(parents=True,exist_ok=True,mode=0o700)
            if (staged/'archive/.git/config').exists():
                git=['git','-C',str(staged/'archive')]
                subprocess.run(git+['config','core.hooksPath','/dev/null'],check=True,capture_output=True)
                remotes=subprocess.run(git+['remote'],check=True,capture_output=True,text=True).stdout.splitlines()
                for remote in remotes:subprocess.run(git+['config','--replace-all','remote.'+remote+'.pushurl','disabled://restore-needs-activation'],check=True,capture_output=True)
            if metadata['mode']=='managed':
                cfg=json_read(staged/'hub/config.json');cfg.update(archive=str(destination/'archive'),destination=str(destination/'hub'),snapshot_folder=None,recovery_key=None)
                atomic(staged/'hub/config.json',cfg)
                # Regenerate launch definitions and the front door for the new paths,
                # but do not load them. The existing activation flow stays explicit.
                (staged/'hub/jobs').mkdir(exist_ok=True,mode=0o700)
                (staged/'hub/logs').mkdir(exist_ok=True,mode=0o700)
                (staged/'hub/receipts').mkdir(exist_ok=True,mode=0o700)
                import plistlib
                for job in core.JOBS:
                    (staged/'hub/jobs'/(job+'.plist')).write_bytes(plistlib.dumps(core.job_definition(cfg,job)))
                (staged/'hub/bin/sov').write_bytes(core.launcher(cfg))
            if (staged/'state/hub.json').exists():
                cfg=json_read(staged/'state/hub.json');cfg['vault']=str(destination/'archive')
                # Keep original settings as evidence, never activate external writers.
                atomic(staged/'state/hub.json',cfg)
            atomic(staged/'recovery.json',dict(manifest=metadata,activation_required=True,scheduled=False))
            (staged/'RECOVERY.md').write_text('# Restored archive\n\nOpen the archive folder in Sovereign to inspect notes and load context. No jobs or connections have been activated.\n\nThe encrypted backup preserved archive data and source-host configuration. State and pointers are recovery evidence, not active configuration. Reconnect external credentials and review every producer checkpoint before an explicit authority transfer.\n\nThe previous authoritative host must be stopped before activating a replacement. Existing VM and device backups remain separate.\n')
            destination.mkdir(mode=0o700) # reserve exclusively, never overwrite
            try:
                for child in staged.iterdir():child.rename(destination/child.name)
            except BaseException:
                shutil.rmtree(destination);raise
            result.update(state='restored',destination=str(destination),restore_tested=True,activation_required=True)
        atomic(ctx['store']/('restore.json' if restore else 'verification.json'),result)
        return result


def operate(req, serve=False):
    if req.get('protocol')!=PROTOCOL: raise ValueError('Upgrade Sovereign on the archive host to use this backup interface.')
    action=req.get('action')
    root=absolute(req.get('root'))
    machine=brain_discovery.describe()['machine']
    if serve:
        if machine.get('role')!='hub' or not machine.get('vault') or Path(machine['vault']).resolve()!=root.resolve():
            raise ValueError('This host is not the declared authority for the requested archive.')
    elif machine.get('vault') and Path(machine['vault']).resolve()==root.resolve() and machine.get('role')=='client':
        if machine.get('client_mode')!='read-and-contribute': raise ValueError('This client cannot access archive backups.')
        hub=machine.get('hub_pointer') or ''
        match=re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]{0,100}):(/[^\r\n]+)',hub)
        if not match:raise ValueError('The archive authority is not configured safely.')
        alias,remote_root=match.groups()
        forwarded=dict(req,root=remote_root)
        command=[os.environ.get('SOV_BACKUP_SSH','ssh'),'-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=3',alias,'~/brain-bin/sov backup --serve']
        try:
            r=subprocess.run(command,input=json.dumps(forwarded),capture_output=True,text=True,timeout=7200 if req.get('apply') else 90)
            response=json.loads(r.stdout)
            if not isinstance(response,dict) or response.get('protocol')!=PROTOCOL:raise ValueError()
        except (subprocess.TimeoutExpired,ValueError):
            raise ValueError('The archive host is unavailable or needs the compatible backup engine. No local fallback was used.') from None
        response.update(remote=True,executor=alias)
        return response
    ctx=context(str(root))
    if action=='status':return status(ctx)
    if action=='browse':
        folder=directory(absolute(req.get('folder') or str(Path.home())))
        names=[]
        for p in sorted(folder.iterdir()):
            if len(names)>=200:break
            if not p.is_symlink() and not p.name.startswith('.') and (p.is_dir() or p.suffix in ('.sovbackup','.key')):
                names.append(dict(name=p.name,path=str(p),directory=p.is_dir()))
        return dict(protocol=PROTOCOL,folder=str(folder),parent=str(folder.parent),entries=names,host=machine['host'])
    plan=prepare(ctx,req)
    if not req.get('apply'):return dict(plan,applied=False)
    if not isinstance(req.get('token'),str) or req['token']!=plan['token']:
        raise ValueError('Configuration changed. Preview this backup operation again.')
    directory(ctx['store'],create=True)
    with locked(ctx['store']/'operation.lock'):
        # Revalidate state after acquiring the operation lock.
        if prepare(ctx,req)['token']!=req['token']:raise ValueError('Configuration changed. Preview again.')
        if action=='configure':
            folder=Path(plan['folder']);key=Path(plan['key'])
            if plan['create_key']:exclusive(key,os.urandom(32))
            marker_id=plan['destination_id'] or uuid.uuid4().hex
            if not plan['destination_id']:exclusive(folder/'.sovereign-backup-destination.json',json.dumps(dict(version=1,id=marker_id)).encode())
            old=configuration(ctx)
            recovered=json_read(ctx['root'].parent/'recovery.json',{})
            recovered_id=recovered.get('manifest',{}).get('archive_id')
            if not isinstance(recovered_id,str) or not re.fullmatch(r'[a-f0-9]{32}',recovered_id):recovered_id=None
            config=dict(version=1,archive_id=old.get('archive_id') or recovered_id or uuid.uuid4().hex,folder=str(folder),key=str(key),destination_id=marker_id)
            # Preserve old destination receipts separately if changing targets.
            if old and old!=config:
                history=ctx['store']/('previous-'+uuid.uuid4().hex);history.mkdir(mode=0o700)
                for name in ('config.json','last-attempt.json','last-success.json','verification.json','restore.json'):
                    if (ctx['store']/name).exists():shutil.copy2(ctx['store']/name,history/name)
                for name in ('last-attempt.json','last-success.json','verification.json','restore.json'):
                    if (ctx['store']/name).exists():(ctx['store']/name).unlink()
            atomic(ctx['store']/'config.json',config)
            return dict(protocol=PROTOCOL,applied=True,state='configured',config=config,scheduled=False,
                        note='Keep an independent secure copy of the recovery key. No schedule was created.')
        config=configuration(ctx)
        attempt=dict(action=action,state='running',started=time.time())
        atomic(ctx['store']/'last-attempt.json',attempt)
        try:
            result=make_backup(ctx,config) if action=='backup' else verify_or_restore(ctx,config,plan)
        except BaseException as exc:
            atomic(ctx['store']/'last-attempt.json',dict(attempt,state='failed',finished=time.time(),error=str(exc)[:1000]));raise
        atomic(ctx['store']/'last-attempt.json',dict(attempt,**result))
        return dict(result,protocol=PROTOCOL,applied=True)


def main():
    req = {}
    try:
        raw=(sys.argv[sys.argv.index('--request')+1].encode() if '--request' in sys.argv else sys.stdin.buffer.read(32769))
        if len(raw)>32768:raise ValueError('Backup request is too large.')
        req=json.loads(raw)
        if not isinstance(req,dict):raise ValueError('Invalid backup request.')
        result=operate(req,serve='--serve' in sys.argv)
        print(json.dumps(result));return 1 if result.get('error') else 0
    except (ValueError,OSError,subprocess.SubprocessError,tarfile.TarError) as exc:
        message='Backup encryption or verification failed. Check the recovery key and available storage.' if isinstance(exc,subprocess.CalledProcessError) else str(exc)
        # A failed apply may already have written a key or a failure receipt.
        print(json.dumps(dict(protocol=PROTOCOL,error=message,applied=None if isinstance(req,dict) and req.get('apply') else False)));return 1
