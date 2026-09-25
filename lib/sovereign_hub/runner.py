"""Every hub job runs through here. Semantics are the hand-written wrapper's, exactly:
combined output to <job>.last-output, <job>.last-run always, <job>.last-ok on exit 0,
<job>.last-exit always, one line in runs.log, an alert with the last fifteen lines on
a non-zero exit, and, for a job that delivers, its non-empty output as the message.
Never retries, never repairs.

One exit code is read rather than counted: PAUSED_EXIT, the code a job returns when it
deliberately did nothing and only the owner can change that. The receipt keeps it (no
last-ok: a pause is not a success), and the owner hears once, on the tick the condition
appears, instead of every tick for as long as it holds. bin/hub/curate is the first
user: its queue circuit breaker stops curation for the whole archive while the review
queue is full, and exiting 0 made that indistinguishable from a healthy tick.
"""
import os
import subprocess
import time
from pathlib import Path

from . import instance, manifest, progress

TAIL_LINES = 15
CHILD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
# EX_TEMPFAIL: nothing is broken, the work is not being done. Not 1 (the job failed) and
# not 3 (curator-run gave up waiting for the model lock); both of those want a person now.
PAUSED_EXIT = 75


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
        env[k] = v[1:-1].replace("'\\''", "'")
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
    observation = progress.Progress.start(state, job_id)
    env = job_env(inst, state, template)
    # Clear inherited identifiers even for jobs that do not report progress.
    env.pop('SOV_PROGRESS_JOB', None); env.pop('SOV_PROGRESS_RUN', None)
    if observation.path is not None:
        env.update(SOV_PROGRESS_JOB=job_id, SOV_PROGRESS_RUN=observation.run_id)
    try:
        with open(out, "w") as fh:
            rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                                cwd=inst["vault"] if os.path.isdir(inst["vault"]) else None).returncode
    except OSError as e:
        out.write_text("could not start %s: %s\n" % (argv[0], e)); rc = 127
    ended = int(time.time())
    exit_file = hub / (job_id + ".last-exit")
    try:
        was = int(exit_file.read_text().strip())      # the previous run's code, for the edge below
    except (OSError, ValueError):
        was = None
    (hub / (job_id + ".last-run")).write_text("%d\n" % ended)
    exit_file.write_text("%d\n" % rc)
    observation.update('completed')
    if rc == 0:
        (hub / (job_id + ".last-ok")).write_text("%d\n" % ended)
    text = out.read_text(errors="ignore")
    with open(hub / "runs.log", "a") as log:
        log.write("%s run job=%s exit=%d dur=%ds out_bytes=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), job_id, rc, ended - started, len(text.encode())))
    channels = inst.get("notify") or {}
    tail = "\n".join(text.strip().splitlines()[-TAIL_LINES:])
    if rc == PAUSED_EXIT:
        # Stood down on purpose. A job that delivers has already said so in its own
        # message; a quiet one says it once, on the tick the condition appears.
        if spec.get("deliver") and text.strip():
            _send(notify, channels.get("archive"), text)
        elif rc != was:
            _send(notify, channels.get("alerts"),
                  "PAUSED %s exit %d, no work done, and no repeat until this changes\n%s" % (job_id, rc, tail))
    elif rc != 0:
        _send(notify, channels.get("alerts"), "ALERT %s exit %d\n%s" % (job_id, rc, tail))
    elif spec.get("deliver") and text.strip():
        _send(notify, channels.get("archive"), text)
    return rc
