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

import sovereign_config

from . import READERS, distill, excerpt, inference, prefilter, privacy, prompt, state

CAPTURE = Path(__file__).resolve().parents[2] / "bin" / "sov-capture"
NAMES = {"claude-code": "Claude Code"}
# The connector runner kills a lane at 300 s. A call with timeout T can block about
# 2T + 30 s (one retry after a timeout), so no call starts after CALL_WINDOW_S and the
# walk itself stops at WALK_WINDOW_S; what it did not reach waits for the next tick.
CALL_TIMEOUT_S = 60
CALL_WINDOW_S = 150
WALK_WINDOW_S = 240
CAPTURE_TIMEOUT_S = 60
WEEK_S = 7 * 86400
UNREACHABLE = "model unreachable"
OFF_REASON = "Session capture is off."
_KEBAB = re.compile(r"[^a-z0-9]+")
_DISTILLER_PROVIDER = re.compile(r"[^a-z0-9.-]+")
_DISTILLER_MODEL = re.compile(r"[^A-Za-z0-9._:-]+")


def _iso(epoch, minutes=False):
    return time.strftime("%Y-%m-%dT%H:%MZ" if minutes else "%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return prefilter._epoch(value)


def _one_line(value, limit):
    return " ".join(str(value or "").split())[:limit].strip()


def _kebab(text):
    return _KEBAB.sub("-", str(text).lower()).strip("-")


def _host(env):
    host = sovereign_config.pointer("~/.brain-host", env)
    return host or socket.gethostname().split(".")[0].lower()


def _vault(env):
    root = sovereign_config.pointer("~/.brain-root", env)
    if not root:
        return None
    root = os.path.realpath(os.path.expanduser(root))
    return root if os.path.isdir(root) else None


def _project(s):
    cwds = s.get("cwds") or []
    return _one_line(os.path.basename(cwds[0].rstrip("/")), 200) if cwds else ""


def _span(s):
    a, b = prefilter._epoch(s.get("first_ts")), prefilter._epoch(s.get("last_ts"))
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


def _context(tool, env, since=None):
    if tool not in READERS:
        raise ValueError("Unknown tool: %s." % tool)
    sd = state.state_dir(env)
    cfg = state.load_config(sd)
    entry = cfg["tools"].get(tool) or {}
    floor = _epoch(entry.get("enabled_at")) if entry.get("enabled") else None
    if since is not None:
        floor = since if floor is None else min(floor, since)
    vault = _vault(env)
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
        found.append((st.st_mtime, path, st.st_size))
    found.sort()
    for mtime, path, size in found:
        if deadline is not None and time.monotonic() >= deadline:
            return
        # The watermark id is the file's own name, which is also what `claude --resume`
        # takes; a resumed file can open with an earlier session's sessionId.
        sid = os.path.splitext(os.path.basename(path))[0]
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


def _excerpt(s, hits):
    text, turn_ids = excerpt.build(s["turns"], hits)
    text, _ = excerpt.clean(text)
    return text, turn_ids


def enabled(tool, env):
    """Whether the owner has turned session capture on for `tool`. Raises ValueError on
    a config that cannot be read."""
    return _context(tool, env)["enabled"]


def candidates(tool, env, now, since=None):
    """The dry plan: one row per transcript the next tick would look at, with no model
    call and no write. `since` (epoch seconds) lowers the enable floor for a backfill."""
    ctx = _context(tool, env, since)
    wm = state.Watermark(ctx["state_dir"], tool)
    out = []
    for look in _walk(ctx, wm.rows, now):
        row = {"id": look["sid"], "project": None, "quiet_age_s": int(now - look["mtime"]), "prompts": None,
               "score": None, "verdict": "active" if look["active"] else look["verdict"],
               "excerpt_chars": 0, "est_tokens": 0}
        s = look.get("scan")
        if s is not None:
            row.update(project=_project(s) or None, prompts=len(s["turns"]), score=look["score"])
            if look["verdict"] is None:
                text, _ = _excerpt(s, look["hits"])
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


def _capture(c, s, sid, tool, lane, stage, vault, distiller, env):
    """Hand one validated candidate to sov-capture. True when it was written."""
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
        return False
    if done.returncode != 0:
        sys.stderr.write("sessions: capture for %s was not written (exit %d): %s\n"
                         % (sid, done.returncode, done.stderr.strip()[:300]))
        return False
    return True


def _waiting(prior, reason, now):
    """{"reason", "since"}, keeping the prior since while the reason is unchanged."""
    if prior and prior.get("reason") == reason and prior.get("since"):
        return {"reason": reason, "since": prior["since"]}
    return {"reason": reason, "since": _iso(now)}


def tick(tool, env, dest_dir, now):
    """One pass. Returns {"tool", "status": "off"|"waiting"|"ran", "reason", "calls",
    "captures", "pending", "verdicts": {id: verdict}, "exit"}; exit is 1 only when a
    capture write failed. Writes sessions/MANIFEST.md into dest_dir unless off."""
    started = time.monotonic()
    ctx = _context(tool, env)
    summary = {"tool": tool, "status": "off", "reason": OFF_REASON, "calls": 0, "captures": 0, "pending": 0,
               "verdicts": {}, "exit": 0}
    if not ctx["enabled"]:
        return summary
    if not ctx["vault"]:
        raise ValueError("No archive on this Mac (set ~/.brain-root).")
    lane, stage, dest = _lane_paths(ctx, env, dest_dir)
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
    key = inference.key(res)
    summary.update(status="ran", reason="")
    budget = ctx["cfg"]["budget"]
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    waiting = prior if prior and prior.get("reason") == UNREACHABLE else None
    calls_open, chars, failed_writes = True, 0, 0

    for look in _walk(ctx, wm.rows, now, observe=lambda *a: wm.observe(*a, write=False),
                      deadline=started + WALK_WINDOW_S):
        if look["active"]:
            continue
        sid, s, row = look["sid"], look["scan"], look["row"]
        cwds = (s or {}).get("cwds") or []
        verdict_row = {"size": look["size"], "mtime": look["mtime"], "policy": ctx["policy"],
                       "cwd": cwds[0] if cwds else None, "project": _project(s) if s else "", "at": _iso(now),
                       "attempts": int((row or {}).get("attempts") or 0), "captures": 0,
                       "distiller": res["distiller"], "prompt": prompt.VERSION}
        if look["verdict"] is not None:
            wm.stage(sid, dict(verdict_row, verdict=look["verdict"]), write=False)
            summary["verdicts"][sid] = look["verdict"]
            continue
        if (not calls_open or summary["calls"] >= budget["calls_per_tick"]
                or wm.calls_today(day) >= budget["calls_per_day"]
                or time.monotonic() - started >= CALL_WINDOW_S):
            summary["pending"] += 1
            continue
        text, turn_ids = _excerpt(s, look["hits"])
        if chars + len(text) > budget["chars_per_tick"]:
            summary["pending"] += 1
            continue
        wm.write_seen()       # the sizes seen so far survive whatever this call does
        wm.record_call(day)
        summary["calls"] += 1
        chars += len(text)
        out = distill.distill(res, key, s, text, turn_ids, timeout=CALL_TIMEOUT_S)
        verdict_row["attempts"] += 1
        if out["status"] == "ok":
            waiting = None
            written = 0
            for c in out["captures"]:
                if _capture(c, s, sid, tool, lane, stage, ctx["vault"], res["distiller"], env):
                    written += 1
                else:
                    failed_writes += 1
            if written != len(out["captures"]):
                summary["pending"] += 1   # the tick fails and is discarded: this session retries
                continue
            summary["captures"] += written
            verdict = "distilled"
            wm.stage(sid, dict(verdict_row, verdict=verdict, captures=written), write=False)
        elif out["status"] == "failed":
            waiting = None
            verdict = "failed:%d" % (_failures(row) + 1)
            wm.stage(sid, dict(verdict_row, verdict=verdict), write=False)
        else:
            # unreachable: the road to the model, nothing about the session. refused: a
            # guard refusal at call time, a configuration the owner must see. Either way
            # the session stays pending and this tick makes no further call.
            waiting = _waiting(prior, UNREACHABLE if out["status"] == "unreachable" else
                               _one_line(out["error"], 300) or "refused", now)
            calls_open = False
            summary["pending"] += 1
            continue
        summary["verdicts"][sid] = verdict
    wm.write_seen()
    wm.write_pending()        # one write for every row staged above
    if waiting != prior:
        wm.stage_waiting(waiting)
    if waiting:
        summary.update(status="waiting", reason=waiting["reason"])
    if failed_writes:
        summary["exit"] = 1
    write_manifest(dest, lane, wm, now, host=host, items=summary["captures"], failed=failed_writes,
                   waiting=summary["pending"], tool=tool)
    return summary


def week_counts(wm, now):
    """This week's verdict counts, as the next commit would leave them."""
    rows, _ = wm.merged()
    counts = {"distilled": 0, "captures": 0, "skipped": 0, "failed": 0, "refused": 0}
    for row in rows.values():
        verdict = row.get("verdict") or ""
        at = _epoch(row.get("at"))
        if not verdict or at is None or at < now - WEEK_S:
            continue
        if verdict == "distilled":
            counts["distilled"] += 1
            counts["captures"] += int(row.get("captures") or 0)
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
        reason = _one_line(wait.get("reason"), 300)
        since = _epoch(wait.get("since"))
        if reason == UNREACHABLE and since is not None:
            lines.append("Waiting: %s since %s." % (reason, _iso(since, True)))
        else:
            lines.append("Waiting: %s%s" % (reason, "" if reason.endswith(".") else "."))
    path = Path(dest_dir) / "MANIFEST.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def commit(tool, env):
    """Merge the staged rows after a successful publish."""
    state.Watermark(state.state_dir(env), tool).commit()


def discard(tool, env):
    """Drop the staged rows after a failed publish, so every session retries."""
    state.Watermark(state.state_dir(env), tool).discard()
