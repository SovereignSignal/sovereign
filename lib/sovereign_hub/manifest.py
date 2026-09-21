"""The hub's jobs, defined once.

Every hub, whether installed from the app or run from a template checkout, renders its
scheduler items from this table plus the owner's instance file. A job's program is a
path relative to the template's bin/ (or absolute for an instance job), and every job
runs through the hub runner (`sov-hub tick <id>`), which is what gives it receipts,
one log line, an alert on failure and delivery of clean output when `deliver` is set.

Schedules: a calendar job has `hour` and `minute` (and optionally `weekday`, 0=Sunday
as launchd counts), or `hours` (a list) and `minute` for several times a day; an
interval job has `interval_s`. Exactly one of the three.
"""
from pathlib import Path

LABEL_PREFIX = "com.sovereign.hub."

JOBS = {
    "nightly": {"program": "hub/nightly", "hour": 6, "minute": 0, "deliver": True,
                "description": "Judge new raw material and propose durable knowledge; deliver the digest"},
    # Continuous curation pilot, owner decision 2026-09-21: "we can't gate progress to
    # that window every night". Cadence and cap only — no judge, prompt, threshold or
    # promotion-logic change, so no gear question under that morning's ruling. The
    # per-tick auto-promote cap lives in hub/curate, because render() writes a fixed
    # environment and a cap declared here would be read by nothing. Review after 3 days;
    # rollback is removing this entry and re-running `sov hub jobs install --apply`.
    "curate": {"program": "hub/curate", "interval_s": 7200, "deliver": False,
               "description": "Curate new raw as it arrives; the nightly stays the daily digest"},
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
    # exchange-sync skips `write: intake` lanes and defers to this job. Without it a
    # contribute-only producer delivers on schedule and nothing ever imports the result.
    "intake": {"program": "hub/intake", "interval_s": 1800, "deliver": False,
               "description": "Import what every contribute-only lane has delivered to the exchange"},
}


def label(job_id):
    return LABEL_PREFIX + job_id


def _schedule(spec):
    if "interval_s" in spec:
        return {"StartInterval": int(spec["interval_s"])}
    if "hours" in spec:
        return {"StartCalendarInterval": [{"Hour": int(h), "Minute": int(spec["minute"])} for h in spec["hours"]]}
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
        if sum(k in spec for k in ("interval_s", "hour", "hours")) != 1:
            raise ValueError("instance job '%s' needs exactly one of interval_s, hour/minute or hours/minute" % job_id)
        if "hours" in spec and (not isinstance(spec["hours"], list) or not spec["hours"] or "minute" not in spec):
            raise ValueError("instance job '%s': hours must be a non-empty list, with a minute" % job_id)
        jobs[job_id] = dict(spec)
    return jobs


# Every key render() and _schedule() understand. A spec key outside this set is a
# mistake that would otherwise cost nothing to make and nothing to notice: on
# 2026-09-21 a proposed job carried an "env" key to cap its auto-promotions, and
# render() writes a FIXED EnvironmentVariables dict, so the plist would have loaded
# and the job would have run at the default cap — 144 a day against an intended 4.
# The manifest would have shown the cap, the plist would have loaded, the job would
# have run. Only the promotions would have said otherwise, days later.
# It must cover what runner.py reads as well as what render() does, and instance_jobs
# as well as the shipped ones: the first version of this set omitted "args", which
# runner.py passes to the program and all five of one hub's instance jobs carry. The
# validator would then have raised on the first instance job and broken
# `sov hub jobs install --apply` on that machine — a guard against silent config
# failing loudly instead, which is better, but still a guard that breaks the thing it
# guards. Enumerate from both readers, not from the jobs this file happens to ship.
KNOWN_SPEC_KEYS = frozenset({
    "program", "args", "description", "deliver",  # identity, arguments, delivery
    "hour", "minute", "hours", "weekday",         # calendar schedules
    "interval_s",                                 # interval schedules
})


def validate_spec(job_id, spec):
    """Refuse a spec key nothing reads. Silence is the failure being prevented."""
    unknown = sorted(set(spec) - KNOWN_SPEC_KEYS)
    if unknown:
        raise ValueError(
            "hub job %r has unrecognised spec key(s): %s. Nothing reads them, so the job "
            "would render and run without whatever they were meant to do. Known keys: %s."
            % (job_id, ", ".join(unknown), ", ".join(sorted(KNOWN_SPEC_KEYS))))
    return spec


def render(job_id, spec, template_root, interpreter, state_dir, home):
    """One launchd item. The program is always the runner; the job's own program is the
    runner's business, read from the manifest again at tick time."""
    validate_spec(job_id, spec)
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
