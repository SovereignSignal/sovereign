"""One session-capture tick: quiet sessions in, candidate captures staged into the lane.

A tick walks one harness's transcripts oldest-quiet first. Each is checked in the order
the watermark needs (quiet, then the size seen this tick, then whether its verdict
deserves another look), read through the privacy gate, pre-filtered without a model,
and only then excerpted, cleaned and sent to the archive's own model, within a budget
of calls and characters per tick and calls per day. Every candidate that survives
validation is handed to sov-capture, which owns the frontmatter, the redaction pass,
the path fence and the never-overwrite rule, writing into the private stage that
sessions.sh publishes. Verdicts are staged; sessions.sh commits them once the publish
succeeded, or discards them so every session retries. Calls are counted the moment
they are made, so a discarded tick still spends its budget.

candidates() is the same walk with no call and no write: the dry plan.
"""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import curator_inference
import sovereign_config

from . import READERS, distill, excerpt, inference, prefilter, privacy, prompt, state

CAPTURE = Path(__file__).resolve().parents[2] / "bin" / "sov-capture"
NAMES = {"claude-code": "Claude Code"}
# The connector runner kills a lane at its timeout_s: 300 s, or the machine's tick when
# that is shorter, which reaches the tick as BOUND_ENV. A session call is one attempt
# (no in-call retry: a held timeout is retried by a later tick) of at most half the bound,
# capped at CALL_TIMEOUT_S, and windows() starts no call later than one full call plus
# CALL_MARGIN_S before the bound, which leaves that margin for the gate, the publish and
# the commit; the walk stops at 80%. What a tick did not reach waits for the next one.
BOUND_ENV = "SOV_WIRE_TIMEOUT_S"
DEFAULT_BOUND_S = 300
CALL_TIMEOUT_S = 150
CALL_MARGIN_S = 30
CAPTURE_TIMEOUT_S = 60
WEEK_S = 7 * 86400
UNREACHABLE = "model unreachable"
# On a hub the tick shares the one local model slot with curator-run and the weekly
# audit, which serialise on the model lock; a tick that finds it held makes no call.
BUSY = "model busy"
MAX_TIMEOUTS = 3
AUTH_CODES = (401, 403)
# The Waiting line is published into the lane, so it carries one of these phrases and
# never the reason itself, which can name a path, a host or an endpoint. The full
# reason stays in the watermark for `status`.
WAITING_PHRASES = ("model unreachable", "model refused this configuration",
                   "no key saved for the curator's provider", "session capture needs the hub's model",
                   "capture is not ready", BUSY)
OFF_REASON = "Session capture is off."
_KEBAB = re.compile(r"[^a-z0-9]+")
_DISTILLER_PROVIDER = re.compile(r"[^a-z0-9.-]+")
_DISTILLER_MODEL = re.compile(r"[^A-Za-z0-9._:-]+")


