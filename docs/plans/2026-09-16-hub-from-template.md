# Hub from the template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hub installable from the template: a manifest of jobs, an instance file for the owner's settings, a fail-loud runner, `sov hub jobs install`, a nightly encrypted rebuild kit pushed off-site, a runbook, and a Part 1 drift check.

**Architecture:** New modules under `lib/sovereign_hub/` (manifest, instance, runner, jobs, kit) reached through a new `bin/sov-hub` entry that `bin/sov hub` dispatches to for the new subcommands while the existing managed-hub commands keep going to `bin/sov-managed-hub`. Hub scripts move into `bin/hub/` unchanged in logic and read their settings from `sov hub env`. Everything is rendered from the manifest plus `~/.local/state/sovereign/hub.json`; nothing owner-specific enters the template.

**Tech Stack:** Python 3.9-compatible stdlib only (the system interpreter is 3.9.6), bash for the moved scripts, launchd plists via `plistlib`, the existing `hub-crypto` sealing tool, the existing test style (`unittest`, throwaway HOME, stub `launchctl` on PATH).

**Spec:** `docs/specs/2026-09-15-hub-from-template-design.md`

## Global Constraints

- Python code must run on 3.9.6 (no `match`, no `X | Y` types, no `str.removeprefix` reliance).
- No name, domain, path or host of the owner's in any shipped file (`tests/test_template_is_general.py` enforces it).
- Every rendered job's interpreter comes from the resolver in `bin/_sov-python.sh`, never a literal `/usr/bin/python3`.
- State lives under `$SOV_STATE_DIR` (default `~/.local/state/sovereign`); tests set it to a temp dir.
- `launchctl` is reached through `$SOV_LAUNCHCTL` (default `/bin/launchctl`); tests point it at a stub.
- Notifications go through `$SOV_NOTIFY` (default `<template>/bin/sov-notify-telegram`); tests point it at a stub that logs.
- Commits on branch `feat/hub-from-template`, one per task, message ends with the Co-Authored-By line used in this repo.
- Run tests from `tests/` with `/usr/bin/python3 -m pytest -q -p no:cacheprovider <file>`.

---

### Task 1: The manifest and the plist renderer

**Files:**
- Create: `lib/sovereign_hub/manifest.py`
- Test: `tests/test_hub_manifest.py`

