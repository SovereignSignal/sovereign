"""Best-effort job observations, separate from authoritative completion receipts.

No source names, text, prompts or verdicts enter this record. Missing observations
never stop curation and never establish success. Only runner-owned jobs opt in.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from sovereign_intake.common import atomic, locked

PHASES = {
    'starting': 'Starting', 'waiting_model': 'Waiting for the model',
    'gathering': 'Finding work', 'judging': 'Judging',
    'screening': 'Screening', 'merging': 'Drafting an update',
    'saving': 'Saving results', 'digest': 'Preparing the digest',
    'structure': 'Checking archive structure', 'historicize': 'Reviewing dated cards',
    'retro_taste': 'Checking card quality', 'skip_audit': 'Reviewing skipped items',
    'completed': 'Completed',
}
JOBS = {'nightly', 'curate', 'weekly-audit'}


def _path(state, job):
    if job not in JOBS:
        raise ValueError('Unsupported progress job')
    return Path(state) / 'hub' / (job + '.progress.json')


def _read(path):
    if path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError('Invalid progress file')
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError('Invalid progress record')
    return result


def _process_start(pid):
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                            capture_output=True, text=True, timeout=2,
                            env=dict(os.environ, LC_ALL='C'))
    return result.stdout.strip() if result.returncode == 0 else ''


class Progress:
    def __init__(self, state=None, job=None, run_id=None):
        self.path = _path(state, job) if state and job in JOBS and run_id else None
        self.run_id = run_id

    @classmethod
    def start(cls, state, job):
        record = cls(state, job, uuid.uuid4().hex)
        if record.path is not None:
            try:
                with locked(record.path.with_suffix('.lock')):
                    now = time.time()
                    atomic(record.path, {'version': 1, 'run_id': record.run_id, 'job': job,
                           'owner_pid': os.getpid(), 'process_start': _process_start(os.getpid()),
                           'started_at': now, 'observed_at': now, 'last_progress_at': now,
                           'phase_started_at': now, 'phase': 'starting', 'current': None, 'total': None})
            except (OSError, ValueError, subprocess.SubprocessError):
                record.path = None
        return record

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('SOV_STATE_DIR'), os.environ.get('SOV_PROGRESS_JOB'),
                   os.environ.get('SOV_PROGRESS_RUN'))

    def update(self, phase, current=None, total=None, holder=None, advance=True):
        if self.path is None:
            return
        try:
            with locked(self.path.with_suffix('.lock')):
                data = _read(self.path)
                if data.get('run_id') != self.run_id or phase not in PHASES:
                    return  # A superseded worker may not overwrite a later run.
                now = time.time()
                if data.get('phase') != phase:
                    data['phase_started_at'] = now
                    data['current'] = data['total'] = None
                data.update(phase=phase, observed_at=now)
                if advance:
                    data['last_progress_at'] = now
                for key, value in (('current', current), ('total', total)):
                    if value is not None:
                        if type(value) is not int or value < 0:
                            return
                        data[key] = value
                data.pop('holder', None)
                if holder:
                    match = re.fullmatch(r'(curator-run|sov-audit) pid (\d+) since ([\d :\-]+)', holder.strip())
                    if match:
                        data['holder'] = {'worker': match[1], 'pid': int(match[2]), 'since': match[3]}
                atomic(self.path, data)
        except (OSError, ValueError, TypeError):
            pass  # Visibility must not turn successful work into a failed job.


def read(state, job, now=None):
    """Return a validated observation; probe the runner PID to reject stale files."""
    if job not in JOBS:
        return None
    try:
        data = _read(_path(state, job))
        if (data.get('version') != 1 or data.get('job') != job
                or data.get('phase') not in PHASES
                or not re.fullmatch(r'[a-f0-9]{32}', str(data.get('run_id', '')))
                or type(data.get('owner_pid')) is not int or data['owner_pid'] <= 0):
            return None
        import math
        for key in ('started_at', 'observed_at', 'last_progress_at', 'phase_started_at'):
            if type(data.get(key)) not in (int, float) or not math.isfinite(data[key]):
                return None
        for key in ('current', 'total'):
            if data.get(key) is not None and (type(data[key]) is not int or data[key] < 0):
                return None
        now = time.time() if now is None else now
        if not data['started_at'] <= data['last_progress_at'] <= data['observed_at'] <= now + 5:
            return None
        if not data['started_at'] <= data['phase_started_at'] <= data['observed_at']:
            return None
        live = (data['phase'] != 'completed' and bool(data.get('process_start'))
                and _process_start(data['owner_pid']) == data['process_start'])
        # Select fields explicitly: a malformed record must not smuggle arbitrary text.
        out = {k: data[k] for k in ('run_id', 'job', 'phase', 'started_at', 'observed_at',
                                   'last_progress_at', 'phase_started_at', 'current', 'total')}
        out['active'] = live
        out['checked_at'] = now
        out['elapsed_s'] = max(0, now - data['started_at'])
        out['no_progress_s'] = max(0, now - data['last_progress_at'])
        out['phase_elapsed_s'] = max(0, now - data['phase_started_at'])
        holder = data.get('holder') or {}
        if (data['phase'] == 'waiting_model' and isinstance(holder, dict)
                and holder.get('worker') in ('curator-run', 'sov-audit')
                and type(holder.get('pid')) is int and holder['pid'] > 0):
            out['holder'] = {k: holder[k] for k in ('worker', 'pid')}
        summary = PHASES[data['phase']]
        if data['current'] is not None and data['total'] is not None:
            summary += ' %d/%d' % (data['current'], data['total'])
        if out.get('holder'):
            summary += '; lock reported held by %s (pid %d)' % (holder['worker'], holder['pid'])
        out['summary'] = summary
        return out
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return None


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 2 and sys.argv[1] in PHASES:
        Progress.from_env().update(sys.argv[1])
