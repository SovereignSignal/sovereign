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
    channels = inst.get("notify") or {}
    if rc != 0:
        tail = "\n".join(text.strip().splitlines()[-TAIL_LINES:])
        _send(notify, channels.get("alerts"), "ALERT %s exit %d\n%s" % (job_id, rc, tail))
    elif spec.get("deliver") and text.strip():
        _send(notify, channels.get("archive"), text)
    return rc