def _iso(epoch, minutes=False):
    return time.strftime("%Y-%m-%dT%H:%MZ" if minutes else "%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _one_line(value, limit):
    return " ".join(str(value or "").split())[:limit].strip()


def _kebab(text):
    return _KEBAB.sub("-", str(text).lower()).strip("-")


def _host(env):
    host = sovereign_config.pointer("~/.brain-host", env)
    return host or socket.gethostname().split(".")[0].lower()


def vault_root(env):
    root = sovereign_config.pointer("~/.brain-root", env)
    if not root:
        return None
    root = os.path.realpath(os.path.expanduser(root))
    return root if os.path.isdir(root) else None


def _project(s):
    cwds = s.get("cwds") or []
    return _one_line(os.path.basename(cwds[0].rstrip("/")), 200) if cwds else ""


def _span(s):
    a, b = prefilter.epoch(s.get("first_ts")), prefilter.epoch(s.get("last_ts"))
    return "%s..%s" % (_iso(a, True), _iso(b, True)) if a is not None and b is not None else ""


def _distiller(name):
    """The distiller label in the shape sov-capture accepts: <provider>/<model>."""
    provider, _, model = str(name or "").partition("/")
    provider = _DISTILLER_PROVIDER.sub("-", provider.lower()).strip("-") or "local"
    model = _DISTILLER_MODEL.sub("-", model).strip("-")
    return "%s/%s" % (provider, model) if model else ""


def _failures(row):
    verdict = (row or {}).get("verdict") or ""
    if verdict.startswith("failed:"):
        try:
            return int(verdict.split(":", 1)[1])
        except ValueError:
            return 0
    return 0


def context(tool, env, since=None):
    if tool not in READERS:
        raise ValueError("Unknown tool: %s." % tool)
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    entry = cfg["tools"].get(tool) or {}
    floor = prefilter.epoch(entry.get("enabled_at")) if entry.get("enabled") else None
    if since is not None:
        floor = since if floor is None else min(floor, since)
    vault = vault_root(env)
    return {"tool": tool, "reader": READERS[tool], "state_dir": sd, "cfg": cfg,
            "enabled": bool(entry.get("enabled")), "floor": floor, "vault": vault,
            "home": Path(env.get("HOME") or str(Path.home())),
            "check": privacy.make_cwd_check(vault, cfg), "policy": privacy.policy_hash(cfg),
            "stems": prefilter.card_stems(vault) if vault else set()}


def _walk(ctx, rows, now, observe=None, deadline=None):
    """Yield one look per transcript, oldest first: {"sid", "size", "mtime", "active"}
    for a session still being written, else that plus the scan and the pre-filter's
    (verdict, score, hits). Sessions whose verdict stands are not yielded."""
    found = []
    for path in ctx["reader"].list_transcripts(ctx["home"]):
        try:
            st = os.stat(path)
        except OSError:
            continue
        # The watermark id is the file's own name, which is also what `claude --resume`
        # takes; a resumed file can open with an earlier session's sessionId.
        sid = os.path.splitext(os.path.basename(path))[0]
        # A session holding an unresolved timeout goes last, so the next call goes to
        # another session when there is one.
        held = bool((rows.get(sid) or {}).get("held_timeout"))
        found.append((held, st.st_mtime, path, st.st_size, sid))
    found.sort()
    for _, mtime, path, size, sid in found:
        if deadline is not None and time.monotonic() >= deadline:
            return
        row = rows.get(sid)
        quiet = prefilter.quiet(size, mtime, row, now, ctx["cfg"]["quiet_min"])
        seen = (row or {}).get("seen") or {}
        if observe is not None and (seen.get("size") != size or seen.get("mtime") != mtime):
            observe(sid, size, mtime)
            row = rows.get(sid)
        look = {"sid": sid, "path": path, "size": size, "mtime": mtime, "row": row, "active": not quiet}
        if not quiet:
            yield look
            continue
        if not state.needs_look(row, size, ctx["policy"]):
            continue
        if ctx["floor"] is None or mtime <= ctx["floor"]:
            # Nothing was written after capture was enabled (or it never was), so nothing
            # in the file is read: prefilter.check would give this verdict after a full scan.
            look.update(scan=None, verdict="skipped:before-enable", score=0, hits=frozenset())
            yield look
            continue
        try:
            s = ctx["reader"].scan(path, ctx["check"])
        except OSError:
            continue
        verdict, score, hits = prefilter.check(s, ctx["cfg"], ctx["floor"], ctx["stems"])
        look.update(scan=s, verdict=verdict, score=score, hits=hits)
        yield look


def excerpt_text(s, hits):
    text, turn_ids = excerpt.build(s["turns"], hits)
    text, _ = excerpt.clean(text)
    return text, turn_ids


def enabled(tool, env):
    """Whether the owner has turned session capture on for `tool`. Raises ValueError on
    a config that cannot be read."""
    return context(tool, env)["enabled"]


def candidates(tool, env, now, since=None, with_excerpt=True):
    """The dry plan: one row per transcript the next tick would look at, with no model
    call and no write. `since` (epoch seconds) lowers the enable floor for a backfill.
    With with_excerpt=False no excerpt is built, so excerpt_chars and est_tokens stay 0:
    for status, which only counts."""
    ctx = context(tool, env, since)
    wm = state.Watermark(ctx["state_dir"], tool)
    out = []
    for look in _walk(ctx, wm.rows, now):
        row = {"id": look["sid"], "project": None, "quiet_age_s": int(now - look["mtime"]), "prompts": None,
               "score": None, "verdict": "active" if look["active"] else look["verdict"],
               "excerpt_chars": 0, "est_tokens": 0}
        s = look.get("scan")
        if s is not None:
            row.update(project=_project(s) or None, prompts=len(s["turns"]), score=look["score"])
            if look["verdict"] is None and with_excerpt:
                text, _ = excerpt_text(s, look["hits"])
                row.update(excerpt_chars=len(text), est_tokens=len(text) // 4)
        out.append(row)
    return out


def _lane_paths(ctx, env, dest_dir):
    lane = "%s-%s" % (ctx["reader"].LANE_PREFIX, _host(env))
    dest = Path(os.path.abspath(str(dest_dir)))
    stage = dest.parents[3] if len(dest.parents) > 3 else None
    if stage is None or dest != stage / "raw" / "tools" / lane / "sessions":
        raise ValueError("--dest must be <stage>/raw/tools/%s/sessions." % lane)
    if not dest.is_dir():
        raise ValueError("--dest %s is not a folder." % dest)
    return lane, stage, dest


def windows(bound_s):
    """(call timeout, no-new-call window, walk window) in seconds for a tick the runner
    bounds at bound_s: (150, 120, 240) at 300. The call is min(150, bound // 2) and the
    window is bound - call - 30, so a call started at the end of the window still ends
    30 s before the bound."""
    call = min(CALL_TIMEOUT_S, bound_s // 2)
    window = max(0, bound_s - call - CALL_MARGIN_S)
    shape = lambda x: int(x) if float(x).is_integer() else x  # noqa: E731
    return shape(call), shape(window), shape(bound_s * 0.8)


def _bound(env):
    try:
        bound = int(env.get(BOUND_ENV) or DEFAULT_BOUND_S)
    except ValueError:
        bound = DEFAULT_BOUND_S
    return min(max(bound, 1), DEFAULT_BOUND_S)


def waiting_phrase(reason):
    """The fixed phrase the published Waiting line uses for a waiting reason."""
    reason = str(reason or "")
    if reason == UNREACHABLE:
        return WAITING_PHRASES[0]
    if reason == BUSY:
        return BUSY
    if (reason.startswith(distill.REFUSING) or reason == inference.GUARD_REASON
            or reason.startswith(tuple("HTTP %d" % c for c in AUTH_CODES))):
        return WAITING_PHRASES[1]
    if reason.startswith("No key is saved for"):
        return WAITING_PHRASES[2]
    if reason == inference.CLIENT_REASON:
        return WAITING_PHRASES[3]
    return WAITING_PHRASES[4]


def _capture(c, s, sid, tool, lane, stage, vault, distiller, env):
    """Hand one validated candidate to sov-capture: "ok" when it was written, "refused"
    when sov-capture ran and declined it (a fence or label refusal, or a body it will not
    take), "fault" when sov-capture could not be run at all."""
    slug = "%s-%s" % (_kebab(c["title"])[:50].strip("-") or "capture", _kebab(sid)[:8].strip("-") or "session")
    meta = []
    for key, value in (("session_title", _one_line(s.get("title"), 200)), ("project", _project(s)),
                       ("span", _span(s)), ("distiller", _distiller(distiller)), ("prompt", prompt.VERSION),
                       ("kind", c["kind"]), ("confidence", c["confidence"]),
                       ("evidence", ",".join(c["evidence"]))):
        if value:
            meta.append("--meta=%s=%s" % (key, value))
    argv = [sys.executable, str(CAPTURE), slug, "--lane", lane, "--subdir", "sessions", "--from", "-",
            "--title=" + c["title"], "--origin=%s-session:%s" % (tool, sid)] + meta
    child = dict(env)
    child.pop("SOVEREIGN_STAGE", None)
    child.update(BRAIN_STAGE=str(stage), BRAIN_ROOT=vault, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run(argv, input=c["body"], capture_output=True, text=True, env=child,
                              timeout=CAPTURE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write("sessions: capture for %s did not run: %s\n" % (sid, exc))
        return "fault"
    if done.returncode != 0:
        if "Traceback (most recent call last)" in done.stderr or (
                done.returncode == 2 and "can't open file" in done.stderr):
            # sov-capture crashed or is not there: a broken install, never this session's fault
            last = (done.stderr.strip().splitlines() or [""])[-1][:300]
            sys.stderr.write("sessions: sov-capture failed to run for %s (exit %d): %s\n"
                             % (sid, done.returncode, last))
            return "fault"
        sys.stderr.write("sessions: capture for %s was refused (exit %d): %s\n"
                         % (sid, done.returncode, done.stderr.strip()[:300]))
        return "refused"
    return "ok"


def _take_back(dest, before):
    """Remove what one session's captures added to dest this tick."""
    for name in sorted(set(os.listdir(str(dest))) - before):
        path = os.path.join(str(dest), name)
        if os.path.isfile(path) or os.path.islink(path):
            os.unlink(path)


def _waiting(prior, reason, now):
    """{"reason", "since"}, keeping the prior since while the reason is unchanged."""
    if prior and prior.get("reason") == reason and prior.get("since"):
        return {"reason": reason, "since": prior["since"]}
    return {"reason": reason, "since": _iso(now)}


def tick(tool, env, dest_dir, now):
    """One pass. Returns {"tool", "status": "off"|"waiting"|"ran", "reason", "calls",
    "captures", "pending", "verdicts": {id: verdict}, "exit"}; exit is 1 only when a
    sov-capture could not be run. Writes sessions/MANIFEST.md into dest_dir unless off."""
    started = time.monotonic()
    call_timeout, call_window, walk_window = windows(_bound(env))
    ctx = context(tool, env)
    summary = {"tool": tool, "status": "off", "reason": OFF_REASON, "calls": 0, "captures": 0, "pending": 0,
               "verdicts": {}, "exit": 0}
    if not ctx["enabled"]:
        return summary
    if not ctx["vault"]:
        raise ValueError("No archive on this Mac (set ~/.brain-root).")
    lane, stage, dest = _lane_paths(ctx, env, dest_dir)
    if not CAPTURE.is_file():
        # Every capture would fail: no call is worth making and no session is at fault.
        sys.stderr.write("sessions: sov-capture is missing (%s); no call made\n" % CAPTURE)
        summary.update(status="fault", reason="sov-capture is missing", exit=1)
        return summary
    host = _host(env)
    wm = state.Watermark(ctx["state_dir"], tool)
    # Rows still staged at the start of a tick belong to a run that never reached its
    # publish (the runner killed it): their captures were never carried, so they go.
    wm.discard()
    prior = wm.waiting
    res = inference.resolve(env)
    ok, reason = inference.ready(res)
    if not ok:
        wm.stage_waiting(_waiting(prior, reason, now))
        summary.update(status="waiting", reason=reason)
        write_manifest(dest, lane, wm, now, host=host, tool=tool)
        return summary
    lock = None
    if res["mode"] == "hub":
        # The hub's one local model slot: take curator-run's lock without waiting, or make
        # no call this tick and stage nothing but the Waiting line.
        lock = curator_inference.open_model_lock(str(ctx["home"]))
        try:
            curator_inference.hold_model_lock(lock, "session-capture")
        except OSError:
            lock.close()
            wm.stage_waiting(_waiting(prior, BUSY, now))
            summary.update(status="waiting", reason=BUSY)
            write_manifest(dest, lane, wm, now, host=host, tool=tool)
            return summary
    try:
        key = inference.key(res)
        summary.update(status="ran", reason="")
        budget = ctx["cfg"]["budget"]
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        # Only a call's outcome changes a waiting set by a call: an answer clears it, an
        # outage or a 401/403 sets it, and a tick that ends on a held timeout leaves it be.
        from_call = (UNREACHABLE, distill.REFUSING) + tuple("HTTP %d" % c for c in AUTH_CODES)
        waiting = prior if prior and str(prior.get("reason") or "").startswith(from_call) else None
        calls_open, chars, failed_writes, faults = True, 0, 0, 0
        # A timeout is not proof of an outage, and one timed-out call uses up a tick, so it is
        # held in the session's row (held_timeout) across ticks until the next call, on any
        # session, says whether the model is working. An answer charges every hold (three
        # timeouts end a session); a timeout or no answer drops every hold, uncharged.
        holds = {k: v for k, v in wm.rows.items() if isinstance(v, dict) and v.get("held_timeout")}
        resolved = set()

        def release(charge):
            """Resolve every held timeout, charged or dropped; returns {sid: new timeouts}."""
            counts = {}
            for hsid, hrow in holds.items():
                nrow = {k: v for k, v in hrow.items() if k not in ("held_timeout", "seen")}
                if charge:
                    nrow["timeouts"] = int(nrow.get("timeouts") or 0) + 1
                    if nrow["timeouts"] >= MAX_TIMEOUTS:
                        nrow.update(verdict="failed:%d" % MAX_TIMEOUTS, at=_iso(now),
                                    error="timed out %d times" % nrow["timeouts"])
                        summary["verdicts"][hsid] = nrow["verdict"]
                counts[hsid] = int(nrow.get("timeouts") or 0)
                wm.stage(hsid, nrow, write=False)
                resolved.add(hsid)
            holds.clear()
            return counts

        for look in _walk(ctx, wm.rows, now, observe=lambda *a: wm.observe(*a, write=False),
                          deadline=started + walk_window):
            if look["active"]:
                continue
            sid, s, row = look["sid"], look["scan"], look["row"]
            cwds = (s or {}).get("cwds") or []
            verdict_row = {"size": look["size"], "mtime": look["mtime"], "policy": ctx["policy"],
                           "cwd": cwds[0] if cwds else None, "project": _project(s) if s else "", "at": _iso(now),
                           "attempts": int((row or {}).get("attempts") or 0), "captures": 0,
                           "timeouts": int((row or {}).get("timeouts") or 0),
                           "distiller": res["distiller"], "prompt": prompt.VERSION}
            if look["verdict"] is not None:
                wm.stage(sid, dict(verdict_row, verdict=look["verdict"]), write=False)
                summary["verdicts"][sid] = look["verdict"]
                continue
            if sid in resolved:
                summary["pending"] += 1   # its hold was resolved by this tick's answer: next tick
                continue
            if (not calls_open or summary["calls"] >= budget["calls_per_tick"]
                    or wm.calls_today(day) >= budget["calls_per_day"]
                    or time.monotonic() - started >= call_window):
                summary["pending"] += 1
                continue
            text, turn_ids = excerpt_text(s, look["hits"])
            if chars + len(text) > budget["chars_per_tick"]:
                summary["pending"] += 1
                continue
            wm.write_seen()       # the sizes seen so far survive whatever this call does
            wm.record_call(day)
            summary["calls"] += 1
            chars += len(text)
            out = distill.distill(res, key, s, text, turn_ids, timeout=call_timeout)
            verdict_row["attempts"] += 1
            answered = out["status"] in ("ok", "failed") or out.get("responded")
            if answered:
                own = sid in holds
                charged = release(charge=True)   # the model is working: every held timeout stands
                if own:
                    verdict_row["timeouts"] = charged[sid]
            if out["status"] == "ok":
                waiting = None
                before = set(os.listdir(str(dest)))
                results = []
                for c in out["captures"]:
                    results.append(_capture(c, s, sid, tool, lane, stage, ctx["vault"], res["distiller"], env))
                    if results[-1] != "ok":
                        break
                if results.count("ok") != len(out["captures"]):
                    # One session's refused capture costs that session alone: what it wrote this
                    # tick is taken back and it counts a failed attempt (three end it), so the
                    # rest of the tick still publishes. Only a sov-capture that cannot run at
                    # all fails the tick.
                    _take_back(dest, before)
                    failed_writes += len(out["captures"])
                    if "fault" in results:
                        faults += 1
                        calls_open = False    # every later capture would fail the same way
                        summary["pending"] += 1
                        continue
                    verdict = "failed:%d" % (_failures(row) + 1)
                    wm.stage(sid, dict(verdict_row, verdict=verdict), write=False)
                    summary["verdicts"][sid] = verdict
                    continue
                summary["captures"] += len(out["captures"])
                verdict = "distilled"
                wm.stage(sid, dict(verdict_row, verdict=verdict, captures=len(out["captures"])), write=False)
            elif out["status"] == "failed" or out.get("responded"):
                # An unparseable reply, or an HTTP error the model host answered with: either
                # way the model saw this excerpt and rejected it. It counts against this
                # session alone (three end it) and the tick goes on to the next one.
                waiting = None
                verdict = "failed:%d" % (_failures(row) + 1)
                wm.stage(sid, dict(verdict_row, verdict=verdict), write=False)
            elif out["status"] == "unreachable" and out.get("timed_out") and not holds:
                # The first timeout with none held: hold it in the row, charge nothing, leave
                # waiting as it was, and make no further call this tick (a timed-out call leaves
                # no time for another).
                wm.stage(sid, dict(verdict_row, verdict=(row or {}).get("verdict") or None,
                                   held_timeout={"at": _iso(now)}), write=False)
                calls_open = False
                summary["pending"] += 1
                continue
            else:
                # A timeout while one is held, no answer at all, or a 404, 408, 429 or 5xx: an
                # outage, never counted against a session, which stays pending for as long as
                # it lasts, and every held timeout is dropped uncharged. 401 or 403, or a guard
                # refusal at call time: a configuration the owner must see, holds dropped the
                # same way. Either way this tick makes no further call.
                release(charge=False)
                if out["status"] == "refused":
                    reason = _one_line(out["error"], 300) or "refused"
                elif out.get("code") in AUTH_CODES:
                    reason = _one_line(out["error"], 300)
                else:
                    reason = UNREACHABLE
                waiting = _waiting(prior, reason, now)
                calls_open = False
                summary["pending"] += 1
                continue
            if verdict != "distilled" and verdict_row["timeouts"] >= MAX_TIMEOUTS:
                verdict = "failed:%d" % MAX_TIMEOUTS   # its own answer charged its third timeout
                wm.stage(sid, dict(verdict_row, verdict=verdict, error="timed out %d times" % verdict_row["timeouts"]),
                         write=False)
            summary["verdicts"][sid] = verdict
        wm.write_seen()
        wm.write_pending()        # one write for every row staged above
        if waiting != prior:
            wm.stage_waiting(waiting)
        if waiting:
            summary.update(status="waiting", reason=waiting["reason"])
        if faults:
            summary["exit"] = 1
        write_manifest(dest, lane, wm, now, host=host, items=summary["captures"], failed=failed_writes,
                       waiting=summary["pending"], tool=tool)
        return summary
    finally:
        if lock is not None:
            lock.close()   # closing the descriptor releases the flock


def week_counts(wm, now):
    """This week's verdict counts, as the next commit would leave them."""
    rows, _ = wm.merged()
    counts = {"distilled": 0, "captures": 0, "skipped": 0, "failed": 0, "refused": 0}
    for row in rows.values():
        verdict = row.get("verdict") or ""
        at = prefilter.epoch(row.get("at"))
        if not verdict or at is None or at < now - WEEK_S:
            continue
        if verdict == "distilled":
            counts["distilled"] += 1
            counts["captures"] += int(row.get("captures") or 0)
        elif verdict == "skipped:before-enable":
            continue   # never looked at: nothing was written after capture was enabled
        elif verdict.startswith("skipped:") or verdict == privacy.DENIED:
            counts["skipped"] += 1
        elif verdict.startswith("failed:"):
            counts["failed"] += 1
        elif verdict == privacy.REFUSED:
            counts["refused"] += 1
    return counts


def write_manifest(dest_dir, lane, wm, now, host="", items=0, failed=0, waiting=0, tool="claude-code"):
    """<dest_dir>/MANIFEST.md in sov_manifest's shape, plus this week's counts and, while
    the lane waits on its model, why and since when."""
    week = week_counts(wm, now)
    _, wait = wm.merged()
    lines = ["---", "type: capture", "source: %s" % lane, "created: %s" % time.strftime("%Y-%m-%d", time.localtime(now)),
             "title: %s session capture manifest" % NAMES.get(tool, tool), "---", "",
             "Last run: %s on %s. Items mirrored: %d. Failed: %d." % (_iso(now), host, items, failed), "",
             "Sessions this week: distilled %d, captures %d, skipped %d, waiting %d, failed %d, refused %d."
             % (week["distilled"], week["captures"], week["skipped"], waiting, week["failed"], week["refused"])]
    if wait:
        phrase = waiting_phrase(wait.get("reason"))
        since = prefilter.epoch(wait.get("since"))
        lines.append("Waiting: %s since %s." % (phrase, _iso(since, True)) if since is not None
                     else "Waiting: %s." % phrase)
    path = Path(dest_dir) / "MANIFEST.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def commit(tool, env):
    """Merge the staged rows after a successful publish."""
    state.Watermark(state.state_dir(env), tool).commit()


def discard(tool, env):
    """Drop the staged rows after a failed publish, so every session retries."""
    state.Watermark(state.state_dir(env), tool).discard()
