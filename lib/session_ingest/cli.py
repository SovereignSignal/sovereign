"""`sov ingest sessions`: the session-capture adapter beside `folder`.

bin/sov-ingest hands `sessions ...` to main() before its own argparse runs.

The owner's commands. Like `folder`, the default is a dry plan.

  sov ingest sessions [--tool claude-code] [--since 30d] [--json]
                    the plan for the next tick and the budget left; no model call, no write
  --show <id>       the cleaned excerpt the model would receive for one session
  --apply           run the shipped sessions.sh once now, under the lane's own lock;
                    refused while capture is off
  --on [--since D]  print the plan, then switch capture on from now (or from D ago: the
                    opt-in backfill); refused where no model may read a session
  --off             switch it off
  --allow <path>    read sessions that ran there (a temporary folder, say)
  --deny <path>     never read past that working folder; both store a realpath and drop
                    it from the other list, and deny wins at check time
  status [--json]   the switch, the distiller, the budget, this week's counts and the
                    projects seen in 30 days, for Settings
  --where <id>      the working folder a session ran in, for "Open session"

The internal flags connectors/harness/claude-code/sessions.sh drives on each tick:

  --gate            exit 3 when capture is off for the tool (the tick then stops,
                    silently), 0 when it is on; readiness is the tick's to check, so
                    a waiting reason reaches the lane's manifest
  --tick --dest D   one pass into the private stage folder D
  --commit-tick     merge the rows the tick staged, after a successful publish
  --discard-tick    drop them after a failed one, so every session retries
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import curator_inference

from . import READERS, inference, prefilter, privacy, run, state

TOOL = "claude-code"
EXIT_OFF = 3
EXIT_USAGE = 64
EXIT_CONFIG = 2
EXIT_REFUSED = 1
USAGE = """usage: sov ingest sessions [--tool claude-code] [--since 30d] [--json]
       sov ingest sessions --show <id> | --where <id>
       sov ingest sessions --apply
       sov ingest sessions --on [--since 30d] | --off
       sov ingest sessions --allow <path> | --deny <path>
       sov ingest sessions status [--json]
       (internal) sov ingest sessions --gate | --tick --dest <dir> | --commit-tick | --discard-tick"""
OFF_SENTENCE = ("Session capture is off. Turn it on with `sov ingest sessions --on` after looking at "
                "the preview.")
TEMPLATE = Path(__file__).resolve().parents[2]
# tool -> (the wire's id in connectors.json, the script the runner runs for it)
WIRES = {"claude-code": ("claude-code-sessions",
                         TEMPLATE / "connectors" / "harness" / "claude-code" / "sessions.sh")}
# The PATH the connector runner gives every wire, so a hand-run sees what a tick sees.
CHILD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
KILL_GRACE_S = 5
NEXT = ({"tool": "codex", "label": "Codex"},)
PROJECT_DAYS = 30
LOCAL_NAME = "Local model"
MAX_PATH = 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_SINCE = re.compile(r"^(\d{1,5})([hdw]?)$")
_UNIT_S = {"h": 3600, "d": 86400, "w": 7 * 86400}
VALUE_ACTIONS = ("--show", "--where", "--allow", "--deny")
FLAG_ACTIONS = ("--apply", "--on", "--off")


class _Usage(Exception):
    pass


def _usage(message=""):
    if message:
        sys.stderr.write("sov ingest sessions: %s\n" % message)
    sys.stderr.write(USAGE + "\n")
    return EXIT_USAGE


def _refuse(message):
    sys.stderr.write(message.rstrip() + "\n")
    return EXIT_REFUSED


def _iso(epoch, minutes=False):
    return time.strftime("%Y-%m-%dT%H:%MZ" if minutes else "%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))   # the day run.tick counts calls on


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _name(tool):
    return run.NAMES.get(tool, tool)


# ---------------------------------------------------------------- internal flags

def _no_args(args):
    if args:
        raise SystemExit(_usage())


def _gate(args, env):
    _no_args(args)
    return 0 if run.enabled(TOOL, env) else EXIT_OFF


def _tick(args, env):
    if len(args) != 2 or args[0] != "--dest" or not args[1]:
        return _usage()
    summary = run.tick(TOOL, env, args[1], time.time())
    if summary["status"] != "off":
        line = "sessions: %d call(s), %d capture(s), %d waiting" % (
            summary["calls"], summary["captures"], summary["pending"])
        if summary["reason"]:
            line += "; waiting: " + summary["reason"]
        print(line)
    return summary["exit"]


def _commit(args, env):
    _no_args(args)
    run.commit(TOOL, env)
    return 0


def _discard(args, env):
    _no_args(args)
    run.discard(TOOL, env)
    return 0


COMMANDS = {"--gate": _gate, "--tick": _tick, "--commit-tick": _commit, "--discard-tick": _discard}


# ---------------------------------------------------------------- parsing the owner's commands

def _since(text):
    m = _SINCE.match(text)
    if not m:
        raise _Usage("--since takes a span such as 30d, 12h or 2w")
    return int(m.group(1)) * _UNIT_S[m.group(2) or "d"]


def _parse(args):
    """{"action", "value", "tool", "since" (seconds or None), "json"}; raises _Usage."""
    opts = {"action": None, "value": None, "tool": TOOL, "since": None, "json": False}
    if args and args[0] == "status":
        opts["action"] = "status"
        args = args[1:]
    i = 0
    while i < len(args):
        name, value = args[i], None
        if name.startswith("--") and "=" in name:
            name, value = name.split("=", 1)
        if name in VALUE_ACTIONS + ("--tool", "--since"):
            if value is None:
                if i + 1 >= len(args):
                    raise _Usage("%s needs a value" % name)
                i += 1
                value = args[i]
            if not value:
                raise _Usage("%s needs a value" % name)
        elif name in FLAG_ACTIONS + ("--json",):
            if value is not None:
                raise _Usage("%s takes no value" % name)
        else:
            raise _Usage("unknown option: %s" % name)
        i += 1
        if name == "--tool":
            opts["tool"] = value
        elif name == "--since":
            opts["since"] = _since(value)
        elif name == "--json":
            opts["json"] = True
        else:
            if opts["action"] is not None:
                raise _Usage("one command at a time")
            opts["action"], opts["value"] = name, value
    action = opts["action"]
    if opts["tool"] not in READERS:
        raise _Usage("unknown tool: %s (session capture knows %s)" % (opts["tool"], ", ".join(sorted(READERS))))
    if opts["since"] is not None and action not in (None, "--on"):
        raise _Usage("--since goes with the plan or with --on")
    if opts["json"] and action not in (None, "status"):
        raise _Usage("--json goes with the plan or with status")
    if action in ("--show", "--where") and not _ID.match(opts["value"]):
        raise _Usage("%s takes a session id" % action)
    return opts


# ---------------------------------------------------------------- the plan

def _readiness(env, probe=False):
    """(resolved inference, ready, reason); never calls a model. On a hubless archive
    probe=True only checks that the provider's Keychain item exists (the plan and
    status, which Settings polls); without it the key is read, as --on and a tick do."""
    res = inference.resolve(env)
    ok, reason = inference.ready(res, probe=probe)
    return res, ok, reason


def _plan(tool, env, now, since, readiness):
    """What the next tick would look at, with no call and no write. `since` (epoch) is
    the floor a backfill would use."""
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    entry = cfg["tools"].get(tool) or {}
    rows = run.candidates(tool, env, now, since)
    used = state.Watermark(sd, tool).calls_today(_day(now))
    budget = cfg["budget"]
    res, ok, reason = readiness
    return {"tool": tool, "enabled": bool(entry.get("enabled")),
            "enabled_at": entry.get("enabled_at") if entry.get("enabled") else None,
            "since": _iso(since) if since is not None else None,
            "mode": res["mode"], "available": ok, "reason": reason, "distiller": res["distiller"],
            "candidates": rows,
            "budget": {"calls_per_tick": budget["calls_per_tick"], "calls_per_day": budget["calls_per_day"],
                       "chars_per_tick": budget["chars_per_tick"], "used_today": used,
                       "left_today": max(0, budget["calls_per_day"] - used)}}


def _age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return "%dm" % (seconds // 60)
    if seconds < 86400:
        return "%dh %dm" % (seconds // 3600, seconds % 3600 // 60)
    return "%dd %dh" % (seconds // 86400, seconds % 86400 // 3600)


def _dash(value):
    return "-" if value is None else str(value)


def _table(header, rows):
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    return ["  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in [header] + rows]


def _print_plan(plan, preview=False):
    if plan["enabled"]:
        print("Session capture for %s is on, from %s." % (_name(plan["tool"]), plan["enabled_at"]))
    else:
        print("Session capture for %s is off." % _name(plan["tool"]))
    if plan["available"]:
        print("Distiller: %s. Ready." % plan["distiller"])
    else:
        print("Distiller: not available. %s" % (plan["reason"] or "No model on this Mac."))
    if preview:
        print("With capture on, the next tick would look at these sessions. No model call was made.")
    else:
        print("This is a dry run: no model call, nothing written.")
    # A session that ended before the floor is never read, so it is a count, not a row.
    rows = [r for r in plan["candidates"] if r["verdict"] != "skipped:before-enable"]
    early = len(plan["candidates"]) - len(rows)
    print("")
    if rows:
        body = []
        for r in rows:
            distil = r["verdict"] is None
            # A read the privacy gate stopped holds no turns, so it has no counts to show.
            stopped = r["verdict"] in (privacy.REFUSED, privacy.DENIED)
            body.append([r["id"], _dash(r["project"]), _age(r["quiet_age_s"]),
                         "-" if stopped else _dash(r["prompts"]), "-" if stopped else _dash(r["score"]),
                         "would distil" if distil else r["verdict"],
                         r["excerpt_chars"] if distil else "-", r["est_tokens"] if distil else "-"])
        for line in _table(["SESSION", "PROJECT", "QUIET", "PROMPTS", "SCORE", "VERDICT", "EXCERPT", "TOKENS"],
                           body):
            print(line)
        print("")
    distil = sum(1 for r in rows if r["verdict"] is None)
    active = sum(1 for r in rows if r["verdict"] == "active")
    print("%d would be distilled, %d skipped, %d still being written." % (distil, len(rows) - distil - active,
                                                                         active))
    if early:
        line = "%s ended before capture was turned on and %s left alone." % (
            _plural(early, "session"), "is" if early == 1 else "are")
        if plan["since"] is None:
            line += " Preview a backfill with --since 30d."
        print(line)
    b = plan["budget"]
    print("Budget left: %s this tick, %d of %d today, %d characters a tick."
          % (_plural(b["calls_per_tick"], "call"), b["left_today"], b["calls_per_day"], b["chars_per_tick"]))


def _dry(opts, env):
    now = time.time()
    since = now - opts["since"] if opts["since"] is not None else None
    plan = _plan(opts["tool"], env, now, since, _readiness(env, probe=True))
    if opts["json"]:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        _print_plan(plan)
    return 0


# ---------------------------------------------------------------- one session

def _find(tool, env, sid):
    home = Path(env.get("HOME") or str(Path.home()))
    for path in READERS[tool].list_transcripts(home):
        if os.path.splitext(os.path.basename(path))[0] == sid:
            return path
    return None


def _not_found(tool, sid):
    return _refuse("No %s session with id %s on this Mac." % (_name(tool), sid))


def _show(opts, env):
    """The excerpt exactly as the tick would build it, through the same privacy gate."""
    tool, sid = opts["tool"], opts["value"]
    path = _find(tool, env, sid)
    if path is None:
        return _not_found(tool, sid)
    ctx = run.context(tool, env)
    s = ctx["reader"].scan(path, ctx["check"])
    if s["stopped"] == privacy.REFUSED:
        return _refuse("This session ran inside an archive, so it is never read or sent.")
    if s["stopped"]:
        return _refuse("This session ran in a folder session capture leaves alone (denied, or temporary "
                       "and not allowed), so it is not read.")
    verdict, _, hits = prefilter.check(s, ctx["cfg"], ctx["floor"], ctx["stems"])
    text, _ = run.excerpt_text(s, hits)
    if verdict is not None:
        sys.stderr.write("The next tick would not send this session (%s). This is what it would send if "
                         "it did.\n" % verdict)
    sys.stdout.write(text.rstrip("\n") + "\n")
    return 0


def _where(opts, env):
    tool, sid = opts["tool"], opts["value"]
    row = state.Watermark(state.state_dir(env), tool).rows.get(sid) or {}
    cwd = row.get("cwd") if isinstance(row.get("cwd"), str) else None
    if not cwd:
        path = _find(tool, env, sid)
        cwd = READERS[tool].first_cwd(path) if path else None
    if not cwd:
        return _not_found(tool, sid)
    print(cwd)
    return 0


# ---------------------------------------------------------------- --apply

def _wire_entry(env, sd, wire):
    """The wire's entry in connectors.json (where the runner reads it), or {} when it is
    not declared or the file cannot be read."""
    path = Path(os.path.expanduser(env.get("SOV_MANIFEST") or str(Path(sd) / "connectors.json")))
    try:
        entry = (json.loads(path.read_text(encoding="utf-8")).get("harnesses") or {}).get(wire)
    except (OSError, ValueError, AttributeError):
        return {}
    return entry if isinstance(entry, dict) else {}


def _take_lock(lock, stale_after_s):
    """The connector runner's own lane lock, a directory: True when this run now holds
    it. One older than stale_after_s was left by a dead run and is taken over, as the
    runner does."""
    try:
        os.mkdir(str(lock))
        return True
    except FileExistsError:
        pass
    try:
        if time.time() - os.path.getmtime(str(lock)) < stale_after_s:
            return False
        os.rmdir(str(lock))
        os.mkdir(str(lock))
        return True
    except OSError:
        return False


def _stop(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=KILL_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            continue


def _apply(opts, env):
    """One pass now, as the runner would run it: the wire's env and bound from
    connectors.json, the runner's PATH, and the lane lock, so a hand-run never overlaps
    a scheduled tick on the same watermark."""
    tool = opts["tool"]
    if not run.enabled(tool, env):
        return _refuse(OFF_SENTENCE)
    wire, script = WIRES[tool]
    sd = state.state_dir(env)
    entry = _wire_entry(env, sd, wire)
    child = dict(env)
    child.update({str(k): str(v) for k, v in (entry.get("env") or {}).items()})
    try:
        bound = int(entry.get("timeout_s") or child.get(run.BOUND_ENV) or run.DEFAULT_BOUND_S)
    except (TypeError, ValueError):
        bound = run.DEFAULT_BOUND_S
    bound = min(max(bound, 1), run.DEFAULT_BOUND_S)
    child.update({run.BOUND_ENV: str(bound), "PATH": CHILD_PATH})
    lanes = sd / "lanes"
    lanes.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = lanes / ("%s.lock" % wire)
    if not _take_lock(lock, 2 * bound):
        return _refuse("A session capture tick is running now. Try again when it ends.")
    try:
        proc = subprocess.Popen(["/bin/bash", str(script)], env=child, start_new_session=True)
        try:
            return proc.wait(timeout=bound)
        except subprocess.TimeoutExpired:
            _stop(proc)
            return _refuse("The pass was still running after %ds and was stopped, as a tick would be. "
                           "What it did not reach waits for the next tick." % bound)
        except KeyboardInterrupt:
            _stop(proc)
            return _refuse("Stopped. What this pass did not finish waits for the next tick.")
    finally:
        try:
            os.rmdir(str(lock))
        except OSError:
            pass


# ---------------------------------------------------------------- the switch and the lists

def _on(opts, env):
    tool = opts["tool"]
    now = time.time()
    readiness = _readiness(env)
    res, ok, reason = readiness
    if res["mode"] == "client" or not ok:
        return _refuse("Session capture stays off: %s" % (reason or res.get("reason") or "no model on this Mac."))
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    entry = dict(cfg["tools"].get(tool) or {})
    # The floor is where reading starts. From off it resets to now, so sessions from a
    # window when capture was off are not captured; while on, --on again keeps it where
    # it is. --since moves it back in either case.
    current = prefilter.epoch(entry.get("enabled_at")) if entry.get("enabled") else None
    floor = now if current is None else current
    if opts["since"] is not None:
        floor = min(floor, now - opts["since"])
    _print_plan(_plan(tool, env, now, floor, readiness), preview=True)
    entry.update(enabled=True, enabled_at=_iso(floor))
    cfg["tools"][tool] = entry
    state.save_config(sd, cfg)
    b = cfg["budget"]
    print("")
    print("Session capture is on for %s. Sessions active after %s are distilled from the next tick, "
          "up to %d a tick and %d a day, oldest first."
          % (_name(tool), _iso(floor, True), b["calls_per_tick"], b["calls_per_day"]))
    return 0


def _off(opts, env):
    tool = opts["tool"]
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    entry = dict(cfg["tools"].get(tool) or {})
    if not entry.get("enabled"):
        print("Session capture is already off for %s." % _name(tool))
        return 0
    entry["enabled"] = False
    cfg["tools"][tool] = entry
    state.save_config(sd, cfg)
    print("Session capture is off for %s. Nothing more is read; what already landed stays in its lane."
          % _name(tool))
    return 0


def _norm(path):
    return os.path.realpath(os.path.expanduser(str(path))).rstrip("/") or "/"


def _under(p, x):
    return x == "/" or p == x or p.startswith(x + "/")


def _set_list(opts, env, key):
    raw = opts["value"]
    if len(raw) > MAX_PATH or "\n" in raw or "\x00" in raw:
        raise ValueError("That path is not one session capture can store.")
    path = _norm(raw)
    other = "deny" if key == "allow" else "allow"
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    cfg[key] = [p for p in cfg[key] if _norm(p) != path] + [path]
    cfg[other] = [p for p in cfg[other] if _norm(p) != path]
    state.save_config(sd, cfg)
    if key == "allow":
        print("Allowed %s. Sessions that ran there are read from the next tick." % path)
        if privacy.make_cwd_check(run.vault_root(env), {})(path) == privacy.REFUSED:
            print("It is inside an archive, so sessions there stay refused.")
    else:
        print("Denied %s. Sessions that ran there are not read past their working folder." % path)
    return 0


def _allow(opts, env):
    return _set_list(opts, env, "allow")


def _deny(opts, env):
    return _set_list(opts, env, "deny")


# ---------------------------------------------------------------- status

def _distiller(res, sd):
    cfg = res.get("cfg")
    if cfg is not None:
        provider = cfg.get("provider") or ""
        if provider:
            return {"provider": provider, "model": cfg["model"],
                    "name": curator_inference.PROVIDERS[provider]["name"]}
        return {"provider": "local", "model": cfg["model"], "name": LOCAL_NAME}
    if res["mode"] == "hubless":   # a provider with no fixed host: named, never called
        provider = curator_inference.chosen_provider(str(sd))
        spec = curator_inference.PROVIDERS[provider]
        return {"provider": provider, "model": spec["model"], "name": spec["name"]}
    return {"provider": "", "model": "", "name": ""}


def _projects(tool, env, cfg, rows, now):
    """Every working folder a session ran in over the last 30 days, with its count and
    what the privacy gate does with it. A committed row's cwd is used as it is; a file
    with no such row (or a row skipped before enable, which carries none) is read only
    up to its first cwd."""
    reader = READERS[tool]
    home = Path(env.get("HOME") or str(Path.home()))
    vault = run.vault_root(env)
    gate = privacy.make_cwd_check(vault, cfg)
    bare = privacy.make_cwd_check(vault, {})   # archives and temporary roots only
    deny = [_norm(x) for x in cfg.get("deny", [])]
    counts = {}
    for path in reader.list_transcripts(home):
        try:
            if os.stat(path).st_mtime < now - PROJECT_DAYS * 86400:
                continue
            row = rows.get(os.path.splitext(os.path.basename(path))[0]) or {}
            cwd = row.get("cwd") if isinstance(row.get("cwd"), str) and row.get("cwd") else None
            cwd = cwd or reader.first_cwd(path)
        except OSError:
            continue
        if cwd:
            counts[cwd] = counts.get(cwd, 0) + 1
    out = []
    for cwd, n in counts.items():
        base = bare(cwd)
        kind = "archive" if base == privacy.REFUSED else "temp" if base == privacy.DENIED else "normal"
        out.append({"path": cwd, "label": os.path.basename(cwd.rstrip("/")) or cwd, "sessions": n,
                    "on": gate(cwd) is None, "kind": kind, "denied": any(_under(_norm(cwd), x) for x in deny)})
    out.sort(key=lambda r: (-r["sessions"], r["path"]))
    return out


def _status_doc(tool, env, now):
    """(the status document Settings reads, enabled_at or None)."""
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    entry = cfg["tools"].get(tool) or {}
    enabled = bool(entry.get("enabled"))
    res, ok, reason = _readiness(env, probe=True)
    wm = state.Watermark(sd, tool)
    counts = run.week_counts(wm, now)
    # Waiting: sessions the next tick would send, the same notion as the manifest's count.
    waiting = sum(1 for r in run.candidates(tool, env, now, with_excerpt=False) if r["verdict"] is None)
    budget = cfg["budget"]
    doc = {"tool": tool, "enabled": enabled, "available": ok, "mode": res["mode"], "reason": reason,
           "distiller": _distiller(res, sd),
           "budget": {"calls_per_tick": budget["calls_per_tick"], "calls_per_day": budget["calls_per_day"],
                      "chars_per_tick": budget["chars_per_tick"], "used_today": wm.calls_today(_day(now))},
           "week": {"distilled": counts["distilled"], "captures": counts["captures"],
                    "skipped": counts["skipped"], "waiting": waiting, "failed": counts["failed"],
                    "refused": counts["refused"]},
           "waiting": wm.waiting if enabled else None,
           "projects": _projects(tool, env, cfg, wm.rows, now),
           "next": [dict(n) for n in NEXT]}
    return doc, (entry.get("enabled_at") if enabled else None)


def _status(opts, env):
    doc, enabled_at = _status_doc(opts["tool"], env, time.time())
    if opts["json"]:
        print(json.dumps(doc, indent=2, sort_keys=True))
        return 0
    print("Session capture for %s is %s." % (_name(doc["tool"]),
                                             "on, from %s" % enabled_at if doc["enabled"] else "off"))
    d = doc["distiller"]
    if doc["available"]:
        print("Distiller: %s (%s/%s). Ready." % (d["name"], d["provider"], d["model"]))
    else:
        print("Distiller: not available. %s" % (doc["reason"] or "No model on this Mac."))
    b = doc["budget"]
    print("Budget: up to %d sessions a tick and %d a day, %d characters a tick; %s used today."
          % (b["calls_per_tick"], b["calls_per_day"], b["chars_per_tick"], _plural(b["used_today"], "call")))
    w = doc["week"]
    print("This week: distilled %d, captures %d, skipped %d, waiting %d, failed %d, refused %d."
          % (w["distilled"], w["captures"], w["skipped"], w["waiting"], w["failed"], w["refused"]))
    if doc["waiting"]:
        print("Waiting: %s since %s." % (doc["waiting"].get("reason"), doc["waiting"].get("since")))
    if doc["projects"]:
        print("Projects in the last %d days:" % PROJECT_DAYS)
        body = []
        for p in doc["projects"]:
            note = "denied" if p["denied"] else {"archive": "inside an archive: never",
                                                 "temp": "temporary"}.get(p["kind"], "")
            body.append(["on" if p["on"] else "off", p["label"], _plural(p["sessions"], "session"), p["path"],
                         note])
        for line in _table(["", "", "", "", ""], body)[1:]:
            print(line)
    print("Next: %s." % ", ".join(n["label"] for n in doc["next"]))
    return 0


OWNER = {None: _dry, "status": _status, "--show": _show, "--where": _where, "--apply": _apply, "--on": _on,
         "--off": _off, "--allow": _allow, "--deny": _deny}


def main(argv, env=None):
    env = os.environ if env is None else env
    argv = list(argv)
    try:
        if argv and argv[0] in COMMANDS:
            return COMMANDS[argv[0]](argv[1:], env)
        try:
            opts = _parse(argv)
        except _Usage as exc:
            return _usage(str(exc))
        return OWNER[opts["action"]](opts, env)
    except (ValueError, OSError) as exc:
        sys.stderr.write("sov ingest sessions: %s\n" % exc)
        return EXIT_CONFIG
