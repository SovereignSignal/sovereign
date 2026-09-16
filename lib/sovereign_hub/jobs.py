"""Render the manifest to scheduler items, say what would change, apply only that.

Labels are com.sovereign.hub.<job>. Retiring a hand-written job is explicit (a prefix
the owner names), parks the plist under sovereign-retired/ and boots it out; nothing is
ever deleted. A failed bootstrap rolls back what this apply created, as the managed
hub's activation does.
"""
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from . import instance, manifest

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
    when = "%02d:%02d" % (int(spec["hour"]), int(spec["minute"]))
    return when + (" " + days[int(spec["weekday"])] if "weekday" in spec else " daily")


def status(state, template):
    state = Path(state); hub = state / "hub"; inst = instance.load(state)
    rows = []
    for job_id, spec in sorted(manifest.all_jobs(inst).items()):
        rows.append({"job": job_id, "label": manifest.label(job_id), "schedule": describe(spec),
                     "last_run": _read_int(hub / (job_id + ".last-run")), "last_ok": _read_int(hub / (job_id + ".last-ok")),
                     "last_exit": _read_int(hub / (job_id + ".last-exit"))})
    return rows


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
