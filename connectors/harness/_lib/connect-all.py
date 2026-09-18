#!/usr/bin/env python3
"""sov connect all: connect every tool found on this machine, in one go.

Reads the harness catalog, keeps the ones whose `detect` paths exist, and runs each
installer with the same flags. An already-connected tool is kept too when it is
connected the old way: its lane is missing from the connector manifest, the one
shared job that runs every lane is not loaded, or a per-tool job still carries it.
Installing is idempotent, so re-running it is how a machine moves from a job per
tool onto the shared runner, and the run says which tools it re-runs and why.
Without --apply every installer prints its dry run and changes nothing. A tool whose
declared credential this run cannot see is named once and left out of the selection: its
installer would stop before it wrote anything, on this pass and on every pass after, so
the rest of the machine connects and the run still ends at 0.

Two kinds of lane, and the difference decides both questions above. A tool on this
machine mirrors local files on the shared tick, so it is declared in the manifest and
carried by the runner. A cloud pull has nothing local to find (no `detect` paths), runs
on a wall clock because one run can outlive a tick, and therefore keeps a job of its own:
it declares itself in the manifest as a non-runner lane (`tick: false`, which the runner
skips and `sov disconnect all` still reaches), and it belongs to the hub, so a machine
that points at a hub never installs it. `bin/sov connect <tool>` recognizes it the same
way. Declared is declared for both kinds; what differs is which job carries the lane, so
the runner tests below say nothing about a lane the runner was never meant to tick.

Usage: connect-all.py [--host H] [--vault V] [--core a,b] [--hub alias:/path] [--apply]
"""
import os, sys, json, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
args = sys.argv[1:]
status = json.loads(subprocess.run([sys.executable, os.path.join(TEMPLATE, "bin", "sov-status"), "--json", "--no-hub"],
                                   capture_output=True, text=True).stdout or "{}")
catalog = status.get("harnesses")
if not catalog:  # not connected yet: build the catalog from detect paths alone
    catalog = []
    for hd in sorted(glob.glob(os.path.join(TEMPLATE, "connectors", "harness", "*"))):
        h = os.path.basename(hd)
        if h.startswith("_") or not os.path.isdir(hd):
            continue
        try:
            meta = json.load(open(os.path.join(hd, "harness.json")))
        except Exception:
            meta = {}
        det = meta.get("detect")
        catalog.append({"id": h, "name": meta.get("name", h), "state": "not connected",
                        "detected": any(os.path.exists(os.path.expanduser(x)) for x in det) if det else None})


