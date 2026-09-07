#!/bin/bash
# Shared installer steps for every harness connector. Sourced, not run.
#
# A harness install.sh sets HARNESS and LANE_PREFIX, sources this file, then calls
# the steps it needs. Everything written is instance-level: pointer files, one
# manifest entry, one hook entry, one LANE.md. The template stays general.
#
# One machine, one connector job. A harness no longer gets a job of its own: it
# declares itself in the connector manifest and the shared runner ticks every lane.
# The split that remains is forced by macOS TCC, not by tooling: a job's own Program
# is the responsible process, so the script runner (python3) cannot write a vault
# under a protected folder, and /usr/bin/rsync, which holds the grant, moves the
# bytes. Two jobs on a client Mac, one on a machine whose vault is outside TCC -- and
# that same mover on either platform once a directory pipe is declared, because a pipe
# belongs to no lane and something has to carry it.
#
#   sov_parse_args "$@"       --host --vault --core --hub --interval --cadence
#                             --timeout --label --no-launchd --disconnect --apply
#   sov_resolve               VAULT CORE HOST LANE LANE_DIR WRITE_VIA LABEL
#                             RUNNER_LABEL RELAY_LABEL STATE_DIR LANES_DIR MANIFEST_JSON
#   sov_plan <line>...        print the dry-run summary (always)
#   sov_write_pointers        ~/.brain-root ~/.brain-core ~/.brain-host
#   sov_link_bins             ~/brain-bin/{brain-load,brain-capture,brain-lane-scope,sov,sov-connectors-run}
#   sov_merge_hook_claude_style <json> <hook> <matcher>   Claude Code settings.json / Codex hooks.json
#   sov_merge_hook_cursor <json> <hook>                   Cursor ~/.cursor/hooks.json (version 1)
#   sov_register_connector <mirror.sh>                    declare this lane, ensure the shared job
#   sov_unregister_connector <harness>                    undeclare it, drop the job when it was the last
#   sov_install_calendar_job <script> <HH:MM> [K=V...]    a lane whose cadence is a wall clock
#                                                         time: declared `"tick": false`, and
#                                                         it keeps a job of its own
#   sov_retire_legacy_jobs <harness>|--all                park the old per-tool jobs, once the
#                                                         shared job is loaded AND has run the
#                                                         lane on its own schedule
#   sov_lane_contract <LANE.md.tmpl> <read line>          render, or patch read: + note
#   sov_assert_staging_carried                            refuse to make a lane directory
#                                                         before the job that carries staging
#   sov_smoke_mirror <mirror.sh>
#   sov_smoke_runner <harness>
#   sov_smoke_hook <hook> <claude|cursor>
#   sov_relay_add <path> [name] | sov_relay_remove <name> | sov_relay_list
set -euo pipefail

HOST=""; VAULT=""; CORE=""; HUB=""; INTERVAL=900; APPLY=0; LABEL=""
TIMEOUT=300; TIMEOUT_SET=0; NO_LAUNCHD=0; DISCONNECT=0
CALENDAR_CADENCE_S=86400               # a wall-clock job runs once a day, whatever the tick is
RUNNER_JOB_LOADED=0                    # set only where the shared job was really loaded
STAGING_MADE_HERE=0                    # a staging tree THIS run made, nothing carrying it yet
_pointer() { [ -f "$1" ] && tr -d '\n' < "$1" || true; }
say() { printf '%s\n' "$*"; }

# Test seams. Nothing here is instance data: a stub launchctl/systemctl lets the
# installer be exercised without touching the machine, and SOV_PLATFORM lets the
# Linux half run on a Mac. Same shape as SOV_TEST_CHECK_OUTPUT in the notion harness.
_sov_launchctl() { "${SOV_LAUNCHCTL:-launchctl}" "$@"; }
_sov_systemctl() { "${SOV_SYSTEMCTL:-systemctl}" "$@"; }

sov_parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --host) HOST="$2"; shift 2;;
      --vault) VAULT="$2"; shift 2;;
      --core) CORE="$2"; shift 2;;
      --hub) HUB="$2"; shift 2;;
      --interval) INTERVAL="$2"; shift 2;;
      --cadence) INTERVAL="$2"; shift 2;;
      --timeout) TIMEOUT="$2"; TIMEOUT_SET=1; shift 2;;
      --label) LABEL="$2"; shift 2;;
      --no-launchd) NO_LAUNCHD=1; shift;;
      --disconnect) DISCONNECT=1; shift;;
      --apply) APPLY=1; shift;;
      -h|--help) sed -n '2,20p' "$0"; exit 0;;
      *) echo "unknown option: $1" >&2; exit 64;;
    esac
  done
}

# Paths that do not depend on which harness is being installed, so `sov relay` and
# `sov disconnect` can reach them without naming a tool.
sov_resolve_state() {
  PLATFORM="${SOV_PLATFORM:-$(uname -s)}"
  STATE_DIR="${SOV_STATE_DIR:-$HOME/.local/state/sovereign}"
  LANES_DIR="$STATE_DIR/lanes"
  MANIFEST_JSON="${SOV_MANIFEST:-$STATE_DIR/connectors.json}"
  RUNS_JSON="$STATE_DIR/runs.json"
  # The tick each lane's installer last ran BY HAND, stamped so it can never be mistaken
  # for the scheduler's work. Retiring a working per-tool job on evidence this script
  # produced itself is how a machine ends up with nothing mirroring at all. It is keyed
  # BY LANE: the evidence is per lane, and one machine-wide stamp made every later
  # installer in a `sov connect all --apply` pass discount the tick the one before it had
  # just run, so a pass retired exactly one legacy job and left the rest.
  INSTALL_TICK_MARK="$STATE_DIR/.installer-tick"
  RUNNER_BIN="$TEMPLATE/bin/sov-connectors-run"
  if [ "$PLATFORM" = "Darwin" ]; then
    RUNNER_LABEL="com.sovereign.connector.runner"
    RELAY_LABEL="com.sovereign.connector.relay"
    RUNNER_UNIT="$HOME/Library/LaunchAgents/$RUNNER_LABEL.plist"
    RELAY_UNIT="$HOME/Library/LaunchAgents/$RELAY_LABEL.plist"
    RETIRED_DIR="$HOME/Library/LaunchAgents/sovereign-retired"
    SCHEDULER="launchd"
  else
    # The suffix is load bearing: brain-status matches sovereign-connector-<name>.timer,
    # so a bare "sovereign-connector.timer" would make every Linux console report no jobs.
    RUNNER_LABEL="sovereign-connector-runner"
    # No TCC and no staging hop here, so no lane stages; a declared directory pipe still
    # has to be carried by something, and on Linux nothing else would.
    RELAY_LABEL="sovereign-connector-relay"
    RUNNER_UNIT="$HOME/.config/systemd/user/$RUNNER_LABEL.service"
    RELAY_UNIT="$HOME/.config/systemd/user/$RELAY_LABEL.service"
    RETIRED_DIR="$STATE_DIR/retired-units"
    SCHEDULER="a systemd user timer"
  fi
}

# The vault sits under a TCC-protected folder: a job whose Program is a script host
# cannot write there and the denial is silent, so mirrors stage and rsync carries.
_sov_vault_is_protected() {
  case "$VAULT/" in
    "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*) return 0;;
  esac
  return 1
}

sov_resolve() {
  case "${HARNESS:-}" in
    runner|relay) echo "harness id '$HARNESS' is reserved for the shared connector job" >&2; exit 64;;
  esac
  VAULT="${VAULT:-$(_pointer "$HOME/.brain-root")}"
  CORE="${CORE:-$(_pointer "$HOME/.brain-core")}"
  HOST="${HOST:-$(_pointer "$HOME/.brain-host")}"
  HOST="${HOST:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
  VAULT="${VAULT/#\~/$HOME}"
  [ -n "$VAULT" ] || { echo "need --vault PATH (or ~/.brain-root)"; exit 64; }
  [ -d "$VAULT/knowledge" ] || { echo "not a brain: $VAULT has no knowledge/ folder"; exit 66; }
  [ -n "$CORE" ] || echo "note: no always-on core (--core a,b,c or ~/.brain-core); packs will be topic-only"
  sov_resolve_state
  NEED_STAGING=0
  LANE="$LANE_PREFIX-$HOST"
  GIT_LANE="$(_pointer "$HOME/.brain-lane")"
  if [ -n "$GIT_LANE" ] && grep -qsE "^write:[[:space:]]*git-branch" "$VAULT/raw/workspaces/$GIT_LANE/LANE.md"; then
    LANE="$GIT_LANE"; LANE_DIR="$VAULT/raw/workspaces/$GIT_LANE/$LANE_PREFIX"; WRITE_VIA=" (git lane $GIT_LANE, branch pushed by the mirror)"
  elif [ "$PLATFORM" = "Darwin" ] && { [ -d "$HOME/.vault-staging" ] || _sov_vault_is_protected; }; then
    # Darwin only. A Linux box that ever grew a stray staging directory would write
    # every lane into a dead end: the mover that drains it does not exist there.
    GIT_LANE=""; LANE_DIR="$HOME/.vault-staging/raw/tools/$LANE"; WRITE_VIA=" (via staging)"
    [ -d "$HOME/.vault-staging" ] || NEED_STAGING=1
  else
    GIT_LANE=""; LANE_DIR="$VAULT/raw/tools/$LANE"; WRITE_VIA=""
  fi
  # LABEL is the LOGICAL lane identity, not a launchd handle any more: the console row
  # id, the Needs-You jump target, the display name, and the sentence already written
  # into every lane contract in the synced vault. It keeps its exact old value.
  if [ "$PLATFORM" = "Darwin" ]; then
    LABEL="${LABEL:-com.sovereign.connector.$HARNESS}"
  else
    LABEL="${LABEL:-sovereign-connector-$HARNESS}"
  fi
  # PLIST is this harness's OWN unit path. Only a calendar-cadence harness installs one;
  # every tick-cadence lane rides the shared runner and writes no unit of its own.
  if [ "$PLATFORM" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  else
    PLIST="$HOME/.config/systemd/user/$LABEL.service"
  fi
  # A lane that can outlive a tick would starve every other lane: neither launchd
  # StartInterval nor systemd Type=oneshot starts a second run while one is in flight.
  if [ "$TIMEOUT_SET" -eq 1 ]; then
    [ "$TIMEOUT" -le "$INTERVAL" ] || { echo "a lane that can outlive a tick needs its own job; see the calendar-job path (--timeout $TIMEOUT > --interval $INTERVAL)" >&2; exit 65; }
  elif [ "$TIMEOUT" -gt "$INTERVAL" ]; then
    TIMEOUT="$INTERVAL"                  # unset default, clamped rather than refused
  fi
  TODAY="$(date +%F)"
  [ "$DISCONNECT" -eq 1 ] && sov_unregister_connector "$HARNESS"
  return 0
}

