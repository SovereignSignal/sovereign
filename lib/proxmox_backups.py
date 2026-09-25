"""Read Proxmox's job selection and storage inventory without changing the cluster."""
import json
import math


# Sent on SSH stdin. All commands are fixed, read-only pvesh GETs. Storage and job
# names travel as argv elements, never as shell text. Parallel reads share the
# caller's six-second SSH budget, including slow or unavailable storage.
PROBE = r'''
import concurrent.futures, json, socket, subprocess, time

deadline = time.monotonic() + 4.5

def get(path, *options):
    remaining = min(3, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError('Probe deadline reached')
    result = subprocess.run(['pvesh', 'get', path, *options, '--output-format', 'json'],
                            capture_output=True, text=True, timeout=remaining)
    result.check_returncode()
    return json.loads(result.stdout)

def read(path, kind, *options):
    try:
        value = get(path, *options)
        if not isinstance(value, kind):
            raise ValueError('Unexpected response shape')
        return value, None
    except Exception as exc:
        return None, type(exc).__name__

node = socket.gethostname().split('.')[0]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    jf = pool.submit(read, '/cluster/backup', list)
    sf = pool.submit(read, '/nodes/' + node + '/storage', list, '--content', 'backup', '--enabled', '1')
    jobs, jobs_error = jf.result()
    stores, storage_error = sf.result()
    pending, job_rows, storage_rows = [], [], []
    for job in jobs or []:
        if not isinstance(job, dict):
            jobs_error = 'Invalid job record'; continue
        if not job.get('enabled', 1) or job.get('node') not in (None, '', node):
            continue
        row = {k: job.get(k) for k in ('id', 'storage', 'schedule', 'next-run')}
        job_rows.append(row)
        if not isinstance(row['id'], str) or '/' in row['id']:
            row['error'] = 'Invalid job identifier'; continue
        pending.append(('job', row, pool.submit(read, '/cluster/backup/' + row['id'] + '/included_volumes', dict)))
    for storage in stores or []:
        if not isinstance(storage, dict):
            storage_error = 'Invalid storage record'; continue
        name = storage.get('storage')
        row = {'storage': name, 'active': storage.get('active') == 1}
        storage_rows.append(row)
        if not isinstance(name, str) or '/' in name:
            row['error'] = 'Invalid storage identifier'; continue
        if not row['active']:
            row['error'] = 'Storage is unavailable'; continue
        pending.append(('storage', row, pool.submit(read, '/nodes/' + node + '/storage/' + name + '/content', list, '--content', 'backup')))
    for kind, row, future in pending:
        value, error = future.result()
        if error:
            row['error'] = error
        elif kind == 'job':
            children = value.get('children')
            if not isinstance(children, list) or any(not isinstance(v, dict) or not str(v.get('id', '')).isdigit() for v in children):
                row['error'] = 'Invalid guest selection'
            else:
                row['vmids'] = [str(v['id']) for v in children]
        else:
            row['backups'] = [{k: v.get(k) for k in ('vmid', 'ctime', 'volid', 'size', 'content', 'incomplete')}
                              for v in value if isinstance(v, dict)]
            if len(row['backups']) != len(value):
                row['error'] = 'Invalid backup record'
print(json.dumps({'version': 2, 'node': node, 'jobs': job_rows, 'jobs_error': jobs_error,
                  'storages': storage_rows, 'storage_error': storage_error}))
'''


def parse_probe(text):
    value = json.loads(text)
    if (not isinstance(value, dict) or value.get('version') != 2
            or not isinstance(value.get('node'), str)
            or not isinstance(value.get('jobs'), list)
            or not isinstance(value.get('storages'), list)):
        raise ValueError('Invalid Proxmox backup response')
    for row in value['jobs']:
        if not isinstance(row, dict) or ('error' not in row and
                (not isinstance(row.get('vmids'), list) or
                 any(not isinstance(v, str) or not v.isdigit() for v in row['vmids']))):
            raise ValueError('Invalid Proxmox job selection')
    for row in value['storages']:
        if not isinstance(row, dict) or not isinstance(row.get('storage'), str):
            raise ValueError('Invalid Proxmox storage response')
        if 'error' not in row and not isinstance(row.get('backups'), list):
            raise ValueError('Invalid Proxmox backup inventory')
    return value


def vm_status(probe, vmid, now):
    """Absence is conclusive only when every configured backup store answered."""
    inventory = probe.get('inventory') or {}
    errors, backups = [], []
    if inventory.get('storage_error'):
        errors.append('Configured backup storage could not be listed.')
    for storage in inventory.get('storages', []):
        if storage.get('error'):
            errors.append('Could not inspect ' + storage['storage'] + '.')
            continue
        for item in storage['backups']:
            if not isinstance(item, dict):
                errors.append('Invalid backup record on ' + storage['storage'] + '.'); continue
            if str(item.get('vmid')) != str(vmid) or item.get('incomplete'):
                continue
            stamp = item.get('ctime')
            size = item.get('size')
            if (not isinstance(stamp, (int, float)) or isinstance(stamp, bool)
                    or not math.isfinite(stamp) or stamp <= 0 or stamp > now + 300
                    or not isinstance(size, (int, float)) or isinstance(size, bool) or not math.isfinite(size) or size <= 0
                    or not isinstance(item.get('volid'), str)):
                errors.append('Invalid backup metadata on ' + storage['storage'] + '.'); continue
            backups.append(dict(item, storage=storage['storage']))
    latest = max(backups, key=lambda x: x['ctime']) if backups else None
    jobs = [j for j in inventory.get('jobs', []) if str(vmid) in j.get('vmids', [])]
    coverage_known = probe.get('reachable', False) and not inventory.get('jobs_error') and not any(j.get('error') for j in inventory.get('jobs', []))
    if not coverage_known:
        errors.append('Backup job coverage could not be fully checked.')
    return {'jobs': len(jobs) if coverage_known else None, 'backup_jobs': jobs,
            'scheduled': bool(jobs) if coverage_known else None,
            'inventory_complete': probe.get('reachable', False) and not inventory.get('storage_error') and not any(s.get('error') for s in inventory.get('storages', [])) and not any(e.startswith('Invalid backup') for e in errors),
            'last_dump_age_h': round(max(0, now - latest['ctime']) / 3600, 1) if latest else None,
            'last_backup': latest, 'backup_errors': errors,
            'backup_observed_at': probe.get('_at')}
