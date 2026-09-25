"""Render the manifest to scheduler items, say what would change, apply only that.

Labels are com.sovereign.hub.<job>. Retiring a hand-written job is explicit (a prefix
the owner names), parks the plist under sovereign-retired/ and boots it out; nothing is
ever deleted. A failed bootstrap rolls back what this apply created, as the managed
hub's activation does.
"""
import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

from . import instance, manifest, progress

RETIRED = "sovereign-retired"


def resolver(template):
    """The interpreter bin/_sov-python.sh picks, so a job never names the Xcode shim."""
    r = subprocess.run(["/bin/bash", "-c", '. "$1/bin/_sov-python.sh"; sov_python "$1"', "_", str(template)],
                       capture_output=True, text=True, timeout=15)
    return r.stdout.strip() or "/usr/bin/python3"


def agents_dir(home):
    return Path(home) / "Library" / "LaunchAgents"


def plan(state, template, home, interpreter, retire_prefix=None):
    state = Path(state); template = Path(template); home = Path(home)
    inst = instance.load(state)
    items = []
    for job_id, spec in sorted(manifest.all_jobs(inst).items()):
        item = manifest.render(job_id, spec, template, interpreter, state, home)
        p = agents_dir(home) / (item["Label"] + ".plist")
        raw = plistlib.dumps(item)
        if not p.exists():
            action = "create"
        else:
            action = "unchanged" if p.read_bytes() == raw else "replace"
        items.append({"label": item["Label"], "path": str(p), "action": action, "plist": item})
    retire = []
    if retire_prefix:
        own = {i["label"] for i in items}
        for p in sorted(agents_dir(home).glob(retire_prefix + "*.plist")):
            if p.stem not in own:
                retire.append(str(p))
    return {"items": items, "retire": retire, "interpreter": interpreter}


def _ctl(launchctl, *args):
    return subprocess.run([launchctl] + list(args), capture_output=True, text=True, timeout=30)


def apply(plan_, launchctl, home):
    home = Path(home); la = agents_dir(home); la.mkdir(parents=True, exist_ok=True)
    domain = "gui/%d" % os.getuid()
    created, replaced_backup, loaded = [], [], []
    try:
        for it in plan_["items"]:
            if it["action"] == "unchanged":
                continue
            p = Path(it["path"]); raw = plistlib.dumps(it["plist"])
            if it["action"] == "replace":
                bak = p.with_suffix(".plist.previous"); shutil.copy2(p, bak); replaced_backup.append((p, bak))
                _ctl(launchctl, "bootout", domain + "/" + it["label"])
            else:
                created.append(p)
            p.write_bytes(raw)
            r = _ctl(launchctl, "bootstrap", domain, str(p))
            if r.returncode != 0:
                raise ValueError("bootstrap of %s failed: %s" % (it["label"], (r.stderr or r.stdout).strip()))
            loaded.append(it["label"])
        parked = []
        for path in plan_["retire"]:
            p = Path(path); dest = la / RETIRED; dest.mkdir(exist_ok=True)
            _ctl(launchctl, "bootout", domain + "/" + p.stem)
            shutil.move(str(p), str(dest / p.name)); parked.append(str(dest / p.name))
    except BaseException:
        for label in reversed(loaded):
            _ctl(launchctl, "bootout", domain + "/" + label)
        for p in created:
            if p.exists():
                p.unlink()
        for p, bak in replaced_backup:
            shutil.move(str(bak), str(p))
        raise
    for _, bak in replaced_backup:
        if bak.exists():
            bak.unlink()
    return {"written": [i["label"] for i in plan_["items"] if i["action"] != "unchanged"], "parked": parked}


def _read_int(p):
    try:
        return int(Path(p).read_text().strip())
    except (OSError, ValueError):
        return None


def describe(spec):
    if "interval_s" in spec:
        return "every %ss" % spec["interval_s"]
    days = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
    if "hours" in spec:
        return ",".join("%02d" % int(h) for h in spec["hours"]) + ":%02d daily" % int(spec["minute"])
    when = "%02d:%02d" % (int(spec["hour"]), int(spec["minute"]))
    return when + (" " + days[int(spec["weekday"])] if "weekday" in spec else " daily")


def status(state, template):
    state = Path(state); hub = state / "hub"; inst = instance.load(state)
    rows = []
    for job_id, spec in sorted(manifest.all_jobs(inst).items()):
        rows.append({"job": job_id, "label": manifest.label(job_id), "schedule": describe(spec),
                     "last_run": _read_int(hub / (job_id + ".last-run")), "last_ok": _read_int(hub / (job_id + ".last-ok")),
                     "last_exit": _read_int(hub / (job_id + ".last-exit")),
                     "progress": progress.read(state, job_id)})
    return rows