def _manifest():
    """The connector manifest, read exactly where sov-status and the installer read it."""
    sd = os.environ.get("SOV_STATE_DIR") or os.path.expanduser("~/.local/state/sovereign")
    try:
        m = json.load(open(os.environ.get("SOV_MANIFEST") or os.path.join(sd, "connectors.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def _pointer(p):
    try:
        return open(os.path.expanduser(p), encoding="utf-8").read().strip() or None
    except OSError:
        return None


def _flag(name):
    """The value this run passes for a flag, before any pointer file has been written."""
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


_META = {}


def harness_meta(h):
    """A harness's own declaration, read from its harness.json."""
    hid = h["id"]
    if hid not in _META:
        try:
            _META[hid] = json.load(open(os.path.join(TEMPLATE, "connectors", "harness", hid, "harness.json"),
                                        encoding="utf-8"))
        except (OSError, ValueError):
            _META[hid] = {}
    return _META[hid]


def is_cloud_pull(h):
    """No detect paths: there is nothing on this machine to find, because the material is
    in a cloud account. Such a lane runs on a wall clock and keeps a job of its own."""
    return not harness_meta(h).get("detect")


MANIFEST = _manifest()
DECLARED = MANIFEST.get("harnesses") or {}
PLATFORM = os.environ.get("SOV_PLATFORM") or ("Darwin" if sys.platform == "darwin" else "Linux")
RUNNER_LABEL = ((MANIFEST.get("runner") or {}).get("label")
                or ("com.sovereign.connector.runner" if PLATFORM == "Darwin" else "sovereign-connector-runner"))
# sov-status already probes the jobs this user's OS really carries (and over ssh,
# where `launchctl list` sees nothing, it falls back to `launchctl print`), so ask it
# rather than probing again here.
RUNNER_LOADED = any(j.get("label") == RUNNER_LABEL for j in (status.get("jobs") or []))
# Which machine is the hub. sov-status is asked with --no-hub here on purpose: a
# migration must not depend on the hub being reachable, and re-walking a live API on
# every pass is exactly what makes one never settle. So the hub is read the same way
# `bin/sov connect <tool>` reads it - the pointer this machine carries (or the one this
# run is about to write), and the host it names.
HUB_ALIAS = ((_flag("--hub") or _pointer("~/.brain-hub") or "").split(":")[0]) or None
HOST = _flag("--host") or _pointer("~/.brain-host") or (status.get("machine") or {}).get("host") or ""
HUB_IS_ELSEWHERE = bool(HUB_ALIAS) and HUB_ALIAS != HOST


def hub_carries(h):
    """A cloud pull runs where the hub is, and installing it here would give one account
    two pullers writing one lane. sov-status can say so outright (`runs_on`), but only
    when it reached the hub, which this command does not ask it to do; the harness's own
    declaration and the hub pointer say the same thing without leaving the machine."""
    return HUB_IS_ELSEWHERE and is_cloud_pull(h)


def needs_credential(h):
    """The credential a harness declares (`secret.env` in its own harness.json) and this
    run cannot see, or None when nothing is in the way. A machine-wide connect has only
    two places to find one: the environment it was started with, and a `--secret` on its
    own command line. With neither, the installer of a machine that was never given the
    credential stops before it writes anything, and stops in the same place on every pass
    after - so re-selecting it is how this command exits non-zero forever and never
    settles, while the rest of the machine is connected perfectly the whole time.

    That is not a step of the migration waiting to happen; it is a thing only the owner
    can supply. So it is named once, with the commands that end it, and left out of the
    selection. Naming it is the point: skipping it quietly would leave a lane nobody
    mirrors and a run with nothing in it to say why."""
    s = harness_meta(h).get("secret") or {}
    if not s.get("env") or "--secret" in args or os.environ.get(s["env"]):
        return None
    return s


def rides_runner(h):
    """Whether the shared runner is what carries this lane. A calendar-cadence lane
    declares itself with `tick: false`: it is declared like any other, but it keeps its own
    wall-clock job, so neither the runner's own job nor the label carrying the lane says
    anything about whether it is migrated. The manifest's word settles it; the harness's
    own declaration answers for a lane not declared here at all."""
    e = DECLARED.get(h.get("id"))
    if isinstance(e, dict) and "tick" in e:
        t = e["tick"]
        # read exactly as `sov connect` writes it and the runner reads it, hand-written
        # "false" included: three readers of one file must not disagree about one lane
        return t.strip().lower() not in ("false", "0", "no", "") if isinstance(t, str) else bool(t)
    return not is_cloud_pull(h)


def rerun_reason(h):
    """Why an already-connected tool is connected again, or None when this machine has
    it on the shared runner. `state: connected` only means something is mirroring the
    lane today - on a machine that still runs a job per tool, every tool is connected
    and none of them is migrated. Skipping them is how a migration becomes a silent
    no-op; re-running one costs seconds and is idempotent."""
    if h.get("id") not in DECLARED:
        # A cloud pull that has not declared itself is not waiting to migrate onto the
        # runner - it never joins it - and re-selecting it forever is how a migration
        # never settles, at the price of a live API walk every pass.
        return None if is_cloud_pull(h) else "that are not in the manifest yet"
    if not rides_runner(h):
        # Declared, and declared as a lane this machine's shared job does not tick. It is
        # on its own schedule by design, so every test below would select it on every pass
        # forever: the runner job it is not in, and the per-tool label that is its own.
        return None
    if not RUNNER_LOADED:
        return "whose lanes are declared but not running (`%s` is not loaded)" % RUNNER_LABEL
    carrier = h.get("runs_in")
    if carrier and carrier != RUNNER_LABEL:
        return "that a per-tool job still carries"
    return None


todo, again, on_hub, own_job, blocked = [], [], [], [], []
for h in catalog:
    if h.get("detected") is False:
        continue
    if hub_carries(h):
        on_hub.append(h)
        continue
    if h.get("state") != "connected":
        want = needs_credential(h)
        if want:
            blocked.append((h, want))
            continue
        todo.append(h)
        continue
    why = rerun_reason(h)
    if why:
        todo.append(h)
        again.append((why, h))
    elif is_cloud_pull(h):
        own_job.append(h)
# Every print below is flushed. Each installer writes straight to this same fd while
# this file's own stdout is block buffered the moment it is a pipe, so without the flush
# the plan lands after the output it describes - through `tee`, or over ssh, which is
# every time anyone keeps a log of a migration.
for h in on_hub:
    print("%s is a cloud pull and runs on the hub (%s), not here: connect it there with `sov connect %s`"
          % (h["name"], HUB_ALIAS, h["id"]), flush=True)
    if h.get("state") == "connected":
        print("  it is also installed on this machine: two pullers into one lane. To stop this "
              "one: `sov disconnect %s --apply`" % h["id"], flush=True)
# Not connected here, and not connectable by this command: it wants a credential only the
# owner has. Every pass would stop in the same place, so it is said once, with both ways to
# end it, and then left alone - and the run still ends at 0 with the rest of the machine
# connected. Said before the plan, with the other lanes this pass is leaving alone.
for h, s in blocked:
    print("%s needs a credential this run does not carry (%s): connect it on its own with "
          "`sov connect %s --apply`" % (h["name"], s.get("label") or s["env"], h["id"]), flush=True)
    print("  that command takes `--secret TOKEN`, or a token this machine already holds; or put "
          "%s in this run's environment and try again" % s["env"], flush=True)
# A cloud pull connected here is connected and not on the runner, so the count of what
# this machine carries is only honest if it is named.
for h in own_job:
    print("%s is connected here and keeps its own job (`%s`): a pull whose run can outlive a "
          "tick cannot share one." % (h["name"], h.get("label") or h["id"]), flush=True)
if not todo:
    print("every tool found on this machine is already connected and runs on `%s`: %s"
          % (RUNNER_LABEL, ", ".join(h["name"] for h in catalog if h.get("detected"))), flush=True)
    sys.exit(0)
print("connecting %d tool(s): %s%s" % (len(todo), ", ".join(h["name"] for h in todo),
                                       "" if "--apply" in args else "  (dry run)"), flush=True)
for why in list(dict.fromkeys(w for w, _ in again)):
    names = [x["name"] for w, x in again if w == why]
    print("  re-running connect for %d already-connected tool(s) %s: %s" % (len(names), why, ", ".join(names)), flush=True)
rc = 0
for h in todo:
    print("\n=== %s ===" % h["name"], flush=True)
    r = subprocess.run(["/bin/bash", os.path.join(TEMPLATE, "connectors", "harness", h["id"], "install.sh")] + args)
    rc = rc or r.returncode
sys.exit(rc)