sov_plan() {
  say "Sovereign connector: $HARNESS on host '$HOST'"
  say "  vault      $VAULT"
  say "  core       ${CORE:-(none)}"
  say "  lane       $LANE_DIR"
  for l in "$@"; do say "  $l"; done
  say "  template   $TEMPLATE"
  if [ "$APPLY" -ne 1 ]; then say; say "dry run. add --apply to install."; exit 0; fi
}

sov_write_pointers() {
  printf '%s' "$VAULT" > "$HOME/.brain-root"
  [ -n "$CORE" ] && printf '%s' "$CORE" > "$HOME/.brain-core"
  printf '%s' "$HOST" > "$HOME/.brain-host"
  [ -n "$HUB" ] && printf '%s' "$HUB" > "$HOME/.brain-hub"
  say "[pointers] ~/.brain-root ~/.brain-core ~/.brain-host${HUB:+ ~/.brain-hub}"
}

sov_link_bins() {
  mkdir -p "$HOME/brain-bin"
  for b in brain-load brain-capture brain-lane-scope sov sov-connectors-run; do
    [ -e "$TEMPLATE/bin/$b" ] && ln -sfn "$TEMPLATE/bin/$b" "$HOME/brain-bin/$b"
  done
  chmod +x "$TEMPLATE/bin/sov" 2>/dev/null || true
  say "[bins] ~/brain-bin -> $TEMPLATE/bin"
}

# Claude Code settings.json and Codex hooks.json share one shape:
#   {"hooks": {"SessionStart": [{"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}]}}
sov_merge_hook_claude_style() {
  local json="$1" hook="$2" matcher="$3"
  mkdir -p "$(dirname "$json")"
  [ -f "$json" ] || echo '{}' > "$json"
  cp "$json" "$json.bak-$(date +%Y%m%d-%H%M%S)"
  chmod +x "$hook" 2>/dev/null || true
  /usr/bin/python3 - "$json" "$hook" "$matcher" <<'EOF'
import json, sys
path, hook, matcher = sys.argv[1:4]
d = json.load(open(path))
groups = d.setdefault("hooks", {}).setdefault("SessionStart", [])
if any(h.get("command") == hook for g in groups for h in g.get("hooks", [])):
    print("[hook] already present in", path)
else:
    groups.append({"matcher": matcher,
                   "hooks": [{"type": "command", "command": hook, "timeout": 30,
                              "statusMessage": "Sovereign: loading brain context"}]})
    json.dump(d, open(path, "w"), indent=2)
    print("[hook] SessionStart added to", path)
EOF
}

# Cursor: {"version": 1, "hooks": {"sessionStart": [{"command": "...", "timeout": 30}]}}
sov_merge_hook_cursor() {
  local json="$1" hook="$2"
  mkdir -p "$(dirname "$json")"
  [ -f "$json" ] || echo '{"version": 1, "hooks": {}}' > "$json"
  cp "$json" "$json.bak-$(date +%Y%m%d-%H%M%S)"
  chmod +x "$hook" 2>/dev/null || true
  /usr/bin/python3 - "$json" "$hook" <<'EOF'
import json, sys
path, hook = sys.argv[1:3]
d = json.load(open(path))
d.setdefault("version", 1)
arr = d.setdefault("hooks", {}).setdefault("sessionStart", [])
if any(h.get("command") == hook for h in arr):
    print("[hook] already present in", path)
else:
    arr.append({"command": hook, "timeout": 30})
    json.dump(d, open(path, "w"), indent=2)
    print("[hook] sessionStart added to", path)
EOF
}

