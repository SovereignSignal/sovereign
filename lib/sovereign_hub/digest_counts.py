"""The digest's four headline counts, over the window since the last digest.

Until 2026-09-22 bin/hub/nightly read judged, new, auto-applied and auto-rejected
out of its OWN run's stdout. That was right while the curator ran once a night.
Since the curate tick started every two hours on 2026-09-21 it is a minority of
the day's work: eleven ticks judge, propose, promote and reject between one 06:00
digest and the next, and none of it reached those four numbers. The pending count
was correct the whole time, because it reads the queue on disk rather than a run.

So the four are read from the lane's own ledgers over the window that ends when
the numbers are taken and begins at the last digest:

    judged         rows in judgments.jsonl, which curator-run appends one of per
                   judged item, on every run it makes
    new            those same rows with promote True, which is exactly the set
                   that becomes a proposal card (curator-run's `new_proposals`)
    auto-applied   decisions.log rows a granted gear wrote (actor auto-gear,
                   verdict approved)
    auto-rejected  decisions.log rows the lane's auto-reject classes wrote
                   (actor auto-taste, verdict rejected)

`new` is counted from the judgment rows rather than from proposals/ ctimes on
purpose. A proposal that auto-promoted or auto-rejected has already left that
folder by the time the digest composes, so ctimes would undercount new by exactly
the two auto- numbers printed beside it.

The window's left edge is `.last-digest` in the lane, epoch seconds, written by
the nightly only once a digest has actually gone out. Absent, unreadable, or
ahead of the window's right edge (a clock that went backwards), it falls back to
one day back: the digest's own cadence, and bounded, so a lost marker costs one
day of double counting rather than a replay of the whole ledger. The window is
half open, [start, end), and the marker keeps sub-second precision, so two
consecutive digests meet exactly, with no gap and no overlap.

This reports; it decides nothing. Stdlib only, deterministic, and read-only
against the lane apart from the marker it owns.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

MARKER_NAME = ".last-digest"
DEFAULT_WINDOW_S = 86400
AUTO_PROMOTE_ACTOR = "auto-gear"
AUTO_REJECT_ACTOR = "auto-taste"

# '2026-08-10T08:14:14-0700': _curator-lib.sh writes the offset with date +%z, and
# the hub ships Python 3.9, whose fromisoformat wants it punctuated.
_UNPUNCTUATED_OFFSET = re.compile(r"^(.*[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)([+-]\d{2})(\d{2})$")


def parse_epoch(raw):
    """One timestamp from either ledger as epoch seconds, or None if unreadable.

    A row whose timestamp cannot be read is skipped rather than guessed at: these
    are counts in a notification, and a wrong number is worse than a missing row.
    """
    raw = (raw or "").strip() if isinstance(raw, str) else ""
    if not raw:
        return None
    match = _UNPUNCTUATED_OFFSET.match(raw)
    if match:
        raw = "%s%s:%s" % match.groups()
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def marker_path(lane_dir):
    return os.path.join(lane_dir, MARKER_NAME)


def read_marker(lane_dir):
    """The instant the last digest was sent, or None when there is no usable one."""
    try:
        with open(marker_path(lane_dir), encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        return None
    try:
        when = float(raw)
    except ValueError:
        return None
    return when if when > 0 else None


def write_marker(lane_dir, when):
    """Close the window at `when`. Written whole and renamed into place: a half
    written marker would silently widen or narrow the next digest's window."""
    path = marker_path(lane_dir)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write("%.6f\n" % float(when))
    os.replace(temp, path)
    return path


def window(lane_dir, now, default_window_s=DEFAULT_WINDOW_S):
    """(start, end) the counts cover: since the last digest, up to now."""
    start = read_marker(lane_dir)
    if start is None or start > now:
        start = now - default_window_s
    return start, now


def _judgments(lane_dir):
    path = os.path.join(lane_dir, "judgments.jsonl")
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _decisions(lane_dir):
    """Rows of the append-only log: ts, verdict, file, actor, detail.

    Rows written before the actor column existed carry four fields and were the
    owner's own hand, so they are read as owner-cli, never as a gear.
    """
    path = os.path.join(lane_dir, "decisions.log")
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            actor = parts[3] if len(parts) >= 5 else "owner-cli"
            yield {"at": parse_epoch(parts[0]), "verdict": parts[1].strip(),
                   "actor": actor.strip()}


def counts(lane_dir, start, end):
    """The four headline numbers for [start, end), read from the lane's ledgers."""
    judged = new = auto_applied = auto_rejected = 0
    for row in _judgments(lane_dir):
        at = parse_epoch(row.get("timestamp"))
        if at is None or not start <= at < end:
            continue
        judged += 1
        if row.get("promote") is True:
            new += 1
    for row in _decisions(lane_dir):
        at = row["at"]
        if at is None or not start <= at < end:
            continue
        if row["actor"] == AUTO_PROMOTE_ACTOR and row["verdict"] == "approved":
            auto_applied += 1
        elif row["actor"] == AUTO_REJECT_ACTOR and row["verdict"] == "rejected":
            auto_rejected += 1
    return {"judged": judged, "new": new,
            "auto_applied": auto_applied, "auto_rejected": auto_rejected}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="digest-counts",
        description="The digest's counts since the last digest, and the marker that ends it.")
    sub = parser.add_subparsers(dest="command")
    read = sub.add_parser("counts", help="print the window and its four counts")
    read.add_argument("--lane", required=True, help="the curator lane directory")
    read.add_argument("--now", type=float, help="close the window here instead of at this instant")
    mark = sub.add_parser("mark", help="record that a digest was sent")
    mark.add_argument("--lane", required=True, help="the curator lane directory")
    mark.add_argument("--at", type=float, help="the instant to record instead of this one")
    args = parser.parse_args(argv)

    if args.command == "counts":
        now = time.time() if args.now is None else args.now
        start, end = window(args.lane, now)
        found = counts(args.lane, start, end)
        print("WINDOW_START=%.6f" % start)
        print("WINDOW_END=%.6f" % end)
        print("JUDGED=%d" % found["judged"])
        print("NEW=%d" % found["new"])
        print("AUTO_APPLIED=%d" % found["auto_applied"])
        print("AUTO_REJECTED=%d" % found["auto_rejected"])
        return 0
    if args.command == "mark":
        write_marker(args.lane, time.time() if args.at is None else args.at)
        return 0
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":                                 # pragma: no cover
    sys.exit(main())
