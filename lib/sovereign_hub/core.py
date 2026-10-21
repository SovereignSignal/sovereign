import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse

from brain_local import archive_root
from sovereign_intake.common import IntakeError, atomic, directory, exclusive, json_read, locked, read_under

ROOT = Path(__file__).resolve().parents[2]
from .manifest import JOBS as _MANIFEST
# The managed hub's three jobs are a view of the one manifest, so both hub flavours keep the same clock.
JOBS = {
    'nightly': {'hour': _MANIFEST['nightly']['hour'], 'minute': _MANIFEST['nightly']['minute'], 'description': 'Propose durable knowledge for owner review'},
    'audit': {'hour': _MANIFEST['weekly-audit']['hour'], 'minute': _MANIFEST['weekly-audit']['minute'], 'weekday': _MANIFEST['weekly-audit']['weekday'], 'description': 'Report structural archive problems without model calls'},
    'snapshot': {'hour': _MANIFEST['snapshot']['hour'], 'minute': _MANIFEST['snapshot']['minute'], 'description': 'Write an encrypted recovery capsule'},
}
MAX_FILE = 128 * 1024 * 1024


def single_line(value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\n\r\x00'):
        raise ValueError('Use a nonempty value on one line.')
    return value


def absolute(value):
    path = Path(single_line(str(value))).expanduser().absolute()
    for parent in path.parents:
        if parent.is_symlink(): raise ValueError('Linked destinations are not supported.')
    if path.is_symlink():
        raise ValueError('Linked destinations are not supported.')
    return path


def canonical(path):
    # One spelling per folder, for when no folder exists to compare: links resolved,
    # Unicode composed and case folded, as APFS ignores both form and case.
    return unicodedata.normalize('NFC', os.path.realpath(path)).casefold()


def within(path, root):
    """Whether path is root or inside it, judged by the folders on disk, never by text.

    Case, Unicode form and firmlinks (/System/Volumes/Data) give one folder many
    spellings, and a string test let a typed variant put a key or a restore inside
    the archive. A path that does not exist yet is judged by its existing parents."""
    path = Path(os.path.abspath(path))
    try:
        target = os.stat(root)
    except OSError:
        text, base = canonical(path), canonical(root).rstrip('/')
        return text == base or text.startswith(base + '/')
    for p in (path, *path.parents):
        try:
            if os.path.samestat(os.stat(p), target): return True
        except OSError:
            pass
    return False


def same_path(a, b):
    """Whether two paths name one folder; see within."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return canonical(a) == canonical(b)


def inference_guard(endpoint, model):
    # The curator and the audit use this exact predicate; one copy, in lib/.
    from curator_inference import inference_violations
    errors = inference_violations(endpoint, model, model, False)
    if errors:
        raise ValueError('Local inference required: ' + '; '.join(errors))
    url = urllib.parse.urlsplit(endpoint)
    if url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('This local Hub requires a loopback inference endpoint.')
    if url.username or url.password or url.query or url.fragment or url.scheme != 'http':
        raise ValueError('Use a plain local HTTP inference endpoint without credentials.')


def validate(config):
    if config.get('version') != 1 or config.get('platform') != 'Darwin':
        raise ValueError('This Hub package supports macOS only.')
    archive = archive_root(config['archive'])
    for name in ('raw/workspaces', 'raw/tools', 'knowledge/entities', 'knowledge/concepts', 'knowledge/syntheses'):
        directory(archive / name)
    if not re.fullmatch('[a-z][a-z0-9-]{0,40}', config['lane']):
        raise ValueError('Choose a simple curator lane name.')
    single_line(config['model']); inference_guard(config['endpoint'], config['model'])
    if type(config['max_items']) is not int or not 1 <= config['max_items'] <= 200:
        raise ValueError('Choose 1 to 200 items per curation run.')
    return config


def load(path):
    path = absolute(path)
    # Say which path, in both of the ways a hub can be absent. A missing FILE returns
    # the default and falls to the isinstance check below; a missing DIRECTORY raises
    # missing_directory out of read_under, which named nothing at all and is what the
    # owner actually saw when this hub had never been installed here.
    nowhere = ('No installed Hub at %s. Install one, pass --config, or if this machine '
               'runs the template hub use `sov hub jobs status`.' % path)
    try:
        config = json_read(path)
    except IntakeError as exc:
        if str(exc) == 'missing_directory':
            raise ValueError(nowhere) from None
        raise
    if not isinstance(config, dict):
        raise ValueError(nowhere)
    validate(config)
    if Path(config['destination']) != path.parent:
        raise ValueError('This Hub was moved. Restore a capsule to regenerate its paths.')
    return config


def config_path(value=None):
    if value:
        return absolute(value)
    pointer = Path.home() / '.sovereign-hub'
    if pointer.exists():
        data, _ = read_under(pointer.parent, pointer.name, 4096)
        return absolute(data.decode().strip())
    return Path.home() / '.local/share/sovereign/hub/config.json'


def client_hub():
    """Resolve the client role with legacy-first aliases and a bounded pointer read."""
    if os.environ.get('BRAIN_HUB'):
        return os.environ['BRAIN_HUB']
    remote = Path.home() / '.brain-hub'
    if remote.exists():
        value = read_under(remote.parent, remote.name, 4096)[0].decode().strip()
        if value:
            return value
    return os.environ.get('SOVEREIGN_HUB')


def install_plan(archive, destination, model, endpoint='http://127.0.0.1:11434/v1/chat/completions', lane='curator', max_items=40):
    archive = archive_root(archive)
    if client_hub():
        raise ValueError('This Mac is a Client. Existing roles require a reviewed migration.')
    destination = absolute(destination)
    if destination.exists() or within(destination, archive):
        raise ValueError('Choose a new Hub folder outside the archive.')
    # Existing curator lanes and client pointers are never silently converted.
    if (archive / 'raw/workspaces' / lane).exists():
        raise ValueError('This archive already has that curator lane. Existing-Hub migration needs its own reviewed cutover.')
    config = validate(dict(version=1, platform='Darwin', archive=str(archive), destination=str(destination),
                           model=model, endpoint=endpoint, lane=lane, max_items=max_items,
                           snapshot_folder=None, recovery_key=None))
    return dict(config=config, jobs=JOBS, scheduled=False, effects=[
        'Copy the Hub tools and Python runtime into ' + str(destination),
        'Create the curator lane with every gear set to ask-first',
        'Prepare inactive job definitions; activation is a separate preview',
        'Keep existing machine pointers, producers and schedules unchanged'])


def launcher(config):
    d = Path(config['destination'])
    import shlex
    body = '#!/bin/sh\nexport SOV_PYTHON=' + shlex.quote(str(d / 'python/bin/python3')) + '\nexec /bin/bash ' + shlex.quote(str(d / 'engine/bin/sov')) + ' "$@"\n'
    return body.encode()


def engine_command(destination, current, legacy):
    """Restored capsules keep their original engine; select the command they carry."""
    base = Path(destination) / 'engine/bin'
    return base / (legacy if not (base / current).is_file() and (base / legacy).is_file() else current)


def job_definition(config, job):
    d = Path(config['destination']); spec = JOBS[job]
    schedule = {'Hour': spec['hour'], 'Minute': spec['minute']}
    if 'weekday' in spec:
        schedule['Weekday'] = spec['weekday']
    return {'Label': 'com.sovereign.hub.' + job,
            'ProgramArguments': [str(d / 'python/bin/python3'), '-I', '-B', str(engine_command(d, 'sov-managed-hub', 'brain-hub')),
                                 'run', job, '--config', str(d / 'config.json'), '--apply'],
            'StartCalendarInterval': schedule, 'RunAtLoad': False,
            'EnvironmentVariables': {'HOME': str(Path.home()), 'PATH': str(d / 'python/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin'},
            'StandardOutPath': str(d / 'logs' / (job + '.log')),
            'StandardErrorPath': str(d / 'logs' / (job + '.log'))}


def write_jobs(config):
    d = Path(config['destination'])
    for job in JOBS:
        (d / 'jobs' / (job + '.plist')).write_bytes(plistlib.dumps(job_definition(config, job)))
    (d / 'bin/sov').write_bytes(launcher(config)); (d / 'bin/sov').chmod(0o700)


def python_runtime():
    # The bundled executable sits in Resources/runtime/bin; source builds can name that same runtime.
    candidate = Path(os.environ.get('SOV_PYTHON_RUNTIME', ROOT.parent / 'runtime'))
    if not (candidate / 'bin/python3').is_file():
        raise ValueError('Use the complete Sovereign app, or set SOV_PYTHON_RUNTIME to its bundled runtime.')
    return candidate


def crypto_tool():
    candidate = ROOT / 'bin/hub-crypto'
    if not candidate.is_file():
        candidate = ROOT / 'apps/console/build/hub-crypto'
    if not candidate.is_file():
        raise ValueError('Use a complete macOS build containing the recovery encryption helper.')
    return candidate


def install(plan, apply=False):
    config = plan['config']; d = Path(config['destination']); lane = Path(config['archive']) / 'raw/workspaces' / config['lane']
    runtime = python_runtime(); crypto = crypto_tool()
    if not apply:
        return dict(plan, applied=False)
    # Revalidate the no-overwrite boundaries immediately before allocation.
    install_plan(config['archive'], str(d), config['model'], config['endpoint'], config['lane'], config['max_items'])
    made_lane = False
    directory(d.parent, create=True)
    d.mkdir(mode=0o700)
    try:
        for name in ('bin', 'jobs', 'logs', 'receipts'):
            (d / name).mkdir()
        engine = d / 'engine'; engine.mkdir()
        for name in ('bin', 'lib', 'connectors', 'templates'):
            shutil.copytree(ROOT / name, engine / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(ROOT / 'CLAUDE.md', engine / 'CLAUDE.md')
        shutil.copy2(crypto, engine / 'bin/hub-crypto')
        shutil.copytree(runtime, d / 'python')
        lane.mkdir(mode=0o700); made_lane = True
        (lane / 'proposals').mkdir(); (lane / 'rejected').mkdir()
        (lane / 'LANE.md').write_text('---\nproducer: Sovereign curator\nread: local archive\nwrite: proposals\n---\n\nThe curator proposes. The owner decides.\n')
        atomic(lane / 'gears.json', {t: {'new': 'ask-first', 'update': 'ask-first'} for t in ('entity', 'concept', 'synthesis', 'plan', 'review')})
        # Forward-only initialization, equivalent to curator-run --init without a model lock.
        (lane / '.last-run').write_text(str(time.time()))
        atomic(d / 'config.json', config); write_jobs(config)
        atomic(d / 'receipts/install.json', {'at': time.time(), 'scheduled': False, 'state': 'installed'})
    except BaseException:
        if made_lane:
            shutil.rmtree(lane)
        shutil.rmtree(d)
        raise
    return dict(plan, applied=True)


def clean_environment(config):
    d = Path(config['destination'])
    # No inherited model, auto-promotion, credential or scope overrides.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CURATOR_', 'ARCHIVIST_', 'SOVS_', 'SOVEREIGN_', 'BRAIN_')) and k not in ('BRAIN_ROOT', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')}
    env.update(HOME=str(Path.home()), PATH=str(d / 'python/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
               SOVS_VAULT=config['archive'], CURATOR_LANE=config['lane'], CURATOR_MODEL=config['model'],
               CURATOR_ENDPOINT=config['endpoint'], CURATOR_SCREEN='on', CURATOR_LOCAL_ONLY='1', ARCHIVIST_AUTO_PROMOTE_MAX='0', ARCHIVIST_AUTO_REJECT_MAX='0')
    return env


def run(config, job, apply=False, proposal=None, reason=''):
    if job in ('approve', 'reject') and os.environ.get('SOVS_VAULT') and Path(os.environ['SOVS_VAULT']).resolve() != Path(config['archive']).resolve():
        raise ValueError('The reviewed archive differs from the managed Hub archive.')
    if job not in (*JOBS, 'approve', 'reject'):
        raise ValueError('Unknown Hub job.')
    d = Path(config['destination']); b = d / 'engine/bin'
    if job == 'snapshot':
        from .recovery import snapshot
        if not config.get('snapshot_folder') or not config.get('recovery_key'):
            raise ValueError('Choose a recovery folder and key before running snapshots.')
        output = Path(config['snapshot_folder']) / ('sovereign-' + time.strftime('%Y%m%dT%H%M%S') + '.sovbackup')
        return snapshot(config, output, Path(config['recovery_key']), apply)
    if job in ('approve', 'reject'):
        if not proposal or not re.fullmatch('[a-z0-9][a-z0-9-]{0,120}', proposal):
            raise ValueError('Choose a proposal by its simple slug.')
        args = ['/bin/bash', str(b / ('curator-' + job + '.sh')), proposal, reason]
    else:
        program = b / 'curator-run' if job == 'nightly' else engine_command(d, 'sov-audit', 'brain-audit')
        args = [str(d / 'python/bin/python3'), '-B', str(program)]
        args += ['--max', str(config['max_items'])] if job == 'nightly' else ['--no-llm']
    if not apply:
        return {'job': job, 'applied': False, 'command': args, 'archive': config['archive']}
    with locked(d / 'operation.lock'):
        env = clean_environment(config); env['CURATOR_ACTOR'] = 'owner-hub-cli'
        if job in ('approve', 'reject') and (Path(config['archive']) / '.git').exists():
            cp = subprocess.run(['git', '-C', config['archive'], 'rev-parse', '--git-dir'], capture_output=True)
            if cp.returncode == 0:
                for key in ('user.name', 'user.email'):
                    check = subprocess.run(['git', '-C', config['archive'], 'config', key], capture_output=True, text=True)
                    if not check.stdout.strip():
                        raise ValueError('Configure this archive repository\'s Git identity before approving.')
        started = time.time()
        try:
            with subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True) as process:
                try:
                    stdout, stderr = process.communicate(timeout=1800)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
                cp = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            from brain_redact import redact_text
            output, _ = redact_text(cp.stdout + cp.stderr)
            (d / 'logs' / (job + '-last.log')).write_text(output)
            result = {'job': job, 'applied': True, 'exit': cp.returncode, 'started': started, 'finished': time.time(), 'log': str(d / 'logs' / (job + '-last.log'))}
        except subprocess.TimeoutExpired:
            result = {'job': job, 'applied': True, 'exit': 124, 'started': started, 'finished': time.time(), 'error': 'Hub operation timed out.'}
        atomic(d / 'receipts' / (job + '.json'), result)
        return result


def activation_plan(config):
    d = Path(config['destination']); home = Path.home()
    if client_hub():
        raise ValueError('This Mac is a Client. Do not activate a second Hub here.')
    if not config.get('snapshot_folder') or not config.get('recovery_key'):
        raise ValueError('Configure encrypted recovery before enabling scheduled Hub jobs.')
    from .recovery import check_key
    check_key(Path(config['recovery_key']), Path(config['archive']), d)
    directory(config['snapshot_folder'])
    pointers = {'.brain-root': config['archive'], '.curator-lane': config['lane'], '.brain-host': socket.gethostname().split('.')[0], '.sovereign-hub': str(d / 'config.json')}
    for name, value in pointers.items():
        p = home / name
        if p.exists() and read_under(home, name, 4096)[0].decode().strip() != value:
            raise ValueError('Existing machine configuration differs: ' + name)
    manifest_path = home / '.local/state/sovereign/connectors.json'
    manifest = json_read(manifest_path, {}) if manifest_path.parent.is_dir() else {}
    if manifest and manifest.get('machine', {}).get('role') != 'hub':
        raise ValueError('Existing connector setup needs a reviewed migration; it will not be replaced.')
    target_bin = home / 'brain-bin/sov'
    if target_bin.exists() or target_bin.is_symlink():
        if not target_bin.is_symlink() or target_bin.resolve() != (d / 'engine/bin/sov'):
            raise ValueError('Existing brain-bin/sov belongs to another installation.')
    return {'pointers': pointers, 'jobs': [job_definition(config, j) for j in JOBS], 'archive': config['archive'], 'applied': False}


def activate(config, apply=False, confirm=False):
    plan = activation_plan(config)
    if not apply:
        return plan
    if not confirm:
        raise ValueError('Confirm that this will be the only active Hub before activation.')
    d = Path(config['destination']); home = Path.home(); units = home / 'Library/LaunchAgents'
    if not doctor(config)['model_available']:
        raise ValueError('The configured local model is unavailable. Check sov hub doctor before activation.')
    receipt = json_read(d / 'receipts/snapshot.json', {})
    if not receipt.get('sha256'):
        raise ValueError('Create a recovery capsule before activating scheduled jobs.')
    from .recovery import restore, MAX_TOTAL
    capsule = absolute(receipt['output'])
    raw, _ = read_under(capsule.parent, capsule.name, MAX_TOTAL)
    if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('The recovery capsule has changed. Create and verify a new capsule.')
    with tempfile.TemporaryDirectory(prefix='sov-verify-', dir=d) as verification:
        restore(capsule, Path(verification) / 'proof', Path(config['recovery_key']))
    # Never replace a pre-existing unit, even if its label happens to match.
    for job in plan['jobs']:
        if (units / (job['Label'] + '.plist')).exists():
            raise ValueError('A Hub job is already installed. Inspect it before retrying activation.')
    with locked(d / 'operation.lock'):
        created, loaded = [], []
        scheduler = os.environ.get('SOV_LAUNCHCTL', '/bin/launchctl')
        try:
            directory(units, create=True)
            for job in plan['jobs']:
                p = units / (job['Label'] + '.plist'); exclusive(p, plistlib.dumps(job)); created.append(p)
                loaded.append(job['Label'])
                subprocess.run([scheduler, 'bootstrap', 'gui/' + str(os.getuid()), str(p)], check=True, capture_output=True, timeout=15)
            for name, value in plan['pointers'].items():
                p = home / name
                if not p.exists(): exclusive(p, (value + '\n').encode()); created.append(p)
            manifest = home / '.local/state/sovereign/connectors.json'
            if not manifest.exists():
                directory(manifest.parent, create=True); exclusive(manifest, b'{"version":1,"machine":{"role":"hub"},"harnesses":{}}\n'); created.append(manifest)
            directory(home / 'brain-bin', create=True)
            link = home / 'brain-bin/sov'
            if not link.exists(): link.symlink_to(d / 'engine/bin/sov'); created.append(link)
            atomic(d / 'receipts/activation.json', {'at': time.time(), 'state': 'activated', 'jobs': loaded})
        except BaseException:
            failures = []
            for label in reversed(loaded):
                try: subprocess.run([scheduler, 'bootout', 'gui/' + str(os.getuid()) + '/' + label], check=True, capture_output=True, timeout=15)
                except Exception: failures.append(label)
            if failures:
                atomic(d / 'receipts/activation.json', {'at': time.time(), 'state': 'cleanup-required', 'loaded_jobs': failures})
                raise ValueError('Activation failed and some jobs could not be unloaded. Inspect the activation receipt before retrying.')
            for p in reversed(created): p.unlink()
            raise
    return dict(plan, applied=True)


def status(config):
    d = Path(config['destination'])
    return {'config': config, 'jobs': JOBS, 'receipts': {p.stem: json_read(p) for p in sorted((d / 'receipts').glob('*.json'))},
            'note': 'Receipts record completed operations. Current scheduler and model availability are separate checks.'}


def doctor(config):
    import urllib.request
    endpoint = config['endpoint'].rsplit('/', 1)[0] + '/models'
    result = {'model': config['model'], 'endpoint': endpoint, 'model_available': False, 'network': 'loopback only', 'writes': False}
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValueError('Local model redirects are refused.')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(endpoint, timeout=5) as response:
            if response.geturl() != endpoint:
                raise ValueError('Unexpected model endpoint redirect.')
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise ValueError('Model response too large.')
        models = json.loads(raw).get('data', [])
        result['model_available'] = any(m.get('id') == config['model'] for m in models)
        if not result['model_available']: result['error'] = 'The configured model was not listed by the local server.'
    except Exception:
        result['error'] = 'The local model server could not be verified.'
    return result