def verified_loaded_job(job_id, state, template, launchctl='/bin/launchctl', timeout=4):
    """Fail closed unless launchd's active target agrees with its saved manifest.

    launchctl's diagnostic format is not an API. Unknown formats keep an alert
    actionable and prevent retry; a saved plist alone cannot prove what is loaded.
    """
    state, template = Path(state), Path(template)
    spec = manifest.all_jobs(instance.load(state))[job_id]
    plist = agents_dir(Path.home()) / (manifest.label(job_id) + '.plist')
    raw = plist.read_bytes(); installed = plistlib.loads(raw)
    args = installed.get('ProgramArguments', [])
    if not isinstance(args, list) or len(args) != 5 or not all(isinstance(x, str) for x in args):
        raise ValueError('The installed backup job differs from this hub. Review its setup before retrying.')
    expected = manifest.render(job_id, spec, template, args[0], state, Path.home())
    if args != expected['ProgramArguments'] or installed.get('Program', args[0]) != args[0]:
        raise ValueError('The installed backup job differs from this hub. Review its setup before retrying.')
    if installed.get('EnvironmentVariables') != expected['EnvironmentVariables']:
        raise ValueError('The installed backup points at a different hub state or environment.')
    schedule_keys = ('StartInterval', 'StartCalendarInterval')
    if any(installed.get(k) != expected.get(k) for k in schedule_keys):
        raise ValueError('The saved backup schedule differs from the hub manifest.')
    target = 'gui/%d/%s' % (os.getuid(), manifest.label(job_id))
    result = subprocess.run([launchctl, 'print', target], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError('The backup schedule is not loaded. Restore it on the hub before retrying.')
    output = result.stdout

    def field(name):
        values = re.findall(r'^\t' + re.escape(name) + r' = (.+)$', output, re.M)
        return values[0] if len(values) == 1 else None

    def block(name):
        values = re.findall(r'^\t' + re.escape(name) + r' = \{\n((?:\t\t[^\n]*\n)*)\t\}', output, re.M)
        return [line[2:] for line in values[0].splitlines()] if len(values) == 1 else []

    if (not output.startswith(target + ' = {\n') or field('path') != str(plist)
            or field('program') != args[0] or block('arguments') != args):
        raise ValueError('The loaded backup target differs from its saved setup. Reload the hub schedule before retrying.')
    env = {}
    for name in ('default environment', 'inherited environment', 'environment'):
        for line in block(name):
            key, sep, value = line.partition(' => ')
            if not sep:
                raise ValueError('The loaded backup environment could not be verified.')
            env[key] = value
    if (any(env.get(k) != v for k, v in expected['EnvironmentVariables'].items())
            or any((k.startswith(('SOV_', 'GIT_', 'PYTHON')) or k in ('VAULT', 'BASH_ENV', 'ENV', 'XDG_CONFIG_HOME'))
                   and k not in expected['EnvironmentVariables'] for k in env)):
        raise ValueError('The loaded backup uses a different hub state or environment. Reload its schedule before retrying.')
    calendar = []
    for descriptor in re.findall(r'^\t{3}descriptor = \{\n((?:\t{4}[^\n]*\n)*)\t{3}\}', output, re.M):
        values = {}
        for line in descriptor.splitlines():
            match = re.fullmatch(r'\t{4}"(\w+)" => (\d+)', line)
            if not match or match[1] in values:
                raise ValueError('The loaded backup calendar could not be verified.')
            values[match[1]] = int(match[2])
        calendar.append(values)
    wanted = expected.get('StartCalendarInterval', [])
    if isinstance(wanted, dict):
        wanted = [wanted]
    normalize = lambda rows: sorted(tuple(sorted(row.items())) for row in rows)
    interval = field('run interval')
    expected_interval = '%s seconds' % expected['StartInterval'] if 'StartInterval' in expected else None
    streams = re.findall(r'^\t{3}stream = com\.apple\.launchd\.calendarinterval$', output, re.M)
    if normalize(calendar) != normalize(wanted) or len(streams) != len(calendar) or interval != expected_interval:
        raise ValueError('The loaded backup schedule differs from the expected follow-up. Reload the hub schedule.')
    identity = {'program': args[0], 'arguments': args, 'environment': expected['EnvironmentVariables'],
                'calendar': calendar, 'interval': interval, 'plist': str(plist)}
    return {'target': target, 'output': output, 'plist': raw, 'identity': identity}


def uninstall(state, template, home, launchctl, apply_=False):
    inst = instance.load(state); domain = "gui/%d" % os.getuid(); out = []
    for job_id in manifest.all_jobs(inst):
        p = agents_dir(home) / (manifest.label(job_id) + ".plist")
        if p.exists():
            out.append(str(p))
            if apply_:
                _ctl(launchctl, "bootout", domain + "/" + p.stem)
                dest = agents_dir(home) / RETIRED; dest.mkdir(exist_ok=True)
                shutil.move(str(p), str(dest / p.name))
    return out