**Interfaces:**
- Produces: `JOBS: dict[str, dict]`, `label(job_id) -> str`, `render(job_id, spec, template_root: Path, interpreter: str, state_dir: Path, home: Path) -> dict` (a launchd plist as a dict), `all_jobs(instance: dict) -> dict[str, dict]` (template jobs merged with `instance["instance_jobs"]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_manifest.py
"""The manifest is the one place hub jobs are defined. Every job renders to a launchd item
whose program is the resolver's interpreter running the hub runner, never the Xcode shim."""
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import manifest  # noqa: E402


class Manifest(unittest.TestCase):
    def test_every_job_has_a_program_a_schedule_and_a_description(self):
        self.assertGreaterEqual(len(manifest.JOBS), 10)
        for job_id, spec in manifest.JOBS.items():
            self.assertRegex(job_id, r"^[a-z][a-z0-9-]*$")
            self.assertTrue(spec["program"], job_id)
            self.assertTrue(spec["description"], job_id)
            self.assertTrue(("interval_s" in spec) ^ ("hour" in spec), job_id)

    def test_render_names_the_runner_on_the_given_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item = manifest.render("nightly", manifest.JOBS["nightly"], ROOT, "/opt/py/bin/python3", tmp / "state", tmp / "home")
            self.assertEqual(item["Label"], "com.sovereign.hub.nightly")
            self.assertEqual(item["ProgramArguments"][:3], ["/opt/py/bin/python3", "-B", str(ROOT / "bin" / "sov-hub")])
            self.assertEqual(item["ProgramArguments"][3:], ["tick", "nightly"])
            self.assertEqual(item["StartCalendarInterval"], {"Hour": 6, "Minute": 0})
            self.assertNotIn("StartInterval", item)
            self.assertTrue(item["StandardErrorPath"].endswith("hub/nightly.error.log"))
            self.assertNotIn("/usr/bin/python3", str(item))
            plistlib.dumps(item)  # serialisable

    def test_interval_jobs_render_with_start_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item = manifest.render("verdict-poll", manifest.JOBS["verdict-poll"], ROOT, "/opt/py/bin/python3", tmp, tmp)
            self.assertEqual(item["StartInterval"], 60)
            self.assertNotIn("StartCalendarInterval", item)

    def test_weekday_jobs_carry_the_weekday(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item = manifest.render("weekly-audit", manifest.JOBS["weekly-audit"], ROOT, "/opt/py/bin/python3", tmp, tmp)
            self.assertEqual(item["StartCalendarInterval"], {"Hour": 10, "Minute": 0, "Weekday": 5})

    def test_instance_jobs_join_the_manifest_without_replacing_it(self):
        inst = {"instance_jobs": {"health": {"program": "/opt/venv/bin/python3", "args": ["/opt/scripts/health.py"],
                                             "hour": 9, "minute": 0, "deliver": True, "description": "Daily health"}}}
        jobs = manifest.all_jobs(inst)
        self.assertIn("nightly", jobs)
        self.assertEqual(jobs["health"]["program"], "/opt/venv/bin/python3")
        with self.assertRaises(ValueError):
            manifest.all_jobs({"instance_jobs": {"nightly": {"program": "/x", "hour": 1, "minute": 0}}})

    def test_managed_hub_jobs_are_a_view_of_the_manifest(self):
        from sovereign_hub import core
        for job_id in ("nightly", "snapshot"):
            self.assertEqual(core.JOBS[job_id]["hour"], manifest.JOBS[job_id]["hour"])
            self.assertEqual(core.JOBS[job_id]["minute"], manifest.JOBS[job_id]["minute"])
        self.assertEqual(core.JOBS["audit"]["hour"], manifest.JOBS["weekly-audit"]["hour"])
        self.assertEqual(core.JOBS["audit"]["weekday"], manifest.JOBS["weekly-audit"]["weekday"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_manifest.py`
Expected: `ModuleNotFoundError: No module named 'sovereign_hub.manifest'`

- [ ] **Step 3: Write the manifest**

```python
# lib/sovereign_hub/manifest.py
"""The hub's jobs, defined once.

Every hub, whether installed from the app or run from a template checkout, renders its
scheduler items from this table plus the owner's instance file. A job's program is a
path relative to the template's bin/ (or absolute for an instance job), and every job
runs through the hub runner (`sov-hub tick <id>`), which is what gives it receipts,
one log line, an alert on failure and delivery of clean output when `deliver` is set.

Schedules: a calendar job has `hour` and `minute` (and optionally `weekday`, 0=Sunday
as launchd counts); an interval job has `interval_s`. Exactly one of the two.
"""
from pathlib import Path

LABEL_PREFIX = "com.sovereign.hub."

JOBS = {
    "nightly": {"program": "hub/nightly", "hour": 6, "minute": 0, "deliver": True,
                "description": "Judge new raw material and propose durable knowledge; deliver the digest"},
    "burndown": {"program": "hub/burndown", "hour": 6, "minute": 27, "deliver": False,
                 "description": "Judge older material under the keep floor until it stops earning its place"},
    "weekly-audit": {"program": "hub/weekly-audit", "hour": 10, "minute": 0, "weekday": 5, "deliver": True,
                     "description": "Propose-only structural audit of the trusted layer"},
    "weekly-landed": {"program": "hub/weekly-landed", "hour": 17, "minute": 0, "weekday": 0, "deliver": False,
                      "description": "What landed on its own this week, with a revert line per card"},
    "verdict-poll": {"program": "hub/verdict-poll", "interval_s": 60, "deliver": False,
                     "description": "Relay the owner's Telegram verdicts to the gate scripts"},
    "autocommit": {"program": "hub/autocommit", "hour": 4, "minute": 30, "deliver": False,
                   "description": "Commit the vault and push every remote, scanning what enters history"},
    "snapshot": {"program": "hub/snapshot", "hour": 3, "minute": 0, "deliver": False,
                 "description": "Daily full-tree snapshot of the vault with rotation"},
    "exchange-sync": {"program": "hub/exchange-sync", "interval_s": 1800, "deliver": False,
                      "description": "Push the vault and template to the exchange; merge producer lanes that stay inside their lane"},
    "fleet-watch": {"program": "sov-fleet-watch", "interval_s": 300, "deliver": True,
                    "description": "Edge-triggered reachability watch over the declared fleet"},
    "kit": {"program": "hub/kit", "hour": 3, "minute": 30, "deliver": False,
            "description": "Encrypt the rebuild kit, copy it off-site, mirror-push the vault and template"},
}


def label(job_id):
    return LABEL_PREFIX + job_id


def _schedule(spec):
    if "interval_s" in spec:
        return {"StartInterval": int(spec["interval_s"])}
    cal = {"Hour": int(spec["hour"]), "Minute": int(spec["minute"])}
    if "weekday" in spec:
        cal["Weekday"] = int(spec["weekday"])
    return {"StartCalendarInterval": cal}


def all_jobs(instance):
    """Template jobs plus the instance's own. An instance job may not shadow a template job:
    the owner adds jobs, never silently replaces one."""
    jobs = dict(JOBS)
    for job_id, spec in (instance.get("instance_jobs") or {}).items():
        if job_id in JOBS:
            raise ValueError("instance job '%s' shadows a template job" % job_id)
        if not isinstance(spec, dict) or not spec.get("program"):
            raise ValueError("instance job '%s' needs a program" % job_id)
        if ("interval_s" in spec) == ("hour" in spec):
            raise ValueError("instance job '%s' needs exactly one of interval_s or hour/minute" % job_id)
        jobs[job_id] = dict(spec)
    return jobs


def render(job_id, spec, template_root, interpreter, state_dir, home):
    """One launchd item. The program is always the runner; the job's own program is the
    runner's business, read from the manifest again at tick time."""
    template_root = Path(template_root); state_dir = Path(state_dir); home = Path(home)
    logs = state_dir / "hub"
    item = {
        "Label": label(job_id),
        "ProgramArguments": [str(interpreter), "-B", str(template_root / "bin" / "sov-hub"), "tick", job_id],
        "RunAtLoad": False,
        "EnvironmentVariables": {
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
            "SOV_STATE_DIR": str(state_dir),
        },
        "StandardOutPath": str(logs / (job_id + ".log")),
        "StandardErrorPath": str(logs / (job_id + ".error.log")),
    }
    item.update(_schedule(spec))
    return item
```

Then make `core.JOBS` a view: in `lib/sovereign_hub/core.py` replace the `JOBS = {...}` literal with

```python
from .manifest import JOBS as _MANIFEST
JOBS = {
    'nightly': {'hour': _MANIFEST['nightly']['hour'], 'minute': _MANIFEST['nightly']['minute'], 'description': 'Propose durable knowledge for owner review'},
    'audit': {'hour': _MANIFEST['weekly-audit']['hour'], 'minute': _MANIFEST['weekly-audit']['minute'], 'weekday': _MANIFEST['weekly-audit']['weekday'], 'description': 'Report structural archive problems without model calls'},
    'snapshot': {'hour': _MANIFEST['snapshot']['hour'], 'minute': _MANIFEST['snapshot']['minute'], 'description': 'Write an encrypted recovery capsule'},
}
```

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_manifest.py test_hub.py`
Expected: manifest tests PASS; `test_hub.py` unchanged (its hub tests need `SOV_PYTHON_RUNTIME` and the crypto helper as before; run with them set or accept the same 11 environment errors as the baseline).

- [ ] **Step 5: Commit**

```bash
git add lib/sovereign_hub/manifest.py lib/sovereign_hub/core.py tests/test_hub_manifest.py
git commit -m "Hub jobs manifest: one table both hub flavors render from"
```

---

### Task 2: The instance file and `sov hub env`

**Files:**
- Create: `lib/sovereign_hub/instance.py`
- Test: `tests/test_hub_instance.py`

**Interfaces:**
- Produces: `path(state_dir) -> Path` (`<state>/hub.json`), `load(state_dir) -> dict` (validated), `validate(inst) -> dict`, `env_exports(inst) -> str` (shell `export` lines), `from_scripts(files: list[Path]) -> dict` (reads `export NAME="value"` lines out of existing scripts into instance fields), `write(state_dir, inst)` (refuses to overwrite).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_instance.py
"""hub.json holds everything that is the owner's. The template never reads a path of the
owner's from anywhere else, and the moved scripts get their settings from `sov hub env`."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import instance  # noqa: E402

GOOD = {
    "version": 1,
    "vault": "/tmp/v",
    "lane": "curator",
    "model": "local-model:tag",
    "audit_model": "local-model:tag",
    "endpoint": "http://localhost:11434/v1/chat/completions",
    "exclude": ["raw/tools/Private"],
    "pending_limit": 50,
    "burndown": {"since_days": 400, "max": 120, "pending_limit": 200, "keep_floor_pct": 2},
    "remotes": ["origin", "exchange"],
    "snapshot": {"folder": "/tmp/snaps", "keep": 30},
    "notify": {"archive": "/tmp/tg-archive.env", "alerts": "/tmp/tg-alerts.env"},
    "kit": {"include": ["~/.agent/.env"], "key_file": "/tmp/keys/hub.key", "targets": ["keep:git/hub-kit/"], "keep": 7},
    "offsite": {"vault": "keep:git/vault.git", "template": "keep:git/template.git"},
    "instance_jobs": {},
}


class Instance(unittest.TestCase):
    def test_validate_accepts_the_full_shape_and_rejects_a_missing_vault(self):
        self.assertEqual(instance.validate(dict(GOOD))["lane"], "curator")
        bad = dict(GOOD); del bad["vault"]
        with self.assertRaises(ValueError):
            instance.validate(bad)

    def test_endpoint_must_be_loopback(self):
        bad = dict(GOOD, endpoint="http://other.local:11434/v1/chat/completions")
        with self.assertRaises(ValueError):
            instance.validate(bad)

    def test_env_exports_are_what_the_scripts_expect(self):
        out = instance.env_exports(instance.validate(dict(GOOD)))
        self.assertIn("export SOVS_VAULT='/tmp/v'", out)
        self.assertIn("export CURATOR_LANE='curator'", out)
        self.assertIn("export CURATOR_MODEL='local-model:tag'", out)
        self.assertIn("export CURATOR_AUDIT_MODEL='local-model:tag'", out)
        self.assertIn("export CURATOR_ENDPOINT='http://localhost:11434/v1/chat/completions'", out)
        self.assertIn("export CURATOR_EXCLUDE='raw/tools/Private'", out)
        self.assertIn("export ARCHIVIST_PENDING_LIMIT='50'", out)
        self.assertIn("export BURNDOWN_KEEP_FLOOR_PCT='2'", out)
        self.assertIn("export SOV_HUB_REMOTES='origin exchange'", out)
        self.assertIn("export SOV_HUB_SNAPSHOT_DIR='/tmp/snaps'", out)
        self.assertIn("export TG_ENV_FILE='/tmp/tg-archive.env'", out)
        # a shell can eval it
        r = subprocess.run(["/bin/bash", "-c", out + '\necho "$CURATOR_LANE:$SOV_HUB_SNAPSHOT_KEEP"'], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "curator:30")

    def test_from_scripts_reads_export_lines_into_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Path(tmp) / "nightly.sh"
            s.write_text('#!/bin/bash\nexport SOVS_VAULT="$HOME/Vault"\nexport CURATOR_LANE=curator\n'
                         'export CURATOR_MODEL="m:1"\nexport CURATOR_ENDPOINT="http://localhost:11434/v1/chat/completions"\n'
                         'export CURATOR_EXCLUDE="a:b c"\n')
            got = instance.from_scripts([s], home="/opt/owner")
            self.assertEqual(got["vault"], "/opt/owner/Vault")
            self.assertEqual(got["exclude"], ["a", "b c"])
            self.assertEqual(got["model"], "m:1")

    def test_write_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance.write(tmp, dict(GOOD))
            self.assertTrue((Path(tmp) / "hub.json").exists())
            with self.assertRaises(ValueError):
                instance.write(tmp, dict(GOOD))
            self.assertEqual(instance.load(tmp)["vault"], "/tmp/v")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_instance.py`
Expected: `ModuleNotFoundError: No module named 'sovereign_hub.instance'`

- [ ] **Step 3: Write the module**

```python
# lib/sovereign_hub/instance.py
"""The instance file: what is the owner's, kept out of the template.

`hub.json` lives in the state directory. `sov hub init` writes it once (from flags, or
from the export lines of the scripts a hand-built hub already runs) and refuses to
overwrite; the owner edits it by hand after. `sov hub env` prints it as shell exports,
which is how the hub scripts read their settings without a rewrite.
"""
import json
import os
import re
import shlex
import urllib.parse
from pathlib import Path

from sovereign_intake.common import atomic, json_read

FILE = "hub.json"
REQUIRED = ("vault", "lane", "model", "endpoint")
DEFAULTS = {
    "version": 1, "audit_model": None, "exclude": [], "pending_limit": 50,
    "burndown": {"since_days": 400, "max": 120, "pending_limit": 200, "keep_floor_pct": 2},
    "remotes": [], "snapshot": {"folder": None, "keep": 30},
    "notify": {"archive": None, "alerts": None},
    "kit": {"include": [], "key_file": None, "targets": [], "keep": 7},
    "offsite": {"vault": None, "template": None},
    "instance_jobs": {},
}
# export NAME in the scripts  ->  field in hub.json
EXPORT_FIELDS = {
    "SOVS_VAULT": "vault", "CURATOR_LANE": "lane", "CURATOR_MODEL": "model",
    "CURATOR_AUDIT_MODEL": "audit_model", "CURATOR_ENDPOINT": "endpoint", "CURATOR_EXCLUDE": "exclude",
}


def path(state_dir):
    return Path(os.path.expanduser(str(state_dir))) / FILE


def validate(inst):
    if not isinstance(inst, dict):
        raise ValueError("hub.json must be an object")
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in inst.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    for k in REQUIRED:
        if not out.get(k):
            raise ValueError("hub.json: '%s' is required" % k)
    if not out.get("audit_model"):
        out["audit_model"] = out["model"]
    url = urllib.parse.urlsplit(out["endpoint"])
    if url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("hub.json: endpoint must be loopback (sovereign inference)")
    if not isinstance(out["exclude"], list):
        raise ValueError("hub.json: exclude must be a list")
    for key in ("pending_limit",):
        if not isinstance(out[key], int) or out[key] < 1:
            raise ValueError("hub.json: %s must be a positive integer" % key)
    from .manifest import all_jobs
    all_jobs(out)                      # raises on a bad instance job
    return out


def load(state_dir):
    p = path(state_dir)
    if not p.is_file():
        raise ValueError("no hub.json at %s; run: sov hub init" % p)
    return validate(json_read(p, {}))


def write(state_dir, inst):
    p = path(state_dir)
    if p.exists():
        raise ValueError("%s exists; edit it by hand, or move it aside first" % p)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic(p, validate(inst))
    return p


def env_exports(inst):
    """Shell export lines. Names are the ones the hub scripts already read."""
    b = inst["burndown"]; s = inst["snapshot"]; n = inst["notify"]
    pairs = [
        ("SOVS_VAULT", inst["vault"]), ("CURATOR_LANE", inst["lane"]),
        ("CURATOR_MODEL", inst["model"]), ("CURATOR_AUDIT_MODEL", inst["audit_model"]),
        ("CURATOR_ENDPOINT", inst["endpoint"]), ("CURATOR_EXCLUDE", ":".join(inst["exclude"])),
        ("ARCHIVIST_PENDING_LIMIT", inst["pending_limit"]),
        ("BURNDOWN_SINCE_DAYS", b["since_days"]), ("BURNDOWN_MAX", b["max"]),
        ("BURNDOWN_PENDING_LIMIT", b["pending_limit"]), ("BURNDOWN_KEEP_FLOOR_PCT", b["keep_floor_pct"]),
        ("SOV_HUB_REMOTES", " ".join(inst["remotes"])),
        ("SOV_HUB_SNAPSHOT_DIR", s.get("folder") or ""), ("SOV_HUB_SNAPSHOT_KEEP", s.get("keep") or 30),
        ("TG_ENV_FILE", n.get("archive") or ""), ("SOV_HUB_ALERTS_ENV", n.get("alerts") or ""),
    ]
    return "\n".join("export %s=%s" % (k, shlex.quote(str(v))) for k, v in pairs) + "\n"


_EXPORT = re.compile(r'^\s*export\s+([A-Z_][A-Z0-9_]*)=(.*?)\s*$')


def from_scripts(files, home=None):
    """Read `export NAME=value` lines out of existing hub scripts. Quotes are stripped and a
    leading $HOME is expanded; nothing else is interpreted. Later files win."""
    home = home or str(Path.home())
    found = {}
    for f in files:
        for line in Path(f).read_text(errors="ignore").splitlines():
            m = _EXPORT.match(line)
            if not m or m.group(1) not in EXPORT_FIELDS:
                continue
            raw = m.group(2).strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                raw = raw[1:-1]
            raw = raw.replace("$HOME", home).replace("${HOME}", home)
            found[EXPORT_FIELDS[m.group(1)]] = raw
    if "exclude" in found:
        found["exclude"] = [x for x in found["exclude"].split(":") if x]
    return found
```

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_instance.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add lib/sovereign_hub/instance.py tests/test_hub_instance.py
git commit -m "Hub instance file: the owner's settings in one place, printed as exports"
```

---

### Task 3: The runner and the `sov-hub` entry

**Files:**
- Create: `lib/sovereign_hub/runner.py`, `bin/sov-hub`
- Modify: `bin/sov` (line 57: route `hub init|env|tick|jobs|kit|law` to `sov-hub`, everything else to `sov-managed-hub`)
- Test: `tests/test_hub_runner.py`

**Interfaces:**
- Produces: `tick(job_id, state_dir, template_root, notify_cmd) -> int` (exit code of the job), receipts at `<state>/hub/<job>.last-run`, `<job>.last-ok`, `<job>.last-output`, `<job>.last-exit`, one line appended to `<state>/hub/runs.log`; alert through `notify_cmd` on non-zero, delivery on `deliver` jobs with non-empty stdout.
- CLI: `sov-hub tick <job>`, `sov-hub env`, `sov-hub init [--from-scripts FILE...] [--vault ... --lane ... --model ... --endpoint ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_runner.py
"""The runner is the wrapper every hub job runs through: receipts, one log line, an
alert on failure, delivery of clean output when the job says so. Semantics match the
hand-written wrapper it replaces, so a cutover changes nothing the owner sees."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import runner, instance, manifest  # noqa: E402

NOTIFY = "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$SOV_STUB_LOG\"\ncat >> \"$SOV_STUB_LOG\"\nexit 0\n"


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp); self.state = self.tmp / "state"; self.template = self.tmp / "template"
        (self.template / "bin" / "hub").mkdir(parents=True); (self.state / "hub").mkdir(parents=True)
        self.log = self.tmp / "notify.log"; self.log.write_text("")
        self.notify = self.tmp / "notify"; self.notify.write_text(NOTIFY); self.notify.chmod(0o755)
        instance.write(self.state, {"vault": str(self.tmp / "v"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "notify": {"alerts": str(self.tmp / "alerts.env")}})
        (self.tmp / "alerts.env").write_text("TG_BOT_TOKEN=x\nTG_CHAT_ID=y\n")
        os.environ["SOV_STUB_LOG"] = str(self.log)

    def job(self, name, body, **spec):
        p = self.template / "bin" / "hub" / name
        p.write_text("#!/bin/bash\n" + body); p.chmod(0o755)
        manifest.JOBS[name] = dict(program="hub/" + name, interval_s=60, deliver=False, description="t", **spec)
        return name

    def tick(self, name):
        return runner.tick(name, self.state, self.template, str(self.notify))

    def receipt(self, name, kind):
        return (self.state / "hub" / (name + "." + kind)).read_text()


class Runner(unittest.TestCase):
    def tearDown(self):
        for k in [k for k in manifest.JOBS if k.startswith("t-")]:
            del manifest.JOBS[k]

    def test_a_clean_quiet_run_leaves_receipts_and_no_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); j = b.job("t-quiet", 'echo "$CURATOR_LANE" > "$SOV_STATE_DIR/saw-env"\n')
            self.assertEqual(b.tick(j), 0)
            self.assertTrue(b.receipt(j, "last-run").strip().isdigit())
            self.assertEqual(b.receipt(j, "last-ok"), b.receipt(j, "last-run"))
            self.assertEqual(b.receipt(j, "last-exit").strip(), "0")
            self.assertEqual((b.state / "saw-env").read_text().strip(), "curator", "the job did not get the instance env")
            self.assertEqual(b.log.read_text(), "", "nothing to say, nothing sent")
            line = (b.state / "hub" / "runs.log").read_text().strip().splitlines()[-1]
            self.assertIn("job=t-quiet exit=0", line)

    def test_a_deliver_job_sends_its_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); j = b.job("t-say", 'echo "hello owner"\n', deliver=True)
            self.assertEqual(b.tick(j), 0)
            self.assertIn("hello owner", b.log.read_text())

    def test_a_failing_run_alerts_with_the_tail_and_keeps_last_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); j = b.job("t-fail", 'for i in $(seq 1 30); do echo "line $i"; done; echo boom >&2; exit 3\n')
            self.assertEqual(b.tick(j), 3)
            self.assertEqual(b.receipt(j, "last-exit").strip(), "3")
            self.assertFalse((b.state / "hub" / "t-fail.last-ok").exists())
            sent = b.log.read_text()
            self.assertIn("ALERT t-fail exit 3", sent)
            self.assertIn("line 30", sent); self.assertIn("boom", sent)
            self.assertNotIn("line 10", sent, "only the tail travels")

    def test_a_missing_program_is_a_loud_failure_not_a_silent_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); manifest.JOBS["t-gone"] = {"program": "hub/does-not-exist", "interval_s": 60, "deliver": False, "description": "t"}
            self.assertNotEqual(b.tick("t-gone"), 0)
            self.assertIn("ALERT t-gone", b.log.read_text())

    def test_the_cli_entry_ticks_and_prints_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); j = b.job("t-cli", 'echo ok\n')
            env = dict(os.environ, SOV_STATE_DIR=str(b.state), SOV_NOTIFY=str(b.notify), SOV_TEMPLATE=str(b.template))
            r = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-hub"), "tick", j], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-hub"), "env"], env=env, capture_output=True, text=True, timeout=60)
            self.assertIn("export CURATOR_LANE='curator'", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_runner.py`
Expected: `ModuleNotFoundError: No module named 'sovereign_hub.runner'`

- [ ] **Step 3: Write the runner and the entry**

```python
# lib/sovereign_hub/runner.py
"""Every hub job runs through here. Semantics are the hand-written wrapper's, exactly:
combined output to <job>.last-output, <job>.last-run always, <job>.last-ok on exit 0,
<job>.last-exit always, one line in runs.log, an alert with the last fifteen lines on
a non-zero exit, and, for a job that delivers, its non-empty output as the message.
Never retries, never repairs.
"""
import os
import subprocess
import time
from pathlib import Path

from . import instance, manifest

TAIL_LINES = 15
CHILD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"


def state_dir():
    return Path(os.path.expanduser(os.environ.get("SOV_STATE_DIR") or "~/.local/state/sovereign"))


def template_root():
    return Path(os.environ.get("SOV_TEMPLATE") or Path(__file__).resolve().parents[2])


def notify_cmd(template):
    return os.environ.get("SOV_NOTIFY") or str(Path(template) / "bin" / "sov-notify-telegram")


def _send(cmd, env_file, text):
    env = dict(os.environ, PATH=CHILD_PATH)
    if env_file:
        env["TG_ENV_FILE"] = str(env_file)
    try:
        subprocess.run([cmd, text], input=text, env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass                        # a failed alert must not turn a job's exit into ours


def job_env(inst, state, template):
    env = dict(os.environ)
    env.update(PATH=CHILD_PATH, SOV_STATE_DIR=str(state), SOV_TEMPLATE=str(template))
    for line in instance.env_exports(inst).splitlines():
        k, v = line[len("export "):].split("=", 1)
        env[k] = v[1:-1].replace("'\\''", "'") if v.startswith("'") else v
    return env


def tick(job_id, state=None, template=None, notify=None):
    state = Path(state or state_dir()); template = Path(template or template_root())
    notify = notify or notify_cmd(template)
    hub = state / "hub"; hub.mkdir(parents=True, exist_ok=True)
    inst = instance.load(state)
    jobs = manifest.all_jobs(inst)
    if job_id not in jobs:
        raise SystemExit("sov hub tick: unknown job '%s'" % job_id)
    spec = jobs[job_id]
    program = spec["program"]
    argv = [program if program.startswith("/") else str(template / "bin" / program)] + list(spec.get("args") or [])
    out = hub / (job_id + ".last-output")
    started = int(time.time())
    try:
        with open(out, "w") as fh:
            rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, env=job_env(inst, state, template),
                                cwd=inst["vault"] if os.path.isdir(inst["vault"]) else None).returncode
    except OSError as e:
        out.write_text("could not start %s: %s\n" % (argv[0], e)); rc = 127
    ended = int(time.time())
    (hub / (job_id + ".last-run")).write_text("%d\n" % ended)
    (hub / (job_id + ".last-exit")).write_text("%d\n" % rc)
    if rc == 0:
        (hub / (job_id + ".last-ok")).write_text("%d\n" % ended)
    text = out.read_text(errors="ignore")
    with open(hub / "runs.log", "a") as log:
        log.write("%s run job=%s exit=%d dur=%ds out_bytes=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), job_id, rc, ended - started, len(text.encode())))
    alerts = (inst.get("notify") or {}).get("alerts"); archive = (inst.get("notify") or {}).get("archive")
    if rc != 0:
        tail = "\n".join(text.strip().splitlines()[-TAIL_LINES:])
        _send(notify, alerts, "ALERT %s exit %d\n%s" % (job_id, rc, tail))
    elif spec.get("deliver") and text.strip():
        _send(notify, archive, text)
    return rc
```

```python
#!/usr/bin/env python3
# bin/sov-hub
"""sov hub, the template-run hub: the instance file, the runner and the job installer.
  sov hub init [--from-scripts FILE ...] [--vault DIR --lane NAME --model TAG --endpoint URL]
  sov hub env                       print hub.json as shell exports
  sov hub tick <job>                run one job through the fail-loud runner (what launchd calls)
  sov hub jobs install [--apply] [--retire-legacy PREFIX]
  sov hub jobs status | uninstall [--apply]
  sov hub kit [--apply]             encrypt the rebuild kit, copy it off-site, mirror-push
  sov hub law                       Part 1 of the vault's law against the template's
The managed-hub commands (install, key, recovery, snapshot, restore, activate, run, doctor, status) stay on sov-managed-hub.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"))
from sovereign_hub import instance, runner  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sov hub"); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--from-scripts", nargs="*", default=[]); p.add_argument("--vault"); p.add_argument("--lane")
    p.add_argument("--model"); p.add_argument("--endpoint"); p.add_argument("--audit-model")
    sub.add_parser("env")
    p = sub.add_parser("tick"); p.add_argument("job")
    args = ap.parse_args(argv)
    state = runner.state_dir()
    if args.cmd == "env":
        sys.stdout.write(instance.env_exports(instance.load(state))); return 0
    if args.cmd == "tick":
        return runner.tick(args.job, state)
    if args.cmd == "init":
        inst = instance.from_scripts([Path(f) for f in args.from_scripts]) if args.from_scripts else {}
        for k in ("vault", "lane", "model", "endpoint", "audit_model"):
            if getattr(args, k):
                inst[k] = getattr(args, k)
        p = instance.write(state, inst)
        print("wrote %s; edit remotes, snapshot, notify, kit, offsite and instance_jobs by hand" % p); return 0
    return 64


if __name__ == "__main__":
    sys.exit(main())
```

In `bin/sov` replace line 57 with:

```bash
  hub)
    case "${1:-}" in
      init|env|tick|jobs|kit|law) exec "$PYTHON" "$BIN/sov-hub" "$@";;
      *) exec "$PYTHON" "$BIN/sov-managed-hub" "$@";;
    esac;;
