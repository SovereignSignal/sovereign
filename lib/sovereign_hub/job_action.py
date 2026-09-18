"""Preview and request the installed backup job; never interrupt or run arbitrary jobs."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess

from sovereign_config import pointer
from . import instance, jobs, manifest, runner


def retry(vault, token=None, apply=False, state=None, template=None, ctl='/bin/launchctl'):
    state = Path(state or runner.state_dir())
    template = Path(template or runner.template_root())
    inst = instance.load(state)
    if Path(inst['vault']).resolve() != Path(vault).resolve():
        raise ValueError('The hub configuration belongs to a different archive. Refresh before retrying.')
    spec = manifest.all_jobs(inst).get('autocommit', {})
    if spec.get('program') != 'hub/autocommit':
        raise ValueError('This backup uses a custom program. Review it on the hub before running it.')
    plist = Path.home() / 'Library/LaunchAgents' / (manifest.label('autocommit') + '.plist')
    raw = plist.read_bytes()
    installed = plistlib.loads(raw)
    args = installed.get('ProgramArguments', [])
    if len(args) < 3 or args[-2:] != ['tick', 'autocommit'] or Path(args[-3]).resolve() != (template / 'bin/sov-hub').resolve():
        raise ValueError('The installed backup job differs from this hub. Review its setup before retrying.')
    if Path(installed.get('EnvironmentVariables', {}).get('SOV_STATE_DIR', '')).resolve() != state.resolve():
        raise ValueError('The installed backup points at a different hub state directory.')
    target = 'gui/%d/%s' % (os.getuid(), manifest.label('autocommit'))
    result = subprocess.run([ctl, 'print', target], capture_output=True, text=True, timeout=4)
    if result.returncode:
        raise ValueError('The backup schedule is not loaded. Restore it on the hub before retrying.')
    if re.search(r'^\s*pid\s*=\s*\d+', result.stdout, re.M) or (state / 'hub/autocommit.lock').exists():
        raise ValueError('A backup is already running or holds its lock. Wait for completion, then refresh.')
    receipt = next(x for x in jobs.status(state, template) if x['job'] == 'autocommit')
    contents = [(state / 'hub.json').read_bytes(), raw, json.dumps(receipt, sort_keys=True).encode()]
    contents += [(template / name).read_bytes() for name in ('bin/hub/autocommit', 'bin/hub/secret-scan', 'bin/sov-redact')]
    fingerprint = hashlib.sha256(b'\0'.join(contents)).hexdigest()
    if apply:
        if not token or token != fingerprint:
            raise ValueError('The job or its last run changed. Preview this backup again before confirming.')
        result = subprocess.run([ctl, 'kickstart', target], capture_output=True, text=True, timeout=4)
        if result.returncode:
            raise ValueError('The scheduler did not accept the request. Refresh the hub before retrying.')
    return {'state': 'requested' if apply else 'preview', 'token': fingerprint, 'vault': str(vault),
            'summary': 'Save archive changes and push them to the configured Git remotes.',
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