# ---------------------------------------------------------------------------
# The connector manifest: the one declaration of what this machine mirrors.
# Written only here (sov connect / disconnect / relay); the runner only reads it.
# JSON is never hand-assembled in bash, so a path with a space or a quote is safe.
# ---------------------------------------------------------------------------
_sov_manifest_py() {
  SOV_MF="$MANIFEST_JSON" SOV_RUNNER_LABEL="$RUNNER_LABEL" SOV_RELAY_LABEL="${RELAY_LABEL:-}" \
  SOV_STATE="$STATE_DIR" SOV_LANES="$LANES_DIR" /usr/bin/python3 - "$@" <<'PYEOF'
import json, os, sys

path = os.environ["SOV_MF"]
op = sys.argv[1]
pos, kw = [], {}
for a in sys.argv[2:]:
    if "=" in a:
        k, _, v = a.partition("=")
        kw[k] = v
    else:
        pos.append(a)

EXCL = [".DS_Store", ".env", ".secrets", ".*.tmp", "*.tmp", "*.jsonl", ".git/"]


def ticks(e):
    """Whether this entry is one the shared runner ticks. Hand-written "false" counts."""
    t = e.get("tick", True)
    if isinstance(t, str):
        return t.strip().lower() not in ("false", "0", "no", "")
    return bool(t)


def runs_on_the_tick(e):
    """A lane the shared runner carries. A calendar-cadence lane declares `tick: false`: it
    is in this file so `sov disconnect all`, which walks exactly this file, can reach the job
    it keeps of its own -- and for no other reason. The runner must never tick it, count it,
    stamp it, or take its wall-clock cadence for the tick every other lane shares."""
    # a missing "enabled" means on, the same default bin/sov-connectors-run applies. Disagreeing
    # here would let a lane tick while the installer left it out of the interval and the counts.
    return isinstance(e, dict) and bool(e.get("enabled", True)) and ticks(e)


def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(65)


def load():
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("version", 1)
    d.setdefault("harnesses", {})
    return d


def relay_argv(d):
    r = d.get("relay") or {}
    srcs = r.get("sources") or []
    if not srcs or not r.get("dest"):
        return None
    args = ["/usr/bin/rsync", "-a"]
    for e in r.get("excludes") or EXCL:
        args.append("--exclude=" + e)
    # staging first, then the directory pipes in declaration order
    srcs = sorted(srcs, key=lambda s: 0 if s.get("kind") == "staging" else 1)
    dest = r["dest"].rstrip("/") + "/"
    seen = set()
    for s in srcs:
        p = s["path"]
        # A trailing slash on a directory source exits 0, writes nothing to stderr and
        # dumps that directory's children loose into raw/tools/ beside the real lanes.
        p = (p.rstrip("/") + "/") if s.get("trailing_slash") else p.rstrip("/")
        # What it LANDS as, which is the basename rsync uses, not the declared name.
        land = "" if s.get("trailing_slash") else os.path.basename(p)
        if land and land in seen:
            die("two relay sources land as %r; they would merge into one destination" % land)
        seen.add(land)
        if (p.rstrip("/") + "/").startswith(dest):
            die("relay source %s sits under the destination %s; that would loop" % (p, dest))
        args.append(p)
    args.append(dest)
    if any(a == "--delete" for a in args):
        die("--delete is never emitted: it removes every lane no source covers")
    return args


def runner_interval(d):
    """The tick the runner will actually use. `load_manifest` in sov-connectors-run
    recomputes exactly this from the enabled lanes, so a timeout has to be judged
    against it and never against one lane's own cadence."""
    en = [h for h in d["harnesses"].values() if runs_on_the_tick(h)]
    # the tick must serve every declared cadence, so it is the smallest of them
    return min([int(h.get("cadence_s") or 900) for h in en] or [900])


def save(d):
    ivl = runner_interval(d)
    runner = d.get("runner") or {}
    runner.update({"label": os.environ["SOV_RUNNER_LABEL"], "interval_s": ivl,
                   "state_dir": os.environ["SOV_STATE"], "log_dir": os.environ["SOV_LANES"]})
    d["runner"] = runner
    if d.get("relay"):
        d["relay"]["interval_s"] = ivl
        relay_argv(d)                    # validate before it reaches a plist
    tmp = path + ".new"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


if op == "upsert-harness":
    d = load()
    hid = kw["id"]
    if hid in ("runner", "relay"):
        die("harness id %r is reserved for the shared connector job" % hid)
    e = d["harnesses"].get(hid) or {}
    fresh = not e
    tick = kw.get("tick", "true") != "false"
    e.update({"label": kw["label"], "mirror": kw["mirror"], "lane": kw["lane"],
              "lane_dir": kw["lane_dir"], "cadence_s": int(kw["cadence_s"]),
              "timeout_s": int(kw["timeout_s"]), "enabled": kw.get("enabled", "true") == "true",
              "tick": tick, "env": json.loads(kw.get("env_json") or "{}")})
    # A calendar lane names the job it keeps of its own, so `sov disconnect` can take that
    # job with it whatever the label was overridden to. The fields are cleared again if the
    # same harness is ever re-declared as a lane the runner ticks.
    if tick:
        e.pop("job_label", None)
        e.pop("at", None)
    else:
        e["job_label"] = kw.get("job_label") or kw["label"]
        if kw.get("at"):
            e["at"] = kw["at"]
    e.setdefault("registered", kw["registered"])
    d["harnesses"][hid] = e
    # The runner's tick is the SMALLEST cadence on this machine, not this lane's, and it
    # skips every lane whose timeout exceeds that tick. Judging against the lane's own
    # cadence accepts what the runner then refuses on every tick, for good.
    ivl = runner_interval(d)
    over = [(k, int(v.get("timeout_s") or 0)) for k, v in sorted(d["harnesses"].items())
            if runs_on_the_tick(v) and int(v.get("timeout_s") or 0) > ivl]
    if over:
        die("the shared tick is %ss (the smallest cadence declared here), and the runner skips "
            "every lane that can outlive a tick: %s. Lower the timeout, raise the fastest "
            "cadence, or give the lane its own job (the calendar-job path)."
            % (ivl, ", ".join("%s (timeout %ss)" % (k, t) for k, t in over)))
    save(d)
    print("declared" if fresh else "already declared")

elif op == "remove-harness":
    d = load()
    hid = pos[0] if pos else kw["id"]
    gone = d["harnesses"].pop(hid, None)
    save(d)
    print("removed" if gone else "absent")

elif op == "set-relay":
    d = load()
    r = d.get("relay") or {}
    r.update({"label": os.environ["SOV_RELAY_LABEL"], "enabled": True,
              "dest": kw["dest"].rstrip("/") + "/", "excludes": EXCL})
    r.setdefault("sources", [])
    d["relay"] = r
    save(d)
    print("relay dest %s" % r["dest"])

elif op == "upsert-relay-source":
    d = load()
    r = d.get("relay")
    if not r:
        die("no relay on this machine: its vault is not behind a staging hop")
    spath = kw["path"].rstrip("/") or "/"
    name = kw.get("name") or os.path.basename(spath)
    src = {"path": kw["path"], "kind": kw.get("kind", "dir"), "name": name,
           "trailing_slash": kw.get("trailing_slash", "false") == "true"}
    # Re-declaring the same path is an update; a DIFFERENT path that would land under
    # the same name is refused. Two sources sharing a basename merge into one
    # destination directory silently, at exit 0, with nothing on stderr.
    land = "" if src["trailing_slash"] else os.path.basename(spath)
    for old in r.get("sources", []):
        if old.get("path", "").rstrip("/") == spath:
            continue
        if old.get("name") == name or (land and not old.get("trailing_slash")
                                       and os.path.basename(old.get("path", "").rstrip("/")) == land):
            die("relay source %s would land as %r, which %s already claims; pass --name to give it another"
                % (kw["path"], land or name, old.get("path")))
    r["sources"] = [x for x in r.get("sources", []) if x.get("path", "").rstrip("/") != spath] + [src]
    d["relay"] = r
    save(d)
    print("relay source %s -> %s" % (name, src["path"]))

elif op == "remove-relay-staging":
    # The staging source belongs to the mover, not to a lane: it is declared when the mover is
    # installed, so it goes when the mover does. Left behind it outlived the job and made
    # `sov relay list` name a mover that is not there.
    d = load()
    r = d.get("relay") or {}
    before = len(r.get("sources") or [])
    r["sources"] = [s for s in r.get("sources", []) if s.get("kind") != "staging"]
    d["relay"] = r
    save(d)
    print("removed" if len(r["sources"]) != before else "absent")

elif op == "remove-relay-source":
    d = load()
    r = d.get("relay") or {}
    name = pos[0] if pos else kw["name"]
    before = len(r.get("sources") or [])
    r["sources"] = [s for s in r.get("sources", []) if s.get("name") != name]
    d["relay"] = r
    save(d)
    print("removed" if len(r["sources"]) != before else "absent")

elif op == "get":
    d = load()
    what = pos[0]
    if what == "runner-interval":
        print((d.get("runner") or {}).get("interval_s") or 900)
    elif what == "lane-count":
        # Bare: what the RUNNER carries. A calendar lane has a job of its own, so it is neither
        # one of the lanes the runner ticks nor a reason to keep the shared job alive for it.
        # `all`: every enabled lane, calendar ones included -- the different question of whether
        # this machine still mirrors anything at all, which decides what the mover carries and
        # whether "the last lane on this machine" is a true sentence.
        every = len(pos) > 1 and pos[1] == "all"
        keep = (lambda h: isinstance(h, dict) and bool(h.get("enabled"))) if every else runs_on_the_tick
        print(sum(1 for h in d["harnesses"].values() if keep(h)))
    elif what == "lane-ids":
        # EVERY declared lane, calendar ones included: `sov disconnect all` walks this list,
        # and a lane it cannot see keeps its job loaded while the command reports a clean
        # machine. `lane-ids tick` narrows it to the lanes the runner actually ticks.
        only_tick = len(pos) > 1 and pos[1] == "tick"
        for k, v in sorted(d["harnesses"].items()):
            if runs_on_the_tick(v) if only_tick else v.get("enabled"):
                print(k)
    elif what == "relay-dest":
        # where the mover REALLY writes, so a sentence built from this can never name a vault
        # the plist does not carry into
        print((d.get("relay") or {}).get("dest") or "")
    elif what == "has-relay":
        print("yes" if (d.get("relay") or {}).get("sources") else "no")
    elif what == "relay-argv":
        argv = relay_argv(d)
        if not argv:
            sys.exit(1)
        for a in argv:
            print(a)
    elif what == "relay-sources":
        for s in (d.get("relay") or {}).get("sources") or []:
            print("%s\t%s" % (s.get("name"), s.get("path")))
    elif what == "relay-dir-sources":
        # the watch folders alone: a staging hop belongs to the lanes, a pipe to nobody,
        # so only these decide whether the mover has work left after the last lane goes
        for s in (d.get("relay") or {}).get("sources") or []:
            if s.get("kind") != "staging":
                print("%s\t%s" % (s.get("name"), s.get("path")))
    elif what == "harness":
        print(((d["harnesses"].get(pos[1]) or {}).get(pos[2]) or ""))
    else:
        die("unknown get: " + what)

else:
    die("unknown manifest op: " + op)
PYEOF
}

# The vault is behind a staging hop: make the tree before the first mirror runs, so
# sov_dest cannot fall through to writing the vault from a script-program job (a
# silent TCC denial that looks exactly like success).
#
# Making it is not a local act. mirror-common.sh sov_dest sends EVERY mirror on this machine
# into staging the moment the directory exists, so a tree that exists before anything can
# carry it into the vault is the silent stall this whole change removes, wearing the shape of
# a success. It is therefore made only after the shared job is up, and a tree THIS run made
# is taken back if the run dies before the mover is loaded.
sov_ensure_staging() {
  [ "${NEED_STAGING:-0}" = "1" ] || return 0
  mkdir -p "$HOME/.vault-staging/raw/tools"
  STAGING_MADE_HERE=1
  trap '_sov_rollback_staging' EXIT
  say "[staging] ~/.vault-staging created: the vault is inside a protected folder, so mirrors stage and the mover carries them in"
  NEED_STAGING=0
}

# Armed only while a staging tree this run made is still uncarried; cleared the moment the
# mover is up. rmdir, never rm -r: if a mirror has already written there those bytes are the
# lane's, and the honest report is then that the tree stands and the mover is what is missing.
_sov_rollback_staging() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "${STAGING_MADE_HERE:-0}" = "1" ]; then
    rmdir "$HOME/.vault-staging/raw/tools" "$HOME/.vault-staging/raw" "$HOME/.vault-staging" 2>/dev/null || true
    if [ -d "$HOME/.vault-staging" ]; then
      echo "[staging] this install failed with ~/.vault-staging in place and nothing loaded to carry it: every mirror on this Mac writes there until \`sov connect\` succeeds" >&2
    else
      echo "[staging] this install failed before anything could carry staging, so the tree it made is gone: no mirror on this Mac is redirected into a tree nothing drains" >&2
    fi
  fi
  return "$rc"
}