```

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_runner.py test_sov_front_door.py`
Expected: runner tests PASS; front-door routing tests still PASS (the docs will mention `sov hub` commands that now route).

- [ ] **Step 5: Commit**

```bash
git add tests/test_hub_runner.py lib/sovereign_hub/runner.py bin/sov-hub bin/sov
git commit -m "Hub runner: every job through one fail-loud wrapper with receipts"
```

---

### Task 4: `sov hub jobs install | status | uninstall`

**Files:**
- Create: `lib/sovereign_hub/jobs.py`
- Modify: `bin/sov-hub` (add the `jobs` subparser)
- Test: `tests/test_hub_jobs_install.py`

**Interfaces:**
- Produces: `plan(state, template, home, interpreter, retire_prefix=None) -> dict` with `items: [{label, path, action: create|replace|unchanged, plist}]` and `retire: [paths]`; `apply(plan, launchctl, home) -> dict` (writes changed items, bootstraps them, parks retired ones under `~/Library/LaunchAgents/sovereign-retired/`, rolls back on failure); `status(state, template) -> list[dict]` (job, schedule, last_run, last_ok, last_exit); `uninstall(...)`.
- Consumes: `manifest.all_jobs`, `manifest.render`, `instance.load`; interpreter from `bin/_sov-python.sh` via `resolver(template)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_jobs_install.py
"""sov hub jobs install renders every job, says what would change, and on --apply writes
only that, loading through launchctl and rolling back if a bootstrap fails. Retiring the
hand-written jobs is explicit, parks the plists, and never deletes."""
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import jobs, instance, manifest  # noqa: E402

STUB = "#!/bin/bash\nprintf '%s %s\\n' \"$(basename \"$0\")\" \"$*\" >> \"$SOV_STUB_LOG\"\n[ \"$1\" = print ] && exit 1\nexit \"${SOV_STUB_RC:-0}\"\n"


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp); self.home = self.tmp / "home"; self.state = self.tmp / "state"
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True); self.state.mkdir()
        self.log = self.tmp / "stub.log"; self.log.write_text(""); os.environ["SOV_STUB_LOG"] = str(self.log)
        self.ctl = self.tmp / "launchctl"; self.ctl.write_text(STUB); self.ctl.chmod(0o755)
        instance.write(self.state, {"vault": str(self.tmp / "v"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "instance_jobs": {"health": {"program": "/opt/x/health", "hour": 9, "minute": 0, "deliver": True, "description": "t"}}})

    def plan(self, **kw):
        return jobs.plan(self.state, ROOT, self.home, "/opt/py/bin/python3", **kw)

    def agents(self):
        return sorted(p.name for p in (self.home / "Library" / "LaunchAgents").glob("*.plist"))


class Install(unittest.TestCase):
    def test_dry_run_plans_every_job_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); p = b.plan()
            labels = {i["label"] for i in p["items"]}
            self.assertIn("com.sovereign.hub.nightly", labels); self.assertIn("com.sovereign.hub.health", labels)
            self.assertEqual(len(labels), len(manifest.JOBS) + 1)
            self.assertTrue(all(i["action"] == "create" for i in p["items"]))
            self.assertEqual(b.agents(), [])
            self.assertEqual(b.log.read_text(), "")

    def test_apply_writes_and_loads_then_a_second_plan_is_all_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); r = jobs.apply(b.plan(), str(b.ctl), b.home)
            self.assertEqual(len(r["written"]), len(manifest.JOBS) + 1)
            self.assertIn("com.sovereign.hub.nightly.plist", b.agents())
            self.assertIn("bootstrap", b.log.read_text())
            item = plistlib.loads((b.home / "Library" / "LaunchAgents" / "com.sovereign.hub.nightly.plist").read_bytes())
            self.assertEqual(item["ProgramArguments"][0], "/opt/py/bin/python3")
            p2 = b.plan()
            self.assertTrue(all(i["action"] == "unchanged" for i in p2["items"]))
            b.log.write_text(""); r2 = jobs.apply(p2, str(b.ctl), b.home)
            self.assertEqual(r2["written"], []); self.assertEqual(b.log.read_text(), "", "unchanged jobs are not reloaded")

    def test_a_changed_schedule_is_a_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); jobs.apply(b.plan(), str(b.ctl), b.home)
            inst = instance.load(b.state); inst["instance_jobs"]["health"]["minute"] = 30
            (b.state / "hub.json").write_text(__import__("json").dumps(inst))
            p = b.plan(); byl = {i["label"]: i["action"] for i in p["items"]}
            self.assertEqual(byl["com.sovereign.hub.health"], "replace")
            self.assertEqual(byl["com.sovereign.hub.nightly"], "unchanged")

    def test_retire_legacy_parks_matching_plists_and_only_those(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); la = b.home / "Library" / "LaunchAgents"
            (la / "com.old.cron.nightly.plist").write_bytes(plistlib.dumps({"Label": "com.old.cron.nightly"}))
            (la / "com.other.thing.plist").write_bytes(plistlib.dumps({"Label": "com.other.thing"}))
            p = b.plan(retire_prefix="com.old.cron.")
            self.assertEqual([Path(x).name for x in p["retire"]], ["com.old.cron.nightly.plist"])
            jobs.apply(p, str(b.ctl), b.home)
            self.assertFalse((la / "com.old.cron.nightly.plist").exists())
            self.assertTrue((la / "sovereign-retired" / "com.old.cron.nightly.plist").exists())
            self.assertTrue((la / "com.other.thing.plist").exists())
            self.assertIn("bootout gui/%d/com.old.cron.nightly" % os.getuid(), b.log.read_text())

    def test_a_failed_bootstrap_rolls_back_what_this_apply_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); os.environ["SOV_STUB_RC"] = "1"
            try:
                with self.assertRaises(ValueError):
                    jobs.apply(b.plan(), str(b.ctl), b.home)
            finally:
                del os.environ["SOV_STUB_RC"]
            self.assertEqual(b.agents(), [], "nothing left behind")

    def test_status_reads_the_runner_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); hub = b.state / "hub"; hub.mkdir()
            (hub / "nightly.last-run").write_text("1700000000\n"); (hub / "nightly.last-ok").write_text("1700000000\n"); (hub / "nightly.last-exit").write_text("0\n")
            rows = {r["job"]: r for r in jobs.status(b.state, ROOT)}
            self.assertEqual(rows["nightly"]["last_exit"], 0); self.assertEqual(rows["nightly"]["last_run"], 1700000000)
            self.assertIsNone(rows["burndown"]["last_run"])
            self.assertEqual(rows["health"]["schedule"], "09:00 daily")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_jobs_install.py`
