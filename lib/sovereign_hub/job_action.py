"""Preview and request the installed backup job; never interrupt or run arbitrary jobs."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import urllib.parse

from sovereign_config import pointer
from . import instance, jobs, manifest, runner


def push_destinations(vault, names):
    """Resolve all effective push URLs without contacting a remote or exposing credentials."""
    if not isinstance(names, list) or any(not isinstance(n, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', n) for n in names):
        raise ValueError('The backup destinations must be configured Git remote names.')
    destinations, labels = {}, []
    for name in names:
        result = subprocess.run(['git', '-C', str(vault), 'remote', 'get-url', '--push', '--all', name],
                                capture_output=True, text=True, timeout=2)
        urls = result.stdout.splitlines()
        if result.returncode or not urls:
            raise ValueError('A configured backup destination could not be resolved. Review the hub Git remotes.')
        destinations[name] = urls
        for url in urls:
            if '://' in url:
                host = urllib.parse.urlsplit(url).hostname or 'configured server'
            else:
                match = re.fullmatch(r'(?:[^/@:]+@)?([^/:]+):.+', url)
                host = match[1] if match else 'local repository'
            labels.append('%s (%s)' % (name, host))
    return destinations, labels


def retry(vault, token=None, apply=False, state=None, template=None, ctl='/bin/launchctl'):
    state = Path(state or runner.state_dir())
    template = Path(template or runner.template_root())
    inst = instance.load(state)
    if Path(inst['vault']).resolve() != Path(vault).resolve():
        raise ValueError('The hub configuration belongs to a different archive. Refresh before retrying.')
    spec = manifest.all_jobs(inst).get('autocommit', {})
    if spec.get('program') != 'hub/autocommit':
        raise ValueError('This backup uses a custom program. Review it on the hub before running it.')
    loaded = jobs.verified_loaded_job('autocommit', state, template, ctl)
    if re.search(r'^\s*pid\s*=\s*\d+', loaded['output'], re.M) or (state / 'hub/autocommit.lock').exists():
        raise ValueError('A backup is already running or holds its lock. Wait for completion, then refresh.')
    destinations, labels = push_destinations(vault, inst['remotes'])
    receipt = next(x for x in jobs.status(state, template) if x['job'] == 'autocommit')
    contents = [(state / 'hub.json').read_bytes(), loaded['plist'], json.dumps(receipt, sort_keys=True).encode(),
                json.dumps(loaded['identity'], sort_keys=True).encode(), json.dumps(destinations, sort_keys=True).encode()]
    contents += [(template / name).read_bytes() for name in ('bin/hub/autocommit', 'bin/hub/secret-scan', 'bin/sov-redact',
                 'bin/sov-hub', 'lib/sovereign_hub/runner.py', 'lib/sovereign_hub/manifest.py', 'lib/sovereign_hub/instance.py')]
    fingerprint = hashlib.sha256(b'\0'.join(contents)).hexdigest()
    if apply:
        if not token or token != fingerprint:
            raise ValueError('The job, its destinations or its last run changed. Preview this backup again before confirming.')
        result = subprocess.run([ctl, 'kickstart', loaded['target']], capture_output=True, text=True, timeout=4)
        if result.returncode:
            raise ValueError('The scheduler did not accept the request. Refresh the hub before retrying.')
    return {'state': 'requested' if apply else 'preview', 'token': fingerprint, 'vault': str(vault),
            'summary': ('Save archive changes and push them to: ' + ', '.join(labels) + '.') if labels else 'Save archive changes locally. No remote backup destinations are configured.',
            'effects': 'The normal backup checks and credential redaction still apply. Existing files may be redacted before saving. A running backup will not be interrupted.',
            'verification': 'Request accepted. Refresh to inspect the new completed run; success is not yet verified.' if apply else 'No backup has been started.'}


def route(root, token=None, apply=False):
    configured = pointer(Path.home() / '.brain-root')
    if not configured or Path(configured).resolve() != Path(root).resolve():
        raise ValueError('Open the configured archive and refresh before running its backup.')
    hub = pointer(Path.home() / '.brain-hub')
    binding = hashlib.sha256((str(Path(root).resolve()) + '\0' + (hub or 'local')).encode()).hexdigest()
    if apply:
        prefix, separator, inner = (token or '').partition(':')
        if not separator or prefix != binding:
            raise ValueError('The configured hub changed. Preview the backup again.')
        token = inner
    if not hub:
        payload = retry(root, token, apply)
        payload['token'] = binding + ':' + payload['token']
        return payload
    alias, separator, vault = hub.partition(':')
    if not separator or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', alias) or not vault.startswith('/') or any(c in vault for c in '\n\r\x00'):
        raise ValueError('The configured hub connection is invalid.')
    command = ['hub', 'retry', '--vault', vault]
    if apply:
        command += ['--apply', '--token', token or '']
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=4', alias,
                             '~/brain-bin/sov ' + shlex.join(command)], capture_output=True, text=True, timeout=10)
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError('The hub did not return a backup preview. Check its connection and installed version.')
    if not isinstance(payload, dict):
        raise ValueError('The hub returned an invalid backup response. Refresh before retrying.')
    if result.returncode or payload.get('error'):
        raise ValueError(payload.get('error') or 'The hub could not complete the request.')
    if payload.get('token'):
        payload['token'] = binding + ':' + payload['token']
    payload['hub'] = alias
    return payload