# Replaces the per-tool job. Declares the lane and makes sure the machine's one
# connector job (and, behind a staging hop, its one mover) exists and is current.
sov_register_connector() {
  local mirror="$1" ivl n
  chmod +x "$mirror" 2>/dev/null || true
  mkdir -p "$LANES_DIR"; chmod 700 "$STATE_DIR" 2>/dev/null || true
  # a freshly connected lane must read "0 err", never "no log": a missing error log
  # makes brain-status report null, which the console renders as "never ran".
  : >> "$LANES_DIR/$HARNESS.log"; : >> "$LANES_DIR/$HARNESS.error.log"
  _sov_manifest_py upsert-harness "id=$HARNESS" "label=$LABEL" "mirror=$mirror" \
    "lane=$LANE" "lane_dir=$LANE_DIR" "cadence_s=$INTERVAL" "timeout_s=$TIMEOUT" \
    enabled=true env_json='{}' "registered=$TODAY" >/dev/null
  sov_ensure_runner_job
  # Not before here: until the shared job is loaded there is nothing on this machine that
  # could carry a staging tree, and sov_ensure_runner_job exits on a bootstrap that fails.
  sov_ensure_staging
  sov_ensure_relay_job
  STAGING_MADE_HERE=0                    # the mover is up, or none is needed: the tree is carried
  ivl="$(_sov_manifest_py get runner-interval)"
  n="$(_sov_manifest_py get lane-count)"
  # what this job ticks, named as such: a calendar lane is declared on this machine too and
  # is not one of them, so "on this machine" was a count the manifest could contradict
  say "[runner] $HARNESS registered; $RUNNER_LABEL runs every ${ivl}s ($n lane(s) on the shared tick)"
  sov_retire_legacy_jobs "$HARNESS"
}

# Render the unit, compare byte for byte, and only rewrite plus reload when it changed:
# connecting a second tool must not boot out a tick already in flight.
sov_ensure_runner_job() {
  local ivl tmp env_extra="" changed=0
  [ -x "$RUNNER_BIN" ] || chmod +x "$RUNNER_BIN" 2>/dev/null || true
  [ -f "$RUNNER_BIN" ] || { echo "the connector runner is missing: $RUNNER_BIN" >&2; exit 70; }
  ivl="$(_sov_manifest_py get runner-interval)"
  mkdir -p "$STATE_DIR"
  if [ "$PLATFORM" = "Darwin" ]; then
    mkdir -p "$HOME/Library/LaunchAgents"
    [ -n "${SOV_STATE_DIR:-}" ] && env_extra=$'\t\t<key>SOV_STATE_DIR</key>\n\t\t<string>'"$STATE_DIR"$'</string>'
    tmp="$(mktemp)"
    cat > "$tmp" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$RUNNER_LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>/usr/bin/python3</string>
		<string>$RUNNER_BIN</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StartInterval</key>
	<integer>$ivl</integer>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin</string>
${env_extra}
	</dict>
	<key>StandardOutPath</key>
	<string>$STATE_DIR/runner.log</string>
	<key>StandardErrorPath</key>
	<string>$STATE_DIR/runner.error.log</string>
</dict>
</plist>
EOF
    if [ -f "$RUNNER_UNIT" ] && cmp -s "$tmp" "$RUNNER_UNIT"; then
      rm -f "$tmp"
    else
      mv "$tmp" "$RUNNER_UNIT"; changed=1
    fi
    _sov_load_launchd "$RUNNER_LABEL" "$RUNNER_UNIT" "$changed" "every ${ivl}s"
  else
    _sov_linger_note
    mkdir -p "$HOME/.config/systemd/user"
    tmp="$(mktemp)"
    {
      echo "[Unit]"; echo "Description=Sovereign connectors: every write wire on this machine"; echo
      echo "[Service]"; echo "Type=oneshot"; echo "ExecStart=/usr/bin/python3 $RUNNER_BIN"
      echo "TimeoutStartSec=$ivl"
      echo "Environment=PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
      [ -n "${SOV_STATE_DIR:-}" ] && echo "Environment=SOV_STATE_DIR=$STATE_DIR"
      echo "StandardOutput=append:$STATE_DIR/runner.log"; echo "StandardError=append:$STATE_DIR/runner.error.log"
    } > "$tmp"
    if [ -f "$RUNNER_UNIT" ] && cmp -s "$tmp" "$RUNNER_UNIT"; then rm -f "$tmp"; else mv "$tmp" "$RUNNER_UNIT"; changed=1; fi
    tmp="$(mktemp)"
    {
      echo "[Unit]"; echo "Description=Sovereign connectors every ${ivl}s"; echo
      echo "[Timer]"; echo "OnBootSec=120"
      # measured from the END of a run, and Persistent so a sleeping laptop catches up
      # the way macOS StartInterval does; bare OnUnitActiveSec drifts.
      echo "OnUnitInactiveSec=$ivl"; echo "Persistent=true"; echo "Unit=$RUNNER_LABEL.service"; echo
      echo "[Install]"; echo "WantedBy=timers.target"
    } > "$tmp"
    if [ -f "${RUNNER_UNIT%.service}.timer" ] && cmp -s "$tmp" "${RUNNER_UNIT%.service}.timer"; then
      rm -f "$tmp"
    else
      mv "$tmp" "${RUNNER_UNIT%.service}.timer"; changed=1
    fi
    if [ "$NO_LAUNCHD" -eq 1 ]; then
      say "[systemd] $RUNNER_LABEL.timer written, not enabled (--no-launchd)"
      return 0
    fi
    _sov_systemctl --user daemon-reload
    # A swallowed failure here is the Linux twin of the silent TCC denial, and with one
    # unit it takes down every lane at once. It has to be loud.
    if ! _sov_systemctl --user enable --now "$RUNNER_LABEL.timer" >/dev/null 2>&1; then
      echo "[systemd] could not enable $RUNNER_LABEL.timer (no user manager, or no XDG_RUNTIME_DIR over ssh). No lane on this box will run." >&2
      exit 70
    fi
    RUNNER_JOB_LOADED=1
    say "[systemd] $RUNNER_LABEL.timer every ${ivl}s (logs: $STATE_DIR)"
  fi
}

# USER is not exported by every login: `brain-host-add` runs `sov connect all --apply`
# over ssh, and there it is often unset. Unguarded under `set -u` this aborted the whole
# Linux branch before a single unit was written, so no lane ran at all.
_sov_linger_note() {
  local u="${USER:-$(id -un)}"
  if [ "$(${SOV_LOGINCTL:-loginctl} show-user "$u" -p Linger --value 2>/dev/null)" != "yes" ]; then
    say "[systemd] NOTE: linger is off for $u, so the timer only runs while you are logged in. Fix once: sudo loginctl enable-linger $u"
  fi
}

# bootstrap only when the unit changed or the job is not loaded, so a tick in flight
# survives connecting the next tool.
_sov_load_launchd() {
  local label="$1" unit="$2" changed="$3" what="$4"
  if [ "$NO_LAUNCHD" -eq 1 ]; then
    say "[launchd] $unit written, not loaded (--no-launchd). Load it from a Terminal on this Mac:"
    say "          launchctl bootstrap gui/\$(id -u) $unit"
    return 0
  fi
  if [ "$changed" -eq 0 ] && _sov_launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    if [ "$label" = "$RUNNER_LABEL" ]; then RUNNER_JOB_LOADED=1; fi
    say "[launchd] $label already $what"
    return 0
  fi
  _sov_launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  if ! _sov_launchctl bootstrap "gui/$(id -u)" "$unit"; then
    # The mover is not the runner: what stops is the carry into the vault, not the lanes,
    # and a sentence that names the wrong failure sends the reader to the wrong job.
    if [ "$label" = "${RELAY_LABEL:-}" ]; then
      echo "[launchd] bootstrap of $label failed. Nothing would carry the staged lane(s) and declared directory pipe(s) into the vault; load it from a Terminal on this Mac:" >&2
    else
      echo "[launchd] bootstrap of $label failed. No lane on this Mac will run; load it from a Terminal here:" >&2
    fi
    echo "          launchctl bootstrap gui/\$(id -u) $unit" >&2
    exit 70
  fi
  if [ "$label" = "$RUNNER_LABEL" ]; then RUNNER_JOB_LOADED=1; fi
  say "[launchd] $label $what"
}

