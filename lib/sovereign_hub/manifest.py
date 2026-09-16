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
