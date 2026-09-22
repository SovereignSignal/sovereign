"""The digest counts the day, not the run that composes it.

Since 2026-09-21 the curator runs every two hours as hub job `curate`, and the
06:00 nightly is one run among twelve. Its four headline counts were read out of
its own stdout, so eleven ticks of judging, proposing, promoting and rejecting
happened between one digest and the next and appeared in none of those numbers.
The pending count was right the whole time, because it reads the queue on disk.

So the four are read from the lane's own ledgers over the window since the last
digest: judgments.jsonl for judged and new, decisions.log for what the gears
applied and what the lane's auto-reject classes rejected. The window's left edge
is `.last-digest`, written only after a digest has actually gone out.

Two things here are easy to get subtly wrong and are held on purpose. `new` is
counted from judgment rows rather than proposals/ ctimes, because a proposal that
auto-promoted or auto-rejected has already left that folder. And the marker moves
only on a send: a digest that failed to deliver must leave the window open, or
the material it never reported is never reported at all.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from sovereign_hub import digest_counts  # noqa: E402

DAY = 86400


def judgment_ts(epoch):
    """The form curator-run writes: aware ISO, offset punctuated."""
    return datetime.fromtimestamp(epoch).astimezone().isoformat()


def decision_ts(epoch):
    """The form _curator-lib.sh writes with date +%z: offset NOT punctuated."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