Expected: `ModuleNotFoundError: No module named 'sovereign_hub.jobs'`

- [ ] **Step 3: Write the module**

```python
# lib/sovereign_hub/jobs.py
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
            if p.exists(): p.unlink()
        for p, bak in replaced_backup:
            shutil.move(str(bak), str(p))
        raise
    for _, bak in replaced_backup:
        if bak.exists(): bak.unlink()
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
    when = "%02d:%02d" % (spec["hour"], spec["minute"])
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
                _ctl(launchctl, "bootout", domain + "/" + p.stem); dest = agents_dir(home) / RETIRED; dest.mkdir(exist_ok=True)
                shutil.move(str(p), str(dest / p.name))
    return out
```

Add to `bin/sov-hub`:

```python
    p = sub.add_parser("jobs"); p.add_argument("action", choices=["install", "status", "uninstall"])
    p.add_argument("--apply", action="store_true"); p.add_argument("--retire-legacy", metavar="PREFIX")
    ...
    if args.cmd == "jobs":
        from sovereign_hub import jobs
        template = runner.template_root(); home = Path.home(); ctl = os.environ.get("SOV_LAUNCHCTL", "/bin/launchctl")
        if args.action == "status":
            for r in jobs.status(state, template):
                print("%-16s %-14s last exit %-4s last ok %s" % (r["job"], r["schedule"], r["last_exit"] if r["last_exit"] is not None else "-",
                      time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last_ok"])) if r["last_ok"] else "never"))
            return 0
        if args.action == "uninstall":
            for p in jobs.uninstall(state, template, home, ctl, args.apply): print(("parked " if args.apply else "would park ") + p)
            return 0
        pl = jobs.plan(state, template, home, jobs.resolver(template), args.retire_legacy)
        for it in pl["items"]: print("%-10s %s" % (it["action"], it["label"]))
        for p in pl["retire"]: print("%-10s %s" % ("retire", p))
        print("interpreter %s" % pl["interpreter"])
        if not args.apply:
            print("dry run. add --apply to write and load."); return 0
        r = jobs.apply(pl, ctl, home); print("written %d, parked %d" % (len(r["written"]), len(r["parked"]))); return 0
```