# One rsync job carries every staged lane and every declared directory pipe into the
# vault. Behind a staging hop its Program must be rsync, which holds the Full Disk Access
# grant: a job whose Program is a script host is denied under a protected folder,
# silently. Without a staging hop there is nothing to drain, so the mover exists only once
# a directory pipe is declared -- and then it MUST exist, on either platform, or
# `sov relay add` reports a pipe that nothing carries.
sov_ensure_relay_job() {
  local staged=0 what dest
  if [ "$PLATFORM" = "Darwin" ] && [ -d "$HOME/.vault-staging" ]; then
    staged=1
    _sov_manifest_py set-relay "dest=$VAULT/raw/tools" >/dev/null
    _sov_manifest_py upsert-relay-source "path=$HOME/.vault-staging/raw/tools/" kind=staging \
      "name=(contents)" trailing_slash=true >/dev/null
  elif [ "$(_sov_manifest_py get has-relay)" = "yes" ]; then
    # A pipe is declared and nothing stages. The destination is set here too, or it keeps
    # pointing at whatever vault this machine had on the day the pipe was declared while
    # every sentence below names the one in this run's argv.
    _sov_manifest_py set-relay "dest=$VAULT/raw/tools" >/dev/null
  else
    # Nothing staged and no pipe declared, so there is no mover to install -- and any
    # mover still on disk would keep rsyncing a source that is no longer declared.
    if [ -n "${RELAY_UNIT:-}" ] && [ -f "$RELAY_UNIT" ]; then
      _sov_drop_shared_job "$RELAY_LABEL" "$RELAY_UNIT"
      say "[relay] no source left to carry; the mover is gone"
    fi
    return 0
  fi
  # Named from what the manifest RECORDS, never from this run's argv: the sentence and the
  # last argument of the job it describes are then the same string by construction.
  dest="$(_sov_manifest_py get relay-dest)"
  if [ "$staged" -eq 1 ]; then
    what="moves staging into $dest"
  else
    what="moves $(_sov_relay_dir_count) directory pipe(s) into $dest"
  fi
  if [ "$PLATFORM" = "Darwin" ]; then _sov_relay_job_launchd "$what"; else _sov_relay_job_systemd "$what"; fi
}

_sov_relay_dir_count() { _sov_manifest_py get relay-dir-sources | grep -c . || true; }

_sov_relay_job_launchd() {
  local what="$1" tmp changed=0 args=() a
  while IFS= read -r a; do args+=("$a"); done < <(_sov_manifest_py get relay-argv)
  [ "${#args[@]}" -gt 0 ] || return 0
  mkdir -p "$HOME/Library/LaunchAgents"
  tmp="$(mktemp)"
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0">'
    echo '<dict>'
    printf '\t<key>Label</key>\n\t<string>%s</string>\n' "$RELAY_LABEL"
    echo '	<key>ProgramArguments</key>'
    echo '	<array>'
    for a in "${args[@]}"; do
      printf '\t\t<string>%s</string>\n' "$(_sov_xml "$a")"
    done
    echo '	</array>'
    echo '	<key>RunAtLoad</key>'
    echo '	<true/>'
    printf '\t<key>StartInterval</key>\n\t<integer>%s</integer>\n' "$(_sov_manifest_py get runner-interval)"
    printf '\t<key>StandardOutPath</key>\n\t<string>%s/relay.log</string>\n' "$STATE_DIR"
    printf '\t<key>StandardErrorPath</key>\n\t<string>%s/relay.error.log</string>\n' "$STATE_DIR"
    echo '</dict>'
    echo '</plist>'
  } > "$tmp"
  if [ -f "$RELAY_UNIT" ] && cmp -s "$tmp" "$RELAY_UNIT"; then rm -f "$tmp"; else mv "$tmp" "$RELAY_UNIT"; changed=1; fi
  _sov_load_launchd "$RELAY_LABEL" "$RELAY_UNIT" "$changed" "$what"
}

# The Linux half. No TCC here, so the mover is not forced on this platform by a grant; it
# exists because a declared directory pipe has to be carried by something, and on Linux
# nothing else would.
_sov_relay_job_systemd() {
  local what="$1" tmp ivl exec_line="" args=() a
  while IFS= read -r a; do args+=("$a"); done < <(_sov_manifest_py get relay-argv)
  [ "${#args[@]}" -gt 0 ] || return 0
  ivl="$(_sov_manifest_py get runner-interval)"
  for a in "${args[@]}"; do exec_line="$exec_line $(_sov_systemd_arg "$a")"; done
  mkdir -p "$HOME/.config/systemd/user" "$STATE_DIR"
  tmp="$(mktemp)"
  {
    echo "[Unit]"; echo "Description=Sovereign connectors: the directory pipes this machine carries"; echo
    echo "[Service]"; echo "Type=oneshot"; echo "ExecStart=${exec_line# }"
    echo "TimeoutStartSec=$ivl"
    echo "Environment=PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
    echo "StandardOutput=append:$STATE_DIR/relay.log"; echo "StandardError=append:$STATE_DIR/relay.error.log"
  } > "$tmp"
  if [ -f "$RELAY_UNIT" ] && cmp -s "$tmp" "$RELAY_UNIT"; then rm -f "$tmp"; else mv "$tmp" "$RELAY_UNIT"; fi
  tmp="$(mktemp)"
  {
    echo "[Unit]"; echo "Description=Sovereign connector mover every ${ivl}s"; echo
    echo "[Timer]"; echo "OnBootSec=120"
    echo "OnUnitInactiveSec=$ivl"; echo "Persistent=true"; echo "Unit=$RELAY_LABEL.service"; echo
    echo "[Install]"; echo "WantedBy=timers.target"
  } > "$tmp"
  if [ -f "${RELAY_UNIT%.service}.timer" ] && cmp -s "$tmp" "${RELAY_UNIT%.service}.timer"; then
    rm -f "$tmp"
  else
    mv "$tmp" "${RELAY_UNIT%.service}.timer"
  fi
  if [ "$NO_LAUNCHD" -eq 1 ]; then
    say "[systemd] $RELAY_LABEL.timer written, not enabled (--no-launchd)"
    return 0
  fi
  _sov_systemctl --user daemon-reload
  # A pipe declared and not carried is the failure this whole path exists to remove, so a
  # mover that will not enable is as loud as a runner that will not.
  if ! _sov_systemctl --user enable --now "$RELAY_LABEL.timer" >/dev/null 2>&1; then
    echo "[systemd] could not enable $RELAY_LABEL.timer (no user manager, or no XDG_RUNTIME_DIR over ssh). Nothing would carry the declared directory pipe(s) into the vault." >&2
    exit 70
  fi
  say "[systemd] $RELAY_LABEL.timer $what"
}

_sov_xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

# systemd expands $VAR and % specifiers inside ExecStart, and splits on whitespace, so
# every argument is quoted and those two characters are doubled.
_sov_systemd_arg() {
  printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\$/$$/g' -e 's/%/%%/g')"
}