class Lane:
    """A curator lane on disk, with only the files the counting reads."""

    def __init__(self, root):
        self.dir = Path(root)
        (self.dir / "proposals").mkdir(parents=True, exist_ok=True)

    def judge(self, epoch, promote, **extra):
        row = {"timestamp": judgment_ts(epoch), "source": "raw/tools/x/a.md",
               "promote": promote}
        row.update(extra)
        with open(self.dir / "judgments.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def raw_judgment(self, line):
        with open(self.dir / "judgments.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def decide(self, epoch, verdict, slug, actor, detail="why"):
        with open(self.dir / "decisions.log", "a", encoding="utf-8") as f:
            f.write("\t".join([decision_ts(epoch), verdict, slug + ".md",
                               actor, detail]) + "\n")

    def raw_decision(self, line):
        with open(self.dir / "decisions.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def propose(self, slug):
        (self.dir / "proposals" / (slug + ".md")).write_text(
            "---\ntype: concept\nsource: raw/tools/x/a.md\n---\n\n# %s\n" % slug,
            encoding="utf-8")

    def mark(self, epoch):
        (self.dir / ".last-digest").write_text("%.6f\n" % epoch, encoding="utf-8")

    def marker(self):
        try:
            return (self.dir / ".last-digest").read_text(encoding="utf-8").strip()
        except OSError:
            return None


class LaneCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="digest-counts-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lane = Lane(Path(self.tmp) / "raw" / "workspaces" / "archivist")

    def counts(self, now, **kw):
        start, end = digest_counts.window(str(self.lane.dir), now, **kw)
        return digest_counts.counts(str(self.lane.dir), start, end)


class TheWindowCoversEveryTickSinceTheLastDigest(LaneCase):
    """The headline case: one nightly run plus the ticks that ran all day."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        self.last_digest = self.now - DAY
        self.lane.mark(self.last_digest)
        # Yesterday, before the last digest went out. None of this counts again.
        for n in range(5):
            self.lane.judge(self.last_digest - 3600 - n, promote=(n < 2))
        self.lane.decide(self.last_digest - 3600, "approved", "old-card", "auto-gear")
        self.lane.decide(self.last_digest - 3500, "rejected", "old-junk", "auto-taste")
        # Three curate ticks through the day, then this morning's nightly run.
        for tick in range(3):
            at = self.last_digest + (tick + 1) * 7200
            self.lane.judge(at, promote=True)
            self.lane.judge(at + 1, promote=False)
            self.lane.judge(at + 2, promote=None, error="endpoint refused")
            self.lane.decide(at + 30, "approved", "tick-%d" % tick, "auto-gear")
        self.lane.decide(self.last_digest + 7300, "rejected", "tick-junk", "auto-taste")
        for n in range(2):
            self.lane.judge(self.now - 300 + n, promote=(n == 0))

    def test_judged_counts_every_run_in_the_window(self):
        self.assertEqual(self.counts(self.now)["judged"], 11)

    def test_new_counts_what_the_judge_kept(self):
        self.assertEqual(self.counts(self.now)["new"], 4)

    def test_auto_applied_counts_the_ticks_the_gears_landed(self):
        self.assertEqual(self.counts(self.now)["auto_applied"], 3)

    def test_auto_rejected_counts_the_lanes_own_classes(self):
        self.assertEqual(self.counts(self.now)["auto_rejected"], 1)

    def test_nothing_before_the_marker_is_counted_twice(self):
        """Move the marker forward and the day's work drops out, all four of it."""
        self.lane.mark(self.now - 60)
        self.assertEqual(self.counts(self.now),
                         {"judged": 0, "new": 0, "auto_applied": 0, "auto_rejected": 0})


class TheLedgersAreReadForWhatTheyMean(LaneCase):

    def setUp(self):
        super().setUp()
        self.now = time.time()
        self.lane.mark(self.now - 3600)
        self.at = self.now - 1800

    def test_only_a_true_promote_is_a_new_proposal(self):
        """promote is True, False, or None for an errored judgment. Only True drafts."""
        self.lane.judge(self.at, promote=True)
        self.lane.judge(self.at, promote=False)
        self.lane.judge(self.at, promote=None, error="boom")
        got = self.counts(self.now)
        self.assertEqual((got["judged"], got["new"]), (3, 1))

    def test_new_survives_a_proposal_leaving_the_queue(self):
        """The reason ctimes cannot be the source: an auto-applied card is gone
        from proposals/ before the digest composes, and it was still new."""
        self.lane.judge(self.at, promote=True)
        self.lane.decide(self.at + 5, "approved", "landed", "auto-gear")
        self.assertEqual(os.listdir(self.lane.dir / "proposals"), [])
        self.assertEqual(self.counts(self.now)["new"], 1)

    def test_the_owners_own_verdicts_are_not_the_gears(self):
        for actor in ("owner-cli", "console-owner", "telegram-owner", "owner-hub-cli"):
            self.lane.decide(self.at, "approved", "by-" + actor, actor)
            self.lane.decide(self.at, "rejected", "no-" + actor, actor)
        got = self.counts(self.now)
        self.assertEqual((got["auto_applied"], got["auto_rejected"]), (0, 0))

    def test_a_verdict_the_actor_did_not_write_is_not_counted(self):
        """Actor and verdict both, so a shape that never happens cannot inflate."""
        self.lane.decide(self.at, "rejected", "odd", "auto-gear")
        self.lane.decide(self.at, "approved", "odd", "auto-taste")
        got = self.counts(self.now)
        self.assertEqual((got["auto_applied"], got["auto_rejected"]), (0, 0))

    def test_a_row_from_before_the_actor_column_existed_is_not_a_gear(self):
        """Four-field rows predate CURATOR_ACTOR; they were the owner's hand."""
        self.lane.raw_decision("\t".join([decision_ts(self.at), "approved",
                                          "ancient.md", "some detail"]))
        self.assertEqual(self.counts(self.now)["auto_applied"], 0)

    def test_an_unparseable_row_is_skipped_not_counted(self):
        self.lane.raw_judgment("{not json")
        self.lane.raw_judgment("")
        self.lane.judge(self.at, promote=True, timestamp=None)
        self.lane.raw_decision("garbage with no tabs")
        self.lane.raw_decision("\t".join(["not-a-date", "approved", "x.md", "auto-gear", ""]))
        self.lane.judge(self.at, promote=True)
        got = self.counts(self.now)
        self.assertEqual((got["judged"], got["new"], got["auto_applied"]), (1, 1, 0))

    def test_a_lane_with_no_ledgers_counts_zero(self):
        self.assertEqual(self.counts(self.now),
                         {"judged": 0, "new": 0, "auto_applied": 0, "auto_rejected": 0})


class TheMarkerDecidesTheLeftEdge(LaneCase):

    def test_an_absent_marker_falls_back_to_one_day(self):
        now = time.time()
        start, end = digest_counts.window(str(self.lane.dir), now)
        self.assertEqual(end, now)
        self.assertAlmostEqual(start, now - DAY, places=6)

    def test_the_fallback_is_bounded_not_the_whole_ledger(self):
        """A lost marker costs one day of double counting, never the archive."""
        now = time.time()
        self.lane.judge(now - 10 * DAY, promote=True)
        self.lane.judge(now - 3600, promote=True)
        self.assertEqual(self.counts(now)["judged"], 1)

    def test_an_unreadable_marker_falls_back(self):
        (self.lane.dir / ".last-digest").write_text("not a number\n", encoding="utf-8")
        now = time.time()
        start, _ = digest_counts.window(str(self.lane.dir), now)
        self.assertAlmostEqual(start, now - DAY, places=6)

    def test_a_marker_in_the_future_falls_back(self):
        """A clock that went backwards must not silently zero every digest."""
        now = time.time()
        self.lane.mark(now + 7 * DAY)
        start, _ = digest_counts.window(str(self.lane.dir), now)
        self.assertAlmostEqual(start, now - DAY, places=6)

    def test_a_marker_is_read_back_exactly_as_written(self):
        """Sub-second precision, so the two windows meet without a gap or an overlap."""
        when = time.time()
        digest_counts.write_marker(str(self.lane.dir), when)
        self.assertAlmostEqual(digest_counts.read_marker(str(self.lane.dir)), when, places=5)

    def test_the_window_is_half_open_so_nothing_falls_between_two_digests(self):
        edge = float(int(time.time()) - 600)   # whole second: an exact round trip
        self.lane.judge(edge, promote=True)
        before = digest_counts.counts(str(self.lane.dir), edge - DAY, edge)
        after = digest_counts.counts(str(self.lane.dir), edge, edge + DAY)
        self.assertEqual((before["judged"], after["judged"]), (0, 1))


class TheCommandLineSpeaksToTheComposer(LaneCase):

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"))
        return subprocess.run([sys.executable, "-m", "sovereign_hub.digest_counts", *args],
                              capture_output=True, text=True, env=env)

    def test_counts_prints_shell_readable_integers(self):
        now = time.time()
        self.lane.mark(now - 3600)
        self.lane.judge(now - 60, promote=True)
        self.lane.decide(now - 50, "approved", "a", "auto-gear")
        self.lane.decide(now - 40, "rejected", "b", "auto-taste")
        r = self.run_cli("counts", "--lane", str(self.lane.dir), "--now", "%.6f" % now)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = dict(line.split("=", 1) for line in r.stdout.split())
        self.assertEqual(out["JUDGED"], "1")
        self.assertEqual(out["NEW"], "1")
        self.assertEqual(out["AUTO_APPLIED"], "1")
        self.assertEqual(out["AUTO_REJECTED"], "1")
        self.assertAlmostEqual(float(out["WINDOW_END"]), now, places=5)

    def test_mark_writes_the_instant_it_is_given(self):
        when = time.time() - 123
        r = self.run_cli("mark", "--lane", str(self.lane.dir), "--at", "%.6f" % when)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertAlmostEqual(float(self.lane.marker()), when, places=5)


class TheNightlyCountsTheWindowAndMarksOnlyWhatItSent(unittest.TestCase):
    """The shipped composer, run for real against a throwaway vault."""

    RUNNER_OUTPUT = (
        "curator-run: judged 1 new item(s), proposed 0 card(s)\n"
        "curator-run: auto-promoted 0 proposal(s) (0 update(s), 0 new) (act-and-report)\n"
        "curator-run: auto-rejected 0 proposal(s) via lane auto-reject.md (act-and-report)\n"
    )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nightly-digest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vault = self.tmp / "vault"
        self.lane = Lane(self.vault / "raw" / "workspaces" / "archivist")
        self.state = self.tmp / "state"
        (self.state / "hub").mkdir(parents=True)
        self.hub = self.tmp / "bin" / "hub"
        self.hub.mkdir(parents=True)
        shutil.copy2(ROOT / "bin" / "hub" / "nightly", self.hub / "nightly")
        self.sent = self.tmp / "sent.txt"
        self.script(self.hub / "tg-send", """#!/bin/bash
: >"$TG_SENT"
for a in "$@"; do printf '%s\\n' "$a" >>"$TG_SENT"; done
exit "${TG_RC:-0}"
""")
        self.runner = self.tmp / "runner"
        self.script(self.runner, "#!/bin/bash\ncat <<'EOF'\n%sEOF\n" % self.RUNNER_OUTPUT)

        self.now = time.time()
        self.last_digest = self.now - DAY + 60
        self.lane.mark(self.last_digest)
        for n in range(4):                       # daytime ticks: 4 judged, 2 kept
            self.lane.judge(self.last_digest + 600 + n, promote=(n < 2))
        self.lane.judge(self.last_digest - 600, promote=True)   # the last digest's own
        self.lane.decide(self.last_digest + 700, "approved", "landed-a", "auto-gear")
        self.lane.decide(self.last_digest + 800, "approved", "landed-b", "auto-gear")
        self.lane.decide(self.last_digest + 900, "rejected", "dropped", "auto-taste")
        self.lane.decide(self.last_digest + 950, "approved", "by-hand", "console-owner")
        self.lane.decide(self.last_digest - 700, "approved", "yesterday", "auto-gear")
        self.lane.propose("waiting-one")
        self.lane.propose("waiting-two")

    def script(self, path, body):
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def nightly(self, *args, rc="0", **override):
        env = dict(os.environ,
                   SOV_TEMPLATE=str(ROOT), SOVS_VAULT=str(self.vault),
                   CURATOR_LANE="archivist", SOV_STATE_DIR=str(self.state),
                   HOME=str(self.tmp), ARCHIVIST_RUNNER=str(self.runner),
                   TG_SENT=str(self.sent), TG_RC=rc, **override)
        env.pop("SOV_HUB_DIGEST", None)
        return subprocess.run(["/bin/bash", str(self.hub / "nightly"), *args],
                              capture_output=True, text=True, env=env)

    def message(self):
        return self.sent.read_text(encoding="utf-8")

    def test_the_header_counts_the_window_not_this_run(self):
        """The stub run reports judged 1, proposed 0. The window holds more."""
        r = self.nightly()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("judged 4 · new 2 · auto-applied 2 · auto-rejected 1 · pending 2",
                      self.message())

    def test_the_pending_count_still_reads_the_queue_on_disk(self):
        self.lane.propose("waiting-three")
        self.nightly()
        self.assertIn("pending 3", self.message())

    def test_a_sent_digest_closes_the_window(self):
        before = float(self.lane.marker())
        self.nightly()
        after = float(self.lane.marker())
        self.assertGreater(after, before)
        self.assertLessEqual(after, time.time() + 1)

    def test_a_send_that_failed_leaves_the_window_open(self):
        """Otherwise the material the digest never delivered is never reported."""
        before = self.lane.marker()
        r = self.nightly(rc="1")
        self.assertEqual(self.lane.marker(), before)
        self.assertIn("send failed", r.stderr)

    def test_a_dry_run_sends_nothing_and_marks_nothing(self):
        (self.state / "hub" / "nightly.last-output").write_text(
            self.RUNNER_OUTPUT, encoding="utf-8")
        before = self.lane.marker()
        r = self.nightly("--compose-dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("judged 4 · new 2 · auto-applied 2 · auto-rejected 1 · pending 2",
                      r.stdout)
        self.assertFalse(self.sent.exists())
        self.assertEqual(self.lane.marker(), before)

    def test_a_window_that_cannot_be_read_still_sends_and_says_so(self):
        """A digest that cannot count must not claim a quiet day it never measured."""
        before = self.lane.marker()
        r = self.nightly(SOV_PYTHON=str(self.tmp / "no-such-python"))
        self.assertEqual(r.returncode, 0, r.stderr)
        message = self.message()
        self.assertIn("judged 1 · new 0 · auto-applied 0 · auto-rejected 0 · pending 2",
                      message)
        self.assertIn("counts: this run only", message)
        self.assertEqual(self.lane.marker(), before,
                         "an unmeasured window must not be closed")

    def test_a_run_that_never_reached_the_send_marks_nothing(self):
        """The curation step failed, so the window must stay where it was."""
        self.script(self.runner, "#!/bin/bash\necho boom >&2\nexit 3\n")
        before = self.lane.marker()
        r = self.nightly()
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.lane.marker(), before)


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