(`import time` at the top of `bin/sov-hub`.)

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_jobs_install.py test_hub_runner.py test_hub_manifest.py`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sovereign_hub/jobs.py bin/sov-hub tests/test_hub_jobs_install.py
git commit -m "sov hub jobs: render, diff, apply only what changed, park legacy jobs"
```

---

### Task 5: Move the hub scripts into `bin/hub/`

**Files:**
- Create: `bin/hub/nightly`, `bin/hub/burndown`, `bin/hub/weekly-audit`, `bin/hub/weekly-landed`, `bin/hub/verdict-poll`, `bin/hub/autocommit`, `bin/hub/secret-scan`, `bin/hub/snapshot`, `bin/hub/exchange-sync`, `bin/hub/tg-send`
- Test: `tests/test_hub_scripts.py` plus the existing generality test.

**Interfaces:**
- Each script begins with `eval "$(sov-hub-env)"` where `sov-hub-env` is: `"$(dirname "$0")/../sov" hub env`; concretely each file's first lines are:

```bash
#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(/bin/bash "$HERE/../sov" hub env)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_scripts.py
"""The hub scripts ship in the template with their settings read from sov hub env, and
none of them names an owner. The runner and jobs table point at these files."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import manifest  # noqa: E402


class Scripts(unittest.TestCase):
    def test_every_manifest_program_exists_and_is_executable(self):
        for job_id, spec in manifest.JOBS.items():
            p = ROOT / "bin" / spec["program"]
            self.assertTrue(p.is_file(), job_id); self.assertTrue(p.stat().st_mode & 0o111, job_id)

    def test_hub_scripts_read_their_settings_from_sov_hub_env(self):
        for p in sorted((ROOT / "bin" / "hub").iterdir()):
            text = p.read_text()
            self.assertIn('hub env', text, p.name)
            self.assertNotRegex(text, r'^\s*export (SOVS_VAULT|CURATOR_MODEL|CURATOR_ENDPOINT|CURATOR_LANE)=', p.name)
            self.assertNotRegex(text, r'Obsidian/|/Users/|node-12|qwen', p.name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_scripts.py`
Expected: FAIL, `bin/hub/nightly` does not exist.

- [ ] **Step 3: Bring the scripts over**

From the working laptop, copy the hub's current scripts into the worktree (read-only on the hub):