# `sov relay add|remove|list`: the directory pipes (a watch folder a tool writes into)
# that used to be hand-installed plists. Needs sov_resolve_state and VAULT resolved.
sov_relay_add() {
  local p="$1" name="${2:-}" force="${3:-}"
  p="${p/#\~/$HOME}"
  [ -d "$p" ] || [ "$force" = "--force" ] || { echo "no such directory: $p (--force to declare it anyway)" >&2; exit 66; }
  case "$p" in /*) ;; *) p="$PWD/$p";; esac
  _sov_manifest_py set-relay "dest=$VAULT/raw/tools" >/dev/null
  _sov_manifest_py upsert-relay-source "path=${p%/}" kind=dir ${name:+"name=$name"} trailing_slash=false
  sov_ensure_relay_job
}

sov_relay_remove() {
  _sov_manifest_py remove-relay-source "$1" >/dev/null
  say "[relay] source $1 removed"
  sov_ensure_relay_job
}

sov_relay_list() {
  local srcs
  srcs="$(_sov_manifest_py get relay-sources)"
  # naming a job on a machine that carries nothing is how `sov relay list` came to
  # describe a mover that was never installed
  [ -n "$srcs" ] || { say "[relay] nothing declared here, so no mover is installed"; return 0; }
  say "[relay] $RELAY_LABEL -> $VAULT/raw/tools/"
  printf '%s\n' "$srcs" | sed 's/^/  /'
}

# ---------------------------------------------------------------------------
# Migration and removal. `launchctl bootout` used to be the only removal code in
# the repo; this is where it lives now, on both platforms.
# ---------------------------------------------------------------------------

# Proof one: the SHARED job is really loaded by the scheduler on this machine. Writing a
# unit is not loading it -- under --no-launchd nothing is bootstrapped at all -- and a
# machine whose only remaining job was never loaded mirrors nothing.
_sov_shared_job_loaded() {
  [ "$NO_LAUNCHD" -eq 1 ] && return 1
  [ "${RUNNER_JOB_LOADED:-0}" = "1" ] && return 0
  if [ "$PLATFORM" = "Darwin" ]; then
    _sov_launchctl print "gui/$(id -u)/$RUNNER_LABEL" >/dev/null 2>&1
  else
    _sov_systemctl --user is-enabled "$RUNNER_LABEL.timer" >/dev/null 2>&1
  fi
}

# Proof two: the shared job has actually run THIS LANE on its own schedule, AND that run
# came out clean. A tick this installer started by hand proves the wiring, never the
# schedule, so this lane's own stamp in .installer-tick, and everything at or before it, is
# discounted. Nothing legacy is removed before both proofs hold, so a machine whose runner
# never fired keeps its old jobs. The stamp is read per lane: one shared stamp let lane B
# discount the hand tick lane A's installer had just run seconds earlier, in the same
# `sov connect all` pass.
#
# A visit is not an outcome. The old per-tool job had no time bound at all and the shared
# runner imposes one, so a lane that now times out on every tick is attempted every tick and
# mirrors nothing: retiring its working job on the attempt alone leaves the machine with a
# lane that is killed on schedule. The scheduled visit therefore has to have SUCCEEDED --
# exit 0, not killed, not refused -- exactly as the runner recorded it.
#
# It is that OUTCOME that is judged, never the tick's selection. The runner also writes
# `skipped` for the two ordinary reasons a tick passes a lane by -- the cadence gate ("not
# due") and a --only run looking at another lane ("not selected") -- over a record that
# still carries the last real run forward. Read as failure, they withdrew on the very next
# tick the evidence a clean scheduled run had just produced: the legacy job was never
# retired and the machine never left the additive window.
_sov_runner_has_run() {
  local h="${1:-}"
  [ -f "$RUNS_JSON" ] || return 1
  SOV_RUNS="$RUNS_JSON" SOV_H="$h" SOV_MARK="$INSTALL_TICK_MARK" /usr/bin/python3 - <<'PYEOF'
import json, os, sys
try:
    d = json.load(open(os.environ["SOV_RUNS"], encoding="utf-8"))
except Exception:
    sys.exit(1)
tick = (d.get("runner") or {}).get("tick_finished")
if not tick:
    sys.exit(1)
h = os.environ.get("SOV_H") or ""


def marks():
    """{lane id: the hand tick that lane's installer ran}. "*" is the machine-wide slot:
    it holds the single stamp the one-stamp file used to be, and it still discounts every
    lane, because a stamp whose lane is unknown can only be read the conservative way."""
    try:
        raw = open(os.environ["SOV_MARK"], encoding="utf-8").read().strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        return {"*": raw}
    return {k: v for k, v in obj.items() if isinstance(v, str) and v}


m = marks()
if h:
    mark = m.get(h) or m.get("*") or ""
else:
    mark = max(m.values()) if m else ""
# Same UTC ISO shape from the same writer, so a plain string compare orders them.
if mark and tick <= mark:
    sys.exit(1)
if h:
    lane = (d.get("lanes") or {}).get(h) or {}
    if not lane.get("attempted_at"):
        sys.exit(1)
    if mark and lane["attempted_at"] <= mark:
        sys.exit(1)
    # A run that never reached an end is no evidence either.
    if not lane.get("finished_at"):
        sys.exit(1)
    # The benign skips are the tick's selection and say nothing about the run underneath.
    # Every other skip is the runner declining to run it (in flight, no log); refused is
    # the mirror gone or the lane over the tick; timed_out is a kill; last_exit anything
    # but 0 is a failed run, and None a lane that never got as far as an exit code.
    if lane.get("skipped") not in (None, "", "not due", "not selected"):
        sys.exit(1)
    if lane.get("refused"):
        sys.exit(1)
    if lane.get("timed_out"):
        sys.exit(1)
    if lane.get("last_exit") != 0:
        sys.exit(1)
sys.exit(0)
PYEOF
}

# Stamp the tick this installer just ran by hand, under the lane it ran. Called only after
# a hand-run, so the next invocation -- this lane's, not every lane's -- can tell the
# scheduler's work from this script's.
_sov_mark_install_tick() {
  local h="${1:-}"
  [ -f "$RUNS_JSON" ] || return 0
  mkdir -p "$STATE_DIR"
  SOV_RUNS="$RUNS_JSON" SOV_H="$h" SOV_MARK="$INSTALL_TICK_MARK" /usr/bin/python3 - <<'PYEOF'
import json, os
try:
    d = json.load(open(os.environ["SOV_RUNS"], encoding="utf-8"))
    tick = (d.get("runner") or {}).get("tick_finished")
except Exception:
    tick = None
if tick:
    path = os.environ["SOV_MARK"]
    try:
        raw = open(path, encoding="utf-8").read().strip()
    except OSError:
        raw = ""
    marks = {}
    if raw:
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
        # an older one-stamp file: keep it in the machine-wide slot, so upgrading never
        # licenses a retirement the old file was holding back
        marks = {k: v for k, v in obj.items() if isinstance(v, str) and v} \
            if isinstance(obj, dict) else {"*": raw}
    marks[os.environ.get("SOV_H") or "*"] = tick
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(marks, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
PYEOF
}

# One tool, or --all. macOS: boot the job out and park its plist in sovereign-retired/
# so `launchctl bootstrap` restores it. Linux: disable --now, park both units and
# delete the timers.target.wants symlink; unlike a stale plist, which is inert, an
# enabled timer keeps firing forever.
sov_retire_legacy_jobs() {
  local which="${1:-}" ids=() found=() h legacy unit
  if [ "$which" = "--all" ]; then
    # the lanes the RUNNER ticks: a calendar lane's own job is the live one, not a legacy
    while IFS= read -r h; do ids+=("$h"); done < <(_sov_manifest_py get lane-ids tick)
  else
    ids=("$which")
  fi
  [ "${#ids[@]}" -gt 0 ] || return 0
  # Only lanes that still carry a per-tool job are in question; the rest say nothing.
  found=()
  for h in "${ids[@]}"; do
    [ -n "$h" ] || continue
    if [ "$PLATFORM" = "Darwin" ]; then unit="$HOME/Library/LaunchAgents/com.sovereign.connector.$h.plist"
    else unit="$HOME/.config/systemd/user/sovereign-connector-$h.service"; fi
    if [ -f "$unit" ]; then found+=("$h"); fi
  done
  [ "${#found[@]}" -gt 0 ] || return 0
  # One gate for the whole machine: a unit that was written but never loaded schedules
  # nothing, so retiring anything against it swaps a working job for no job at all.
  if ! _sov_shared_job_loaded; then
    say "[migrate] ${#found[@]} per-tool job(s) kept: $RUNNER_LABEL is written but not loaded here (--no-launchd, or the bootstrap has not happened), so nothing else would mirror these lanes"
    return 0
  fi
  for h in "${found[@]}"; do
    if [ "$PLATFORM" = "Darwin" ]; then
      legacy="com.sovereign.connector.$h"; unit="$HOME/Library/LaunchAgents/$legacy.plist"
    else
      legacy="sovereign-connector-$h"; unit="$HOME/.config/systemd/user/$legacy.service"
    fi
    if ! _sov_runner_has_run "$h"; then
      say "[migrate] $legacy kept: $RUNNER_LABEL has not mirrored this lane cleanly on its own schedule yet (a killed, failed or refused run does not count, and neither does this installer's own). It goes at the next \`sov connect $h --apply\` after a scheduled run that succeeds."
      continue
    fi
    mkdir -p "$RETIRED_DIR"
    if [ "$PLATFORM" = "Darwin" ]; then
      _sov_launchctl bootout "gui/$(id -u)/$legacy" >/dev/null 2>&1 || true
      mv "$unit" "$RETIRED_DIR/"
    else
      _sov_systemctl --user disable --now "$legacy.timer" >/dev/null 2>&1 || true
      rm -f "$HOME/.config/systemd/user/timers.target.wants/$legacy.timer"
      mv "$unit" "$RETIRED_DIR/" 2>/dev/null || true
      mv "${unit%.service}.timer" "$RETIRED_DIR/" 2>/dev/null || true
      _sov_systemctl --user daemon-reload >/dev/null 2>&1 || true
      _sov_systemctl --user reset-failed >/dev/null 2>&1 || true
    fi
    if [ "$PLATFORM" = "Darwin" ]; then
      say "[migrate] $legacy booted out; its plist parked in $RETIRED_DIR (restore: launchctl bootstrap gui/\$(id -u) <plist>)"
    else
      say "[migrate] $legacy disabled; its units parked in $RETIRED_DIR (restore: copy them back and systemctl --user enable --now)"
    fi
  done
}

# Undeclare a lane. The raw/ material stays: it is provenance, not cache. When the last
# enabled lane goes, so does the shared job -- and the mover only if the pipes it carries
# went with it.
sov_unregister_connector() {
  local h="${1:-$HARNESS}" left declared own own_label lane_dir
  # The manifest, not this run's variables, is the record of where the lane writes and which
  # job (if any) it keeps of its own. A harness that sets its lane AFTER sov_resolve -- the
  # calendar path does, and sov_resolve dispatches this from inside itself -- would otherwise
  # report a lane path that exists on no disk.
  lane_dir="$(_sov_manifest_py get harness "$h" lane_dir)"
  [ -n "$lane_dir" ] || lane_dir="${LANE_DIR:-}"
  own_label="$(_sov_manifest_py get harness "$h" job_label)"
  if [ "$PLATFORM" = "Darwin" ]; then own_label="${own_label:-com.sovereign.connector.$h}"
  else own_label="${own_label:-sovereign-connector-$h}"; fi
  if [ "$APPLY" -ne 1 ]; then
    say "Sovereign connector: disconnect $h on host '$HOST'"
    say "  manifest   $MANIFEST_JSON"
    say "  lane       ${lane_dir:-(unknown)}  (kept: raw/ is provenance)"
    say; say "dry run. add --apply to disconnect."
    exit 0
  fi
  say "[manifest] $h $(_sov_manifest_py remove-harness "$h")"
  [ -f "$LANES_DIR/$h.error.log" ] && mv "$LANES_DIR/$h.error.log" "$LANES_DIR/$h.error.log.retired"
  # a calendar-cadence harness kept its own job; take that with it
  if [ "$PLATFORM" = "Darwin" ]; then own="$HOME/Library/LaunchAgents/$own_label.plist"
  else own="$HOME/.config/systemd/user/$own_label.service"; fi
  if [ -f "$own" ]; then
    mkdir -p "$RETIRED_DIR"
    if [ "$PLATFORM" = "Darwin" ]; then
      _sov_launchctl bootout "gui/$(id -u)/$own_label" >/dev/null 2>&1 || true
      mv "$own" "$RETIRED_DIR/"
    else
      _sov_systemctl --user disable --now "$own_label.timer" >/dev/null 2>&1 || true
      rm -f "$HOME/.config/systemd/user/timers.target.wants/$own_label.timer"
      mv "$own" "$RETIRED_DIR/" 2>/dev/null || true
      mv "${own%.service}.timer" "$RETIRED_DIR/" 2>/dev/null || true
      _sov_systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    say "[migrate] this harness's own job ($own_label) parked in $RETIRED_DIR"
  fi
  # Two different questions, and one count cannot answer both. The RUNNER's fate turns on the
  # lanes it ticks; whether this machine still mirrors anything -- which is what the mover
  # carries, and what "the last lane on this machine" means -- turns on every declared lane, a
  # calendar lane with a job of its own included.
  left="$(_sov_manifest_py get lane-count)"
  declared="$(_sov_manifest_py get lane-count all)"
  if [ "$left" -eq 0 ]; then
    # Only if the shared job was ever installed here: a machine whose one lane was a calendar
    # lane never had a runner, and announcing that its last lane stopped mirroring would name
    # a job that never existed.
    if [ -f "$RUNNER_UNIT" ]; then
      _sov_drop_shared_job "$RUNNER_LABEL" "$RUNNER_UNIT"
      if [ "$declared" -eq 0 ]; then
        say "[runner] that was the last lane on this machine; no lane mirrors from here any more"
      else
        say "[runner] no lane rides the shared tick here any more; $declared lane(s) with a job of their own stay"
      fi
    fi
    _sov_relay_after_last_lane "$declared"
  else
    sov_ensure_runner_job
    say "[runner] $left lane(s) still declared; $RUNNER_LABEL stays"
  fi
  say "[lane] ${lane_dir:-the lane directory} left in place; raw/ is provenance, never cache"
  exit 0
}

# The mover is not the runner's shadow. It carries the directory pipes (`sov relay add`),
# which belong to no lane, and behind a staging hop it carries the staging tree every lane
# on the machine writes into -- a calendar lane, which the runner never ticks, included. So
# the last lane the RUNNER carries leaving is not on its own a reason for it to go: dropping
# it there stopped every watch folder on the machine, and every staged lane still declared,
# and said nothing. It is passed the count of lanes still declared here, of either kind.
_sov_relay_after_last_lane() {
  local declared="${1:-0}" n dirs srcs stages=0
  [ -n "${RELAY_UNIT:-}" ] || return 0
  # The same test sov_ensure_relay_job makes: where that is true every lane on this machine
  # stages, so a lane still declared is a lane still staging, and this is the only thing that
  # carries it in.
  if [ "$PLATFORM" = "Darwin" ] && [ -d "$HOME/.vault-staging" ] && [ "$declared" -gt 0 ]; then
    stages=1
  fi
  dirs="$(_sov_manifest_py get relay-dir-sources)"
  n="$(printf '%s' "$dirs" | grep -c . || true)"
  if [ "$n" -gt 0 ] || [ "$stages" -eq 1 ]; then
    # rebuilt from what remains: the staging source when a lane still stages, plus the pipes
    sov_ensure_relay_job
    if [ "$stages" -eq 1 ]; then
      say "[relay] $RELAY_LABEL stays: $declared lane(s) with a job of their own still stage here, and nothing else carries them into $VAULT/raw/tools/"
    fi
    if [ "$n" -gt 0 ]; then
      say "[relay] $RELAY_LABEL stays: it still carries $n directory pipe(s), which no lane owns"
      printf '%s\n' "$dirs" | sed 's/^/  /'
    fi
    return 0
  fi
  [ -f "$RELAY_UNIT" ] || return 0
  # It goes -- so name what stops being carried, or a folder quietly stops mirroring.
  srcs="$(_sov_manifest_py get relay-sources)"
  if [ -n "$srcs" ]; then
    say "[relay] nothing is left for $RELAY_LABEL to carry; it goes too. These stop reaching $VAULT/raw/tools/:"
    printf '%s\n' "$srcs" | sed 's/^/  /'
  fi
  _sov_drop_shared_job "$RELAY_LABEL" "$RELAY_UNIT"
  # The staging source was the mover's own declaration; undeclared with it, so `sov relay
  # list` cannot go on describing a job that is not installed. The next mover redeclares it.
  _sov_manifest_py remove-relay-staging >/dev/null
}

_sov_drop_shared_job() {
  local label="$1" unit="$2"
  [ -n "$unit" ] || return 0
  if [ "$PLATFORM" = "Darwin" ]; then
    _sov_launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  else
    _sov_systemctl --user disable --now "$label.timer" >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/timers.target.wants/$label.timer" "${unit%.service}.timer"
    _sov_systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  rm -f "$unit"
  if [ "$PLATFORM" = "Darwin" ]; then say "[launchd] $label removed"; else say "[systemd] $label removed"; fi
}

# A lane whose run is measured in hours cannot share a tick: neither launchd
# StartInterval nor systemd Type=oneshot starts a second run while one is in flight,
# so it keeps a job of its own on a wall-clock schedule.
#
# It is still DECLARED in the manifest, as a non-runner lane: `tick: false`, its own job
# label, and its calendar cadence. The runner skips it entirely -- never runs it, never
# counts it as due, never stamps it -- while `sov disconnect all`, which walks exactly this
# manifest, can reach it. Left undeclared, its job survived a disconnect that reported a
# clean machine.
sov_install_calendar_job() {
  local script="$1" at="$2"; shift 2
  local hour min envxml="" k v kv
  case "$at" in [0-9][0-9]:[0-9][0-9]) ;; *) echo "calendar job wants HH:MM, got $at" >&2; exit 64;; esac
  # Its lane stages like every other one when the vault is behind a protected folder, and
  # the same one mover carries it in. Both calls are no-ops on a machine with neither.
  sov_ensure_staging
  mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR" 2>/dev/null || true
  # No lanes/ log pair is created here: this lane's output goes to its OWN job's log, which
  # is where the console already reads it, and a pair under lanes/ would show it twice.
  _sov_manifest_py upsert-harness "id=$HARNESS" "label=$LABEL" "mirror=$script" \
    "lane=$LANE" "lane_dir=$LANE_DIR" "cadence_s=$CALENDAR_CADENCE_S" "timeout_s=$TIMEOUT" \
    enabled=true tick=false "job_label=$LABEL" "at=$at" env_json='{}' "registered=$TODAY" >/dev/null
  sov_ensure_relay_job
  STAGING_MADE_HERE=0                    # the mover is up, or none is needed: the tree is carried
  say "[manifest] $HARNESS declared as a calendar lane: it keeps its own job ($LABEL, daily at $at), so $RUNNER_LABEL never ticks it"
  hour=$((10#${at%%:*})); min=$((10#${at##*:}))
  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    envxml="$envxml"$'\n\t\t<key>'"$k"$'</key>\n\t\t<string>'"$(_sov_xml "$v")"$'</string>'
  done
  if [ "$PLATFORM" = "Darwin" ]; then
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>$script</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>$hour</integer>
		<key>Minute</key>
		<integer>$min</integer>
	</dict>
	<key>RunAtLoad</key>
	<false/>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin</string>${envxml}
	</dict>
	<key>StandardOutPath</key>
	<string>$HOME/Library/Logs/$LABEL.log</string>
	<key>StandardErrorPath</key>
	<string>$HOME/Library/Logs/$LABEL.error.log</string>
</dict>
</plist>
EOF
    if [ "$NO_LAUNCHD" -eq 1 ]; then
      say "[launchd] $PLIST written, not loaded (--no-launchd). Load it from a Terminal on this Mac:"
      say "          launchctl bootstrap gui/\$(id -u) $PLIST"
    else
      _sov_launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
      # As loud as the tick path's refusal, and for the same reason: this job is the ONLY
      # thing that runs this lane -- the shared runner skips it by declaration -- so a
      # refusal that only prints leaves an installer reporting success over a lane that
      # will never mirror again. It names this lane, not "no lane on this Mac": the
      # machine's ticking lanes are untouched, and a sentence that says otherwise sends
      # the reader to the wrong job. --no-launchd is the deliberate way to write it
      # without loading it; a refusal is not that.
      if _sov_launchctl bootstrap "gui/$(id -u)" "$PLIST"; then
        say "[launchd] $LABEL daily at $at"
      else
        echo "[launchd] bootstrap of $LABEL failed (no GUI session here?). Nothing will run the $HARNESS lane on this Mac; load it from a Terminal here:" >&2
        echo "          launchctl bootstrap gui/\$(id -u) $PLIST" >&2
        exit 70
      fi
    fi
  else
    _sov_linger_note
    mkdir -p "$HOME/.config/systemd/user" "$STATE_DIR"
    {
      echo "[Unit]"; echo "Description=Sovereign connector: $HARNESS, daily at $at"; echo
      echo "[Service]"; echo "Type=oneshot"; echo "ExecStart=/bin/bash $script"
      echo "Environment=PATH=/usr/bin:/bin:/usr/local/bin"
      for kv in "$@"; do echo "Environment=$kv"; done
      echo "StandardOutput=append:$STATE_DIR/$LABEL.log"; echo "StandardError=append:$STATE_DIR/$LABEL.error.log"
    } > "$PLIST"
    {
      echo "[Unit]"; echo "Description=Sovereign connector: $HARNESS every day at $at"; echo
      echo "[Timer]"; echo "OnCalendar=*-*-* $at:00"; echo "Persistent=true"; echo "Unit=$LABEL.service"; echo
      echo "[Install]"; echo "WantedBy=timers.target"
    } > "${PLIST%.service}.timer"
    if [ "$NO_LAUNCHD" -eq 1 ]; then
      say "[systemd] $LABEL.timer written, not enabled (--no-launchd)"
      return 0
    fi
    _sov_systemctl --user daemon-reload
    if _sov_systemctl --user enable --now "$LABEL.timer" >/dev/null 2>&1; then
      say "[systemd] $LABEL.timer daily at $at (logs: $STATE_DIR)"
    else
      echo "[systemd] could not enable $LABEL.timer (no user manager, or no XDG_RUNTIME_DIR over ssh)" >&2
      exit 70
    fi
  fi
}

# Making a lane directory under a staging hop IS making the staging tree: mirror-common.sh
# sov_dest redirects every mirror on this machine into it the moment it exists. Only
# sov_ensure_staging may do that, and only once something is loaded to carry it, so a lane
# contract written before the lane's job exists is the same silent stall wearing a
# different shape. The tick path closes it by ordering (sov_register_connector, then the
# contract) and the calendar path by the same ordering; this makes the ordering checkable
# instead of remembered. It cannot fire on a machine off the staging path, where
# NEED_STAGING is 0 from sov_resolve onward.
sov_assert_staging_carried() {
  [ "${NEED_STAGING:-0}" = "1" ] || return 0
  echo "internal: $HARNESS would create $LANE_DIR before anything on this machine carries staging. Install the lane's job first, then write its contract." >&2
  exit 70
}

sov_lane_contract() {
  local tmpl="$1" readline="$2"
  sov_assert_staging_carried
  mkdir -p "$LANE_DIR"
  if [ -n "${GIT_LANE:-}" ]; then
    # the box's LANE.md is the owner's contract; record this harness beside it instead
    {
      echo "---"; echo "type: capture"; echo "source: $GIT_LANE"; echo "created: $TODAY"; echo "title: $HARNESS connector on $HOST"; echo "---"; echo
      echo "Connected $TODAY by \`sov connect $HARNESS\` on host $HOST, inside lane \`$GIT_LANE\`."
      echo "Read wire: $readline. Write wire: \`connectors/harness/$HARNESS/mirror.sh\` every ${INTERVAL}s"
      echo "via $SCHEDULER (\`$RUNNER_LABEL\`, lane id \`$LABEL\`), committed and pushed on the lane branch."
      echo "\`MANIFEST.md\` here is the heartbeat; \`brain-load-usage.md\` the read receipt."
    } > "$LANE_DIR/HARNESS.md"
    say "[lane] HARNESS.md written in $LANE_DIR (the box LANE.md stays the owner's)"
    return
  fi
  if [ -f "$LANE_DIR/LANE.md" ]; then
    cp "$LANE_DIR/LANE.md" "$LANE_DIR/.LANE.md.bak-$(date +%Y%m%d-%H%M%S)"
    /usr/bin/python3 - "$LANE_DIR/LANE.md" "$readline" "$HARNESS" "$TODAY" "$LABEL" "$INTERVAL" "$RUNNER_LABEL" "$SCHEDULER" <<'EOF'
import re, sys
p, readline, harness, today, label, interval, runner, scheduler = sys.argv[1:9]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r"(?m)^read:.*$", "read: " + readline, s, count=1)
# Nothing else re-renders a LANE.md, and these files live in the synced vault on every
# device: a contract that still names a per-tool job names a job that exists nowhere.
# One rule for every phrasing on disk, because three fixed ones missed three of eight:
# "every 900s via launchd\n(`L`)", "every 900s via a systemd user timer (`L`)", "every
# 900s via a scheduled job\n(`L`)", "every 900s via `L`," and "every 900s as `L`.".
#
# What makes it the WRITE-WIRE sentence, and not any sentence that happens to name the
# lane, is the cadence immediately in front of the connector word: prose that mentions
# the lane id in passing ("filed under `L`", "shows it as `L`") carries no "every Ns"
# there. So the cadence is required, the connector word has to follow it directly, and
# the label has to sit right there too -- either straight after the connector word
# ("every 900s via `L`"), or, when the job's kind is named in between, inside the
# brackets every shape on disk puts it in ("every 900s via a systemd user timer (`L`)").
# The bracket is what bounds the words in between: without it, one unpunctuated clause
# carrying a cadence, a preposition and the lane id ("ran every 900s under the old job
# and the console still lists it as `L`") is a whole owner-written sentence the patcher
# would rewrite. Nothing is consumed past the label either, or the space after it is
# eaten with it. The cadence itself is kept as it stands.
_lbl = "`" + re.escape(label) + "`"
job = re.compile(r"(?P<pre>every\s+\d+s\s+)(?:via|as|in|by|under)\s+"
                 r"(?:" + _lbl + r"|(?:[^.,;:!?`\n()]{1,40}?\s+)?\(\s*" + _lbl + r"\s*\))", re.I)
s2 = job.sub(lambda m: (m.group("pre") or "") + "via %s (`%s`, lane id `%s`)"
             % (scheduler, runner, label), s2)
marker = "sov connect " + harness
if marker not in s2:
    s2 = s2.rstrip() + ("\n\nRewired %s by `%s`: read wire `%s`; write wire "
        "`connectors/harness/%s/mirror.sh` every %ss via %s (`%s`, lane id `%s`). `MANIFEST.md` in the "
        "lane is the heartbeat; `brain-load-usage.md` is the read receipt.\n"
        % (today, marker, readline, harness, interval, scheduler, runner, label))
open(p, "w", encoding="utf-8").write(s2)
print("[lane] LANE.md patched (read: + write wire + note)")
EOF
  else
    sed -e "s|{{HOST}}|$HOST|g" -e "s|{{DATE}}|$TODAY|g" -e "s|{{INTERVAL}}|$INTERVAL|g" \
        -e "s|{{LABEL}}|$LABEL|g" -e "s|{{RUNNER}}|$RUNNER_LABEL|g" -e "s|{{SCHEDULER}}|$SCHEDULER|g" \
        -e "s|{{WRITE_VIA}}|$WRITE_VIA|g" -e "s|{{READ}}|$readline|g" \
        "$tmpl" > "$LANE_DIR/LANE.md"
    say "[lane] LANE.md written"
  fi
}

sov_smoke_mirror() {
  /bin/bash "$1"
  say "[smoke] mirror: $(grep -m1 'Last run' "$LANE_DIR/MANIFEST.md" 2>/dev/null || echo 'no manifest?')"
}

# Exercise the SHIPPED path, not just the mirror: a lane that only ever runs when a
# human calls mirror.sh directly is how one sat broken for 17 days behind 1074 exit-0
# runs. This tick is a smoke test and nothing more: it licenses no retirement, because
# it is evidence this installer produced itself. It is stamped so a later run knows that.
sov_smoke_runner() {
  local h="$1"
  /usr/bin/python3 "$RUNNER_BIN" --only "$h" || say "[smoke] runner: tick reported a problem; see $LANES_DIR/$h.error.log"
  say "[smoke] runner: $(grep -m1 'Last run' "$LANE_DIR/MANIFEST.md" 2>/dev/null || echo 'no manifest?')"
  _sov_mark_install_tick "$h"
}

sov_smoke_hook() {
  local hook="$1" style="$2" out
  out="$(cd "$VAULT" && CURSOR_PROJECT_DIR="$VAULT" printf '{"cwd":"%s","session_id":"install-smoke","source":"startup"}' "$VAULT" | /usr/bin/python3 "$hook")"
  if [ "$style" = "cursor" ]; then
    printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("additional_context",""); print("[smoke] hook ok: %d chars of context" % len(c) if c else "[smoke] hook produced no context")'
  else
    printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print("[smoke] hook ok:", d.get("systemMessage"))' || say "[smoke] hook produced no context (check ~/.brain-core and brain-load)"
  fi
}
