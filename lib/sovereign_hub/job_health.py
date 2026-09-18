"""Read-only explanations for completed hub runs. A cleared blocker is not recovery."""
import datetime
import os
import plistlib
from pathlib import Path
import re
import subprocess
import time
import tempfile

from brain_redact import redact_text

MAX_OUTPUT = 65536


def next_run(spec, after):
    if spec.get('interval_s'):
        return after + int(spec['interval_s'])
    start = datetime.datetime.fromtimestamp(after)
    for offset in range(9):
        day = start.date() + datetime.timedelta(days=offset)
        if 'weekday' in spec and (day.weekday() + 1) % 7 != int(spec['weekday']):
            continue
        for hour in sorted(spec.get('hours', [spec.get('hour', 0)])):
            candidate = datetime.datetime.combine(day, datetime.time(int(hour), int(spec.get('minute', 0)))).timestamp()
            if candidate > after:
                return candidate
    return None


def read_output(state, job):
    path = Path(state) / 'hub' / (job + '.last-output')
    try:
        if path.is_symlink() or path.stat().st_size > MAX_OUTPUT:
            return ''
        return path.read_text(errors='replace')
    except OSError:
        return ''


def cleared_scan(output, vault, template):
    """Recheck only the complete set of previously rejected paths; never stage/redact."""
    if 'SECRET SCAN FAILED' not in output or '=== FILENAME HITS ===\n(none)' not in output:
        return False
    count = re.search(r'=== SUMMARY: files with content hits: (\d+) ===', output)
    paths = re.findall(r'^--- (.+)$', output, re.M)
    if not count or not paths or len(paths) != int(count[1]) or len(paths) > 20:
        return False
    vault = Path(vault).resolve()
    for name in paths:
        path = vault / name
        if Path(name).is_absolute() or any(x in name for x in ('\n', '\r', '\x00')):
            return False
        try:
            path.resolve().relative_to(vault)
            if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size > 1048576)):
                return False
        except (OSError, ValueError):
            return False
    scanner = Path(template) / 'bin/hub/secret-scan'
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as listing:
            listing.write('\n'.join(paths)+'\n'); listing.flush()
            result = subprocess.run(['/bin/bash', str(scanner), listing.name],
                                    cwd=vault, capture_output=True, text=True, timeout=2)
        return result.returncode == 0 and '=== SUMMARY: files with content hits: 0 ===' in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def schedule_loaded(job, state, template):
    try:
        item = plistlib.loads((Path.home() / 'Library/LaunchAgents' / ('com.sovereign.hub.' + job + '.plist')).read_bytes())
        args = item.get('ProgramArguments', [])
        if len(args) < 3 or args[-2:] != ['tick', job] or Path(args[-3]).resolve() != (Path(template) / 'bin/sov-hub').resolve():
            return False
        if Path(item.get('EnvironmentVariables', {}).get('SOV_STATE_DIR', '')).resolve() != Path(state).resolve():
            return False
        return subprocess.run(['/bin/launchctl', 'print', 'gui/%d/com.sovereign.hub.%s' % (os.getuid(), job)],
                              capture_output=True, timeout=1).returncode == 0
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.TimeoutExpired):
        return False


def describe(job, row, spec, state, template, vault, now=None):
    now = time.time() if now is None else now
    stamp, code = row.get('last_run'), row.get('last_exit')
    if stamp is None or code is None:
        return {'state': 'unknown', 'summary': 'No completed run recorded'}
    if code == 0:
        return {'state': 'healthy', 'summary': 'Last run succeeded'}
    output = read_output(state, job)
    clean, _ = redact_text(output)
    health = {'state': 'needs_attention', 'summary': 'Last run failed',
              'why': 'The job reported a failure. Its captured output is available below.' if output else 'The job reported a failure, but no captured output is available.',
              'action': 'Inspect the failure details and correct the reported cause before retrying.',
              'verify': 'A newer completed run must succeed before this is resolved.',
              'failure_output': '\n'.join(clean.splitlines()[-35:])[:8000],
              'checked_at': now}
    # Only this bounded, read-only verifier can lower a scanner failure. Other
    # failures stay actionable, regardless of a new app version or elapsed time.
    if job == 'autocommit' and spec.get('program') == 'hub/autocommit':
        health['retry_supported'] = True
        if 'SECRET SCAN FAILED' in output:
            health.update(summary='Backup stopped by the credential check',
                          why='The credential check rejected content before a new Git backup was created.',
                          action='Review the flagged files. Remove any real credential or correct a confirmed scanner error, then retry the backup.')
            if cleared_scan(output, vault, template):
                due = next_run(spec, stamp)
                health.update(why='The files rejected by the previous run now pass the current credential check. A successful backup is still unverified.',
                              next_due=due, verification_deadline=due + 900 if due else None,
                              action='Run backup now, or allow the next scheduled run to verify recovery.')
                if not schedule_loaded(job, state, template):
                    health.update(summary='Backup schedule is unavailable',
                                  action='The previous blocker has cleared, but the scheduler could not be verified. Check the hub schedule before retrying.')
                elif due and now <= due + 900:
                    health.update(state='awaiting_verification', summary='Previous blocker cleared; awaiting backup')
                else:
                    health.update(summary='Backup verification is overdue',
                                  action='The expected follow-up run has not succeeded. Check the scheduler and run the backup now.')
        elif 'PUSH FAILED' in output or 'push ' in output and ' failed' in output:
            health.update(summary='Backup could not reach a remote',
                          why='The backup reported a failed push. Inspect the recorded output to identify the destination.',
                          action='Restore access to the failed destination, then run the backup again.')
    return health