```bash
W=<worktree>/bin/hub; mkdir -p "$W"
scp <hub>:brain-bin/cron-wrappers/archivist-nightly-cron.sh "$W/nightly"
scp <hub>:brain-bin/archivist-burndown.sh "$W/burndown"
scp <hub>:brain-bin/archivist-weekly.sh "$W/weekly-audit"
scp <hub>:brain-bin/cron-wrappers/archivist-weekly-landed.py "$W/weekly-landed"
scp <hub>:brain-bin/tg-verdict-poll.py "$W/verdict-poll"
scp <hub>:brain-bin/cron-wrappers/vault-autocommit.sh "$W/autocommit"
scp <hub>:brain-bin/cron-wrappers/vault-secret-scan.sh "$W/secret-scan"
scp <hub>:bin/vault-snapshot.sh "$W/snapshot"
scp <hub>:brain-bin/brain-exchange-sync.sh "$W/exchange-sync"
scp <hub>:brain-bin/cron-wrappers/tg-send.sh "$W/tg-send"
chmod +x "$W"/*
```

Then, in each bash script: delete every `export SOVS_VAULT=`, `export CURATOR_*=`, `V="$HOME/Obsidian/..."`, `VAULT="${VAULT:-$HOME/Obsidian/...}"`, `LANE=`, `BACKUP_ROOT=` assignment that names the owner's paths and replace with the header block above plus reads of the exported names: `V="$SOVS_VAULT"`, `VAULT="$SOVS_VAULT"`, `LANE="$SOVS_VAULT/raw/workspaces/$CURATOR_LANE"`, `BACKUP_ROOT="$SOV_HUB_SNAPSHOT_DIR"`, `KEEP="$SOV_HUB_SNAPSHOT_KEEP"`. In `exchange-sync` and `autocommit` replace the literal `for r in origin node-12` with `for r in $SOV_HUB_REMOTES`, and the template push line with `git -C "$SOV_TEMPLATE" push -q "${SOV_HUB_REMOTES##* }" main`. `nightly` calls `"$HERE/burndown"`'s sibling `curator-run` as `"$HERE/../curator-run"`; `weekly-audit` calls `"$HERE/../sov-audit"`; the nightly's `TG_SEND` becomes `"$HERE/tg-send"`. For the two Python scripts, replace any `os.path.expanduser("~/Obsidian/...")` with `os.environ["SOVS_VAULT"]` and any lane path with `os.path.join(os.environ["SOVS_VAULT"], "raw/workspaces", os.environ["CURATOR_LANE"])`; both begin with the exports already in the environment because the runner sets them, so they need no eval. Grep each file after editing:

```bash
grep -nE 'Obsidian/|/Users/|node-12|qwen|sovsarchive' "$W"/* && echo "STILL SPECIFIC" || echo clean
```

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_scripts.py test_template_is_general.py`
Expected: PASS. Then syntax-check every bash script with `bash -n` and every Python one with `python3 -m py_compile`.

- [ ] **Step 5: Commit**

```bash
git add bin/hub tests/test_hub_scripts.py
git commit -m "Hub scripts ship in the template and read the instance file"
```

---

### Task 6: The kit: `sov hub kit`

**Files:**
- Create: `lib/sovereign_hub/kit.py`, `bin/hub/kit` (a two-line bash: `eval env`, then `exec "$HERE/../sov" hub kit --apply`)
- Modify: `bin/sov-hub` (add `kit`)
- Test: `tests/test_hub_kit.py`

**Interfaces:**
- Produces: `inventory(inst, state, home) -> list[(name, bytes)]` (hub.json, `~/.brain-*`, notify env files, every `kit.include` path expanded; refuses the key file and anything under the vault), `build(inst, state, home, template, apply) -> dict` (tar, seal with `hub-crypto`, write `<snapshot.folder>/hub-kit/<UTC stamp>.kit`, copy to each target with `scp` or `cp` for a local path, keep the newest `kit.keep`, mirror-push vault and template to `offsite` targets, write `<state>/hub/kit.json` receipt), `restore(capsule, destination, key) -> list[str]` (unseal into a directory, verify hashes).
- Consumes: `core.crypto_tool()`, `recovery.check_key`, tar and hash code copied from `recovery.snapshot` (kept small and local; the capsule format is the same: a `manifest.json` of hashes inside a gzip tar sealed by `hub-crypto seal`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_kit.py
"""The kit is what a rebuild needs and nothing more: the instance file, the pointers, the
notify env files, and what the owner lists. Never the key, never the vault. Sealed with
the same tool as the recovery capsule, and it restores byte for byte."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import kit, instance, recovery  # noqa: E402

CRYPTO = ROOT / "apps/console/build/hub-crypto"


@unittest.skipUnless(CRYPTO.is_file() or (ROOT / "bin/hub-crypto").is_file(), "needs the built hub-crypto helper")
class Kit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/private/tmp"); t = Path(self.tmp.name)
        self.home = t / "home"; self.state = self.home / ".local/state/sovereign"; self.state.mkdir(parents=True)
        (self.home / ".brain-root").write_text(str(t / "vault") + "\n"); (t / "vault" / "knowledge").mkdir(parents=True)
        (self.home / "secret.env").write_text("TOKEN=abc\n"); (self.home / "tg.env").write_text("TG_BOT_TOKEN=x\n")
        self.keys = t / "keys"; self.keys.mkdir(); self.key = self.keys / "hub.key"; recovery.recovery_key(self.key, True)
        self.target = t / "offsite"; self.target.mkdir()
        instance.write(self.state, {"vault": str(t / "vault"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "snapshot": {"folder": str(t / "snaps"), "keep": 30},
                                    "notify": {"archive": str(self.home / "tg.env")},
                                    "kit": {"include": [str(self.home / "secret.env")], "key_file": str(self.key), "targets": [str(self.target)], "keep": 2}})
        self.inst = instance.load(self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def test_inventory_is_exactly_the_declared_set_and_never_the_key_or_the_vault(self):
        names = [n for n, _ in kit.inventory(self.inst, self.state, self.home)]
        self.assertIn("state/hub.json", names); self.assertIn("pointers/.brain-root", names)
        self.assertIn("notify/tg.env", names); self.assertIn("include/secret.env", names)
        self.assertFalse(any("hub.key" in n for n in names))
        bad = dict(self.inst); bad["kit"] = dict(self.inst["kit"], include=[str(self.key)])
        with self.assertRaises(ValueError):
            kit.inventory(bad, self.state, self.home)
        bad["kit"]["include"] = [self.inst["vault"]]
        with self.assertRaises(ValueError):
            kit.inventory(bad, self.state, self.home)

    def test_build_seals_copies_keeps_and_restores_byte_for_byte(self):
        r0 = kit.build(self.inst, self.state, self.home, ROOT, apply=False)
        self.assertFalse(list((Path(self.inst["snapshot"]["folder"]) / "hub-kit").glob("*")) if (Path(self.inst["snapshot"]["folder"]) / "hub-kit").exists() else True)
        for _ in range(3):
            r = kit.build(self.inst, self.state, self.home, ROOT, apply=True)
        kits = sorted((Path(self.inst["snapshot"]["folder"]) / "hub-kit").glob("*.kit"))
        self.assertEqual(len(kits), 2, "keep=2 prunes the oldest")
        self.assertEqual(sorted(p.name for p in self.target.glob("*.kit")), [p.name for p in kits])
        receipt = __import__("json").loads((self.state / "hub" / "kit.json").read_text())
        self.assertEqual(receipt["targets"][str(self.target)]["state"], "copied")
        out = Path(self.tmp.name) / "restored"
        names = kit.restore(kits[-1], out, self.key)
        self.assertIn("include/secret.env", names)
        self.assertEqual((out / "include/secret.env").read_text(), "TOKEN=abc\n")
        self.assertEqual((out / "state/hub.json").read_bytes(), (self.state / "hub.json").read_bytes())

    def test_a_wrong_key_restores_nothing(self):
        kit.build(self.inst, self.state, self.home, ROOT, apply=True)
        capsule = sorted((Path(self.inst["snapshot"]["folder"]) / "hub-kit").glob("*.kit"))[-1]
        other = self.keys / "other.key"; recovery.recovery_key(other, True)
        out = Path(self.tmp.name) / "nope"
        with self.assertRaises(Exception):
            kit.restore(capsule, out, other)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_kit.py`
Expected: `ModuleNotFoundError: No module named 'sovereign_hub.kit'` (or skipped if the helper is absent: copy it from `<a built app checkout>/apps/console/build/hub-crypto` into the worktree's gitignored `apps/console/build/` first).

- [ ] **Step 3: Write the module**

```python
# lib/sovereign_hub/kit.py
"""The rebuild kit: what only exists on the hub machine, sealed and copied off-site nightly.

Contents: hub.json, the machine pointers (~/.brain-*), the notify env files, and every
path the owner lists under kit.include. Never the recovery key, never anything under the
vault (the vault has its own copies). Sealed with hub-crypto like the recovery capsule,
so one key opens both. Targets are copied with scp (host:path) or cp (a local path); the
same run mirror-pushes the vault and the template to the offsite remotes and writes a
receipt with each target's state.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from sovereign_intake.common import atomic
from .core import crypto_tool
from .recovery import check_key

MAX_TOTAL = 64 * 1024 * 1024


def _under(p, root):
    try:
        Path(p).resolve().relative_to(Path(root).resolve()); return True
    except ValueError:
        return False


def _files(path):
    p = Path(os.path.expanduser(str(path)))
    if p.is_dir():
        return [q for q in sorted(p.rglob("*")) if q.is_file() and not q.is_symlink()]
    return [p] if p.is_file() else []


def inventory(inst, state, home):
    state = Path(state); home = Path(home); k = inst.get("kit") or {}
    key = k.get("key_file")
    entries = []
    def add(name, p):
        raw = Path(p).read_bytes()
        entries.append((name, raw))
    add("state/hub.json", state / "hub.json")
    for p in sorted(home.glob(".brain-*")):
        if p.is_file(): add("pointers/" + p.name, p)
    for label, envp in (inst.get("notify") or {}).items():
        if envp and Path(os.path.expanduser(envp)).is_file():
            add("notify/" + Path(envp).name, os.path.expanduser(envp))
    for item in k.get("include") or []:
        for f in _files(item):
            if key and Path(f).resolve() == Path(os.path.expanduser(key)).resolve():
                raise ValueError("the recovery key never goes in the kit: " + str(f))
            if _under(f, inst["vault"]):
                raise ValueError("the vault has its own copies; not in the kit: " + str(f))
            add("include/" + str(f.relative_to(Path(item).expanduser().parent) if Path(item).expanduser().is_dir() else f.name), f)
    if sum(len(r) for _, r in entries) > MAX_TOTAL:
        raise ValueError("kit exceeds %d MiB" % (MAX_TOTAL // (1024 * 1024)))
    return entries


def _seal(entries, key, out):
    with tempfile.TemporaryDirectory(prefix="sov-kit-", dir=str(Path(out).parent)) as tmp:
        plain = Path(tmp) / "kit.tar.gz"; hashes = {}
        with tarfile.open(plain, "w:gz") as tar:
            for name, raw in entries:
                h = tarfile.TarInfo(name); h.size = len(raw); h.mode = 0o600; h.mtime = int(time.time())
                tar.addfile(h, io.BytesIO(raw)); hashes[name] = hashlib.sha256(raw).hexdigest()
            payload = json.dumps({"version": 1, "hashes": hashes, "created": time.time()}, sort_keys=True).encode()
            h = tarfile.TarInfo("manifest.json"); h.size = len(payload); h.mode = 0o600; tar.addfile(h, io.BytesIO(payload))
        sealed = Path(tmp) / "sealed"
        subprocess.run([str(crypto_tool()), "seal", str(key), str(plain), str(sealed)], check=True, capture_output=True, timeout=120)
        shutil.move(str(sealed), str(out))
    return hashes


def _copy(target, capsule):
    if ":" in target:
        r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", str(capsule), target.rstrip("/") + "/" + capsule.name], capture_output=True, text=True, timeout=300)
        return {"state": "copied" if r.returncode == 0 else "failed", "detail": (r.stderr or "").strip()[:200]}
    dest = Path(os.path.expanduser(target)); dest.mkdir(parents=True, exist_ok=True); shutil.copy2(capsule, dest / capsule.name)
    return {"state": "copied", "detail": ""}


def _mirror(repo, remote):
    r = subprocess.run(["git", "-C", str(repo), "push", "--mirror", "-q", remote], capture_output=True, text=True, timeout=600)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"state": "pushed" if r.returncode == 0 else "failed", "head": head, "detail": (r.stderr or "").strip()[:200]}


def build(inst, state, home, template, apply=False):
    state = Path(state); k = inst.get("kit") or {}; snap = (inst.get("snapshot") or {}).get("folder")
    if not snap or not k.get("key_file"):
        raise ValueError("hub.json needs snapshot.folder and kit.key_file before a kit can be built")
    key = check_key(Path(os.path.expanduser(k["key_file"])))
    folder = Path(os.path.expanduser(snap)) / "hub-kit"
    entries = inventory(inst, state, home)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()); out = folder / (stamp + ".kit")
    result = {"applied": apply, "output": str(out), "files": [n for n, _ in entries], "targets": {}, "offsite": {}}
    if not apply:
        return result
    folder.mkdir(parents=True, exist_ok=True)
    hashes = _seal(entries, key, out); result["sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    keep = int(k.get("keep") or 7)
    for old in sorted(folder.glob("*.kit"))[:-keep]:
        old.unlink()
    for target in k.get("targets") or []:
        result["targets"][target] = _copy(target, out)
    off = inst.get("offsite") or {}
    if off.get("vault"): result["offsite"]["vault"] = _mirror(inst["vault"], off["vault"])
    if off.get("template"): result["offsite"]["template"] = _mirror(template, off["template"])
    result["finished"] = time.time()
    (state / "hub").mkdir(exist_ok=True); atomic(state / "hub" / "kit.json", result)
    failed = [t for t, r in result["targets"].items() if r["state"] != "copied"] + [n for n, r in result["offsite"].items() if r["state"] != "pushed"]
    if failed:
        raise ValueError("kit built locally but these targets failed: " + ", ".join(failed))
    return result


def restore(capsule, destination, key):
    destination = Path(destination); key = check_key(Path(os.path.expanduser(str(key))))
    if destination.exists():
        raise ValueError("restore destination exists: " + str(destination))
    with tempfile.TemporaryDirectory(prefix="sov-kit-restore-", dir=str(destination.parent)) as tmp:
        plain = Path(tmp) / "kit.tar.gz"
        subprocess.run([str(crypto_tool()), "open", str(key), str(capsule), str(plain)], check=True, capture_output=True, timeout=120)
        names = []
        with tarfile.open(plain, "r:gz") as tar:
            members = tar.getmembers(); manifest = json.loads(tar.extractfile("manifest.json").read())
            staged = Path(tmp) / "out"; staged.mkdir()
            for m in members:
                if m.name == "manifest.json": continue
                if not m.isreg() or m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise ValueError("unsafe entry in kit: " + m.name)
                raw = tar.extractfile(m).read()
                if hashlib.sha256(raw).hexdigest() != manifest["hashes"].get(m.name):
                    raise ValueError("hash mismatch in kit: " + m.name)
                p = staged / m.name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw); p.chmod(0o600); names.append(m.name)
        shutil.move(str(staged), str(destination))
    return names
```

Check the verb `hub-crypto` uses to decrypt (`open` above): read `lib/sovereign_hub/recovery.py` `restore()` and use the same word it passes. Add to `bin/sov-hub`:

```python
    p = sub.add_parser("kit"); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("kit-restore"); p.add_argument("--capsule", required=True); p.add_argument("--destination", required=True); p.add_argument("--key-file", required=True)
    ...
    if args.cmd == "kit":
        from sovereign_hub import kit
        r = kit.build(instance.load(state), state, Path.home(), runner.template_root(), args.apply)
        print(json.dumps(r, indent=1)); return 0
    if args.cmd == "kit-restore":
        from sovereign_hub import kit
        for n in kit.restore(Path(args.capsule), Path(args.destination), Path(args.key_file)): print(n)
        return 0
```

And `bin/hub/kit`:

```bash
#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$HERE/../sov" hub kit --apply
```

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_kit.py`
Expected: 3 passed (with the helper present).

- [ ] **Step 5: Commit**

```bash
git add lib/sovereign_hub/kit.py bin/hub/kit bin/sov-hub tests/test_hub_kit.py
git commit -m "Hub kit: seal what only the hub machine has, copy it off-site, mirror-push"
```

---

### Task 7: Status and the app read hub receipts

**Files:**
- Modify: `bin/sov-status` (the local jobs loop near line 1470: for a label with the `com.sovereign.hub.` prefix, add `last_run`, `last_ok` and `last_exit` from `<state>/hub/<job>.*` when launchd has no exit yet, and point `stderr` at `<state>/hub/<job>.error.log`)
- Test: extend `tests/test_brain_status_jobs.py` with one test.

- [ ] **Step 1: Write the failing test** (append to `tests/test_brain_status_jobs.py`)

```python
class HubReceipts(unittest.TestCase):
    """A hub job row reads the runner's receipts, so a job that has never exited in
    launchd's eyes still shows its last run and last exit."""

    def test_a_hub_job_row_carries_the_runner_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); b.plist("com.sovereign.hub.nightly"); b.labels = "com.sovereign.hub.nightly"
            hub = b.state / "hub"; hub.mkdir()
            (hub / "nightly.last-run").write_text("1700000000\n"); (hub / "nightly.last-ok").write_text("1699990000\n"); (hub / "nightly.last-exit").write_text("2\n")
            d = b.status()
            row = next(j for j in d["jobs"] if j["label"] == "com.sovereign.hub.nightly")
            self.assertEqual(row["last_exit"], 2); self.assertEqual(row["last_run"], 1700000000); self.assertEqual(row["last_ok"], 1699990000)
            self.assertTrue(row["stderr"].endswith("hub/nightly.error.log"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_brain_status_jobs.py::HubReceipts`
Expected: FAIL on `last_run` (KeyError or None).

- [ ] **Step 3: Implement** in `bin/sov-status`, right after `jobs.append({"label": label, **r, **info})` in the local jobs loop:

```python
        if label.startswith("com.sovereign.hub."):
            hub_state = os.path.join(_state_dir(), "hub"); jid = label[len("com.sovereign.hub."):]
            def _i(name):
                try: return int(open(os.path.join(hub_state, "%s.%s" % (jid, name))).read().strip())
                except (OSError, ValueError): return None
            row = jobs[-1]
            row["last_run"], row["last_ok"] = _i("last-run"), _i("last-ok")
            if _i("last-exit") is not None:
                row["last_exit"] = _i("last-exit")
            err = os.path.join(hub_state, jid + ".error.log")
            row["stderr"] = err; n, a = _log_lines(err); row["stderr_lines"], row["stderr_age_h"] = n, a
```

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_brain_status_jobs.py test_brain_status_transparency.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bin/sov-status tests/test_brain_status_jobs.py
git commit -m "sov-status: hub job rows read the runner's receipts"
```

---

### Task 8: `sov hub law`, the Part 1 drift check

**Files:**
- Create: `lib/sovereign_hub/law.py`
- Modify: `bin/sov-hub` (add `law`), `bin/sov` (`sov check` also runs `sov-hub law` when a hub.json exists, warning only), `CLAUDE.md` (the template's Part 1 updated to the vault's current Part 1 text, verbatim)
- Test: `tests/test_hub_law.py`

**Interfaces:**
- Produces: `part1(text) -> str` (the text between `# Part 1` and `# Part 2`, whitespace-normalised), `drift(vault_law: Path, template_law: Path) -> list[str]` (differing lines, empty when equal).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_law.py
"""Part 1 of the law is the copyable standard. The template's copy and the vault's must
say the same thing, and sov check says so when they drift."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import law  # noqa: E402


class Law(unittest.TestCase):
    def test_identical_part_one_has_no_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.md"; b = Path(tmp) / "b.md"
            a.write_text("# Part 1 — the standard\n\nrule one\n\n# Part 2 — mine\n\nsecret\n")
            b.write_text("intro\n# Part 1 — the standard\nrule one\n# Part 2 — other\ndifferent\n")
            self.assertEqual(law.drift(a, b), [])

    def test_a_changed_rule_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.md"; b = Path(tmp) / "b.md"
            a.write_text("# Part 1 — the standard\nrule one\n# Part 2\n")
            b.write_text("# Part 1 — the standard\nrule two\n# Part 2\n")
            d = law.drift(a, b)
            self.assertTrue(any("rule one" in x for x in d) and any("rule two" in x for x in d))

    def test_the_template_law_has_a_part_one(self):
        self.assertTrue(law.part1((ROOT / "CLAUDE.md").read_text()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_law.py`
Expected: `ModuleNotFoundError: No module named 'sovereign_hub.law'`

- [ ] **Step 3: Write the module**

```python
# lib/sovereign_hub/law.py
"""Part 1 of the law is the standard any instance copies. When the vault's and the template's
Part 1 differ, one of them is behind; say which lines."""
import difflib
import re
from pathlib import Path

_START = re.compile(r"^# Part 1\b", re.M)
_END = re.compile(r"^# Part 2\b", re.M)


def part1(text):
    s = _START.search(text)
    if not s:
        return ""
    e = _END.search(text, s.end())
    body = text[s.start():e.start() if e else len(text)]
    return "\n".join(line.rstrip() for line in body.splitlines() if line.strip())


def drift(vault_law, template_law):
    a = part1(Path(vault_law).read_text(errors="ignore")).splitlines()
    b = part1(Path(template_law).read_text(errors="ignore")).splitlines()
    return [l for l in difflib.unified_diff(a, b, "vault", "template", lineterm="", n=0) if l[:1] in "+-" and not l.startswith(("+++", "---"))]
```

In `bin/sov-hub` add `sub.add_parser("law")` and:

```python
    if args.cmd == "law":
        from sovereign_hub import law
        vault = Path(instance.load(state)["vault"]) / "CLAUDE.md"
        d = law.drift(vault, runner.template_root() / "CLAUDE.md")
        if not d: print("Part 1 matches between the vault and the template"); return 0
        print("Part 1 drift, vault (-) vs template (+):"); [print(x) for x in d]; return 1
```

In `bin/sov`, the `check)` branch becomes:

```bash
  check)    /bin/bash "$BIN/sov-check" "$@"; rc=$?
            [ -f "${SOV_STATE_DIR:-$HOME/.local/state/sovereign}/hub.json" ] && "$PYTHON" "$BIN/sov-hub" law || true
            exit $rc;;
```

Then bring the template's `CLAUDE.md` Part 1 up to the vault's: copy the vault's Part 1 section over the template's (`python3 - <<'PY'` that splices `law.part1`-bounded text), keeping the template's Part 2 placeholder. Run `sov hub law` against a temp hub.json pointing at the vault to confirm "matches". The generality test must still pass (Part 1 names no owner).

- [ ] **Step 4: Run the tests**

Run: `cd tests && /usr/bin/python3 -m pytest -q -p no:cacheprovider test_hub_law.py test_template_is_general.py test_sov_front_door.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_hub_law.py lib/sovereign_hub/law.py bin/sov-hub bin/sov CLAUDE.md
git commit -m "sov hub law: Part 1 drift between the vault and the template"
```

---

### Task 9: Runbook, full suites, the hub dry run

**Files:**
- Create: `docs/hub-rebuild.md`
- Modify: `docs/hub-setup.md` (one paragraph pointing at the template-run hub and the kit), `connectors/README.md` if it lists `sov` commands (the front-door test reads docs for `sov <word>` and requires each to route).

- [ ] **Step 1: Write the runbook**

```markdown
# Rebuild the hub

One screen. Needs: a Mac with the Command Line Tools, the recovery key (kept outside every archive; the owner has two copies), and reach to one vault remote and one kit target.

1. `git clone <template remote> ~/sovs-brain-template && ln -s ~/sovs-brain-template/bin/sov ~/brain-bin/sov`
2. `git clone <vault remote> "<vault path>"` (any remote: the exchange, the canonical, the off-site mirror)
3. Fetch the newest `*.kit` from a kit target, then
   `sov hub kit-restore --capsule <file>.kit --destination ~/hub-restore --key-file <key>`
4. `mkdir -p ~/.local/state/sovereign && cp ~/hub-restore/state/hub.json ~/.local/state/sovereign/ && cp ~/hub-restore/pointers/.brain-* ~/`
   Put each `~/hub-restore/notify/*` and `~/hub-restore/include/*` file back at the path hub.json names.
5. `sov hub jobs install` (read the plan), then `sov hub jobs install --apply`
6. `sov hub jobs status` shows every job; `sov status --json` shows the hub; the first nightly proves the model.

Rollback of a reinstall: `sov hub jobs uninstall --apply` parks the plists.
```

- [ ] **Step 2: Full suites**

Run from the worktree, both interpreters, as in the release checks:

```bash
cd tests && SOV_PYTHON_RUNTIME=<the installed app>/Contents/Resources/runtime /usr/bin/python3 -m pytest -q -p no:cacheprovider
PYTHONPATH=lib SOV_PYTHON_RUNTIME=... <venv312>/bin/python -m unittest discover -s tests
```

Expected: all pass (the previous baseline was 538; this plan adds about 25).

- [ ] **Step 3: The hub dry run, read-only**

On the hub machine, from a clone of the branch in a scratch directory (not the live checkout):

```bash
git clone -b feat/hub-from-template <exchange>:git/<template>.git /tmp/hub-branch
SOV_STATE_DIR=/tmp/hub-state /tmp/hub-branch/bin/sov hub init --from-scripts ~/brain-bin/archivist-nightly.sh ~/brain-bin/archivist-weekly.sh
# edit /tmp/hub-state/hub.json by hand: remotes, snapshot, notify, kit, offsite, instance_jobs (the six agent-stack jobs from the plists)
SOV_STATE_DIR=/tmp/hub-state /tmp/hub-branch/bin/sov hub jobs install --retire-legacy com.sov.cron.
```

Paste the plan output into the Workplan under move 5 for the owner; nothing is applied.

- [ ] **Step 4: Commit and packet**

```bash
git add docs/hub-rebuild.md docs/hub-setup.md
git commit -m "Hub rebuild runbook"
```

Then the packet: a dated block in the Workplan's move 5 section (what was built, the suite counts, the dry-run plan, the cutover steps and rollback), and the owner's yes for the cutover moment.
