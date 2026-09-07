"""The cadence gate, measured over a sequence of ticks, and what a stand-down leaves behind.

One scheduler entry runs every lane, and its interval is the smallest cadence any lane
declares. The gate that decides whether a lane is due therefore has to be right about the
scheduler, not just about seconds:

  * launchd counts StartInterval from the moment the previous tick STARTED, so tick k+1
    lands one interval after tick k BEGAN. A lane that finished d seconds into tick k is
    only `interval - d` seconds old when tick k+1 asks. Under a plain `age >= cadence_s`
    gate, every lane whose cadence IS the interval -- which is every shipped default --
    misses by exactly d, waits a whole further interval, and mirrors at half the rate it
    declares, forever, with nothing anywhere saying so. That is the regression this file
    exists to keep out;
  * a lane that declares a LONGER cadence must still pace itself: its own rate, and never
    faster, however wide the gate had to be opened for the first case.

So the sequence below is a real scheduler, simulated: the shipped runner is invoked once
per tick, and between ticks this file advances the machine's clock exactly as launchd
spaces the firings, counting the real seconds the ticks themselves cost. Every assertion
is over what the mirrors actually ran, not over what the gate said about them.

The second half is the record. A tick that finds the lock held stands down and mirrors
nothing; one of those is normal (a tick that ran long), a run of them is a runner wedged
behind a lock while nothing on the machine writes. The record has to carry enough to tell
those apart, because the record is what the status reader consumes.

Nothing is inherited: HOME, the state directory, the manifest and every mirror script live
inside a temp dir.
"""
import datetime
import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_connectors_runner import PATH, PY, RUNNER, declare, entry

ISO = "%Y-%m-%dT%H:%M:%SZ"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
INTERVAL = 900          # the shipped default tick, and what every default cadence declares
INSIDE_TICK_S = 5       # how far into a tick a lane finishes: the d that used to be lost


def shift(obj, seconds):
    """Every ISO stamp in the record, moved `seconds` further into the past."""
    if isinstance(obj, dict):
        return {k: shift(v, seconds) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shift(v, seconds) for v in obj]
    if isinstance(obj, str) and STAMP.match(obj):
        t = datetime.datetime.strptime(obj, ISO).replace(tzinfo=datetime.timezone.utc)
        return (t - datetime.timedelta(seconds=seconds)).strftime(ISO)
    return obj


def age_of(stamp):
    t = datetime.datetime.strptime(str(stamp), ISO).replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()


class Scheduler:
    """A throwaway machine, plus the scheduler that fires its one job."""

    def __init__(self, tmp, cadences, interval_s=INTERVAL):
        self.tmp = Path(tmp)
        self.state = self.tmp / "state"
        self.home = self.tmp / "home"
        self.out = self.tmp / "out"
        self.home.mkdir()
        self.out.mkdir()
        (self.home / ".brain-host").write_text("testbox")
        self.interval_s = interval_s
        self.cadences = dict(cadences)
        # one line per run, so "did this lane run on that tick" is a count
        declare(self.state,
                {hid: entry(str(self.tmp), hid, 'date +%%s%%N >> "%s/%s"' % (self.out, hid),
                            cadence_s=c, timeout_s=60)
                 for hid, c in self.cadences.items()},
                interval_s=interval_s)
        self._t = time.time()

    def env(self):
        return {"HOME": str(self.home), "PATH": PATH, "SOV_STATE_DIR": str(self.state),
                "SOV_MANIFEST": str(self.state / "connectors.json")}

    def fire(self, args=()):
        """One firing of the shared job, exactly as the scheduler runs it."""
        r = subprocess.run([PY, str(RUNNER)] + list(args), capture_output=True, text=True,
                           env=self.env(), timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        return r

    def advance(self, seconds):
        """Move this machine's clock forward by `seconds`.

        The real seconds the tick itself cost count toward it, so the arithmetic holds
        however slow the machine running this test is: the next tick sees an age of
        exactly `seconds`, not `seconds` plus however long python took to start."""
        now = time.time()
        step = seconds - (now - self._t)
        self._t = now
        assert step > 0, "the ticks cost more real time than the interval being simulated"
        p = self.state / "runs.json"
        p.write_text(json.dumps(shift(json.loads(p.read_text()), step), indent=2))

    def runs(self, lane_id):
        """How many times that lane's mirror has actually run."""
        p = self.out / lane_id
        return len(p.read_text().splitlines()) if p.exists() else 0

    def counts(self):
        return {hid: self.runs(hid) for hid in self.cadences}

    def lane_age(self, lane_id):
        """What a seconds-only gate would be judging this lane by, right now."""
        rec = json.loads((self.state / "runs.json").read_text())["lanes"][lane_id]
        return age_of(rec["finished_at"])

    def runner_block(self):
        return json.loads((self.state / "runs.json").read_text())["runner"]


class TheTickGate(unittest.TestCase):
    """Seven firings of the one job, spaced the way launchd spaces them."""

    TICKS = 7

    def sequence(self, tmp, cadences):
        """Fire the job TICKS times, advancing the clock between firings exactly as
        launchd does: the next firing lands one interval after this one STARTED, so a
        lane that finished INSIDE_TICK_S seconds in is `interval - INSIDE_TICK_S` old
        when the next firing asks it. Returns the run count per lane after each tick."""
        m = Scheduler(tmp, cadences)
        seen = []
        for _ in range(self.TICKS):
            m.fire()
            seen.append(m.counts())
            m.advance(m.interval_s - INSIDE_TICK_S)
        return m, seen

    def test_a_lane_whose_cadence_is_the_tick_runs_on_every_single_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, seen = self.sequence(tmp, {"onthetick": INTERVAL})
            got = [s["onthetick"] for s in seen]
            self.assertEqual(got, list(range(1, self.TICKS + 1)),
                             "a lane declaring the %ss tick as its cadence did not mirror on "
                             "every tick: the run counts after each of %d ticks were %s. "
                             "Measured from its own finish it is only %ss old when the next "
                             "tick asks, so a seconds-only gate skips it and it mirrors every "
                             "%ss -- half the rate it declares, and nothing says so."
                             % (INTERVAL, self.TICKS, got, INTERVAL - INSIDE_TICK_S, 2 * INTERVAL))

    def test_the_seconds_gate_alone_would_have_skipped_every_one_of_those_ticks(self):
        """The other half of that proof: this sequence really is the losing one. If the
        lane were ever a full cadence old at a firing, a seconds-only gate would have
        passed it too and the test above would prove nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            m = Scheduler(tmp, {"onthetick": INTERVAL})
            for k in range(1, self.TICKS + 1):
                m.fire()
                m.advance(m.interval_s - INSIDE_TICK_S)
                self.assertLess(m.lane_age("onthetick"), INTERVAL,
                                "after tick %d the lane's own record was already a full cadence "
                                "old. Either it was skipped on a tick and has been ageing since "
                                "-- which is the halving itself -- or the launchd spacing this "
                                "file exists to simulate is not being simulated." % k)

    def test_a_longer_cadence_still_paces_itself_and_never_runs_faster(self):
        """Three times the tick: it may mirror on one tick in three, and on no other."""
        with tempfile.TemporaryDirectory() as tmp:
            _, seen = self.sequence(tmp, {"onthetick": INTERVAL, "slow": 3 * INTERVAL})
            got = [s["slow"] for s in seen]
            self.assertEqual(got, [1, 1, 1, 2, 2, 2, 3],
                             "a lane declaring %ss over a %ss tick mirrored on the wrong ticks: "
                             "the counts after each tick were %s. It runs on one tick in three, "
                             "the first one included, and on none in between."
                             % (3 * INTERVAL, INTERVAL, got))
            self.assertEqual(seen[-1]["onthetick"], self.TICKS,
                             "the lane beside it stopped mirroring; this proves nothing")

    def test_the_slow_lane_is_carried_by_the_turn_of_the_wheel_not_by_the_clock(self):
        """At the tick it runs on, it is still SHORT of its cadence in seconds, so nothing
        but the count of ticks can have made it due. That is what keeps the rule correct on
        a scheduler whose firings are spaced from the previous START."""
        with tempfile.TemporaryDirectory() as tmp:
            m = Scheduler(tmp, {"slow": 3 * INTERVAL})
            m.fire()
            self.assertEqual(m.runs("slow"), 1, "the first tick has to run it")
            age = None
            for _ in range(3):
                m.advance(m.interval_s - INSIDE_TICK_S)
                age = m.lane_age("slow")
                m.fire()
            self.assertLess(age, 3 * INTERVAL,
                            "by the tick it ran on, the lane was already a full cadence old: a "
                            "seconds-only gate would have run it too, so this proves nothing")
            self.assertEqual(m.runs("slow"), 2,
                             "the fourth tick was its turn and it did not mirror")

    def test_a_machine_that_slept_through_its_turns_still_gets_one(self):
        """The wall clock stays on as a second door. launchd coalesces a whole sleep into
        one firing, so a laptop shut for hours owes a slow lane turns it never gets back.
        That door can only ever open EARLIER in ticks, never sooner in seconds than the
        lane's own declared cadence."""
        with tempfile.TemporaryDirectory() as tmp:
            m = Scheduler(tmp, {"slow": 3 * INTERVAL})
            m.fire()
            self.assertEqual(m.runs("slow"), 1)
            m.advance(6 * 3600)             # the lid was shut for six hours: one firing on wake
            m.fire()
            self.assertEqual(m.runs("slow"), 2,
                             "one firing after a six-hour sleep left a lane whose cadence is "
                             "%ss unrun: a count of ticks alone cannot pay back a sleep."
                             % (3 * INTERVAL))

    def test_a_cadence_shorter_than_the_tick_gets_every_tick_and_keeps_its_declaration(self):
        """It asked for more than the scheduler has to give. Every tick is as close as it
        can be served, and the listing still shows the cadence it declared."""
        with tempfile.TemporaryDirectory() as tmp:
            m = Scheduler(tmp, {"eager": 300, "onthetick": INTERVAL})
            for _ in range(3):
                m.fire()
                m.advance(m.interval_s - INSIDE_TICK_S)
            self.assertEqual(m.runs("eager"), 3)
            self.assertIn("300s", m.fire(["--list"]).stdout,
                          "the listing no longer shows the cadence the lane declared")


class AStandDownIsInTheRecord(unittest.TestCase):
    """A tick that finds the lock held mirrors nothing. One of those is a tick that ran
    long; a run of them is a wedge, and the console can only tell them apart if the record
    does. Both flags used to be written here and read by nobody."""

    SMALL = 60          # a short interval, so "held past the whole interval" is testable

    def box(self, tmp):
        return Scheduler(tmp, {"one": self.SMALL}, interval_s=self.SMALL)

    def hold_lock(self, m, age_s):
        """A tick already in flight: the lock it holds, as old as it has been running."""
        lock = m.state / "runner.lock"
        lock.mkdir()
        t = time.time() - age_s
        os.utime(lock, (t, t))
        return lock

    def test_one_stand_down_is_counted_and_stamped_and_stays_off_the_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.box(tmp)
            m.fire()
            self.hold_lock(m, 5)                     # a tick that started five seconds ago
            r = m.fire()
            self.assertEqual(r.stderr, "", "a fresh overlap is normal and says nothing")
            b = m.runner_block()
            self.assertTrue(b["skipped_overlap"], "the stand-down is not in the record at all")
            self.assertEqual(b.get("stand_downs"), 1,
                             "the record cannot count stand-downs, so a runner wedged behind a "
                             "lock reads exactly like a tick that ran long: %s" % b)
            self.assertTrue(b.get("stand_down_since"),
                            "nothing in the record says WHEN the runner stopped getting through")
            self.assertLess(age_of(b["stand_down_since"]), 120)
            self.assertEqual(m.runs("one"), 1, "a lane ran while another tick held the lock")

    def test_a_run_of_them_accumulates_so_a_wedge_can_be_told_from_a_long_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.box(tmp)
            m.fire()
            self.hold_lock(m, 5)
            m.fire()
            first = m.runner_block().get("stand_down_since")
            m.fire()
            m.fire()
            b = m.runner_block()
            self.assertEqual(b.get("stand_downs"), 3,
                             "three ticks in a row mirrored nothing and the record counts %s"
                             % b.get("stand_downs"))
            self.assertEqual(b.get("stand_down_since"), first,
                             "the first-seen stamp moved, so the streak reads as new on every "
                             "tick and its length can never be seen")

    def test_a_tick_holding_the_lock_past_the_whole_interval_takes_the_stream(self):
        """The one stand-down that is a runner-level fault: no lane is visited, no lane log
        grows, and the reclaim that would say so is another interval away. Under the
        scheduler this stream is the job's error log, which the console counts."""
        with tempfile.TemporaryDirectory() as tmp:
            m = self.box(tmp)
            m.fire()
            self.hold_lock(m, self.SMALL + 20)       # past the interval, not yet stale
            r = m.fire()
            self.assertTrue(r.stderr.strip(),
                            "a tick wedged behind a lock for longer than the whole interval "
                            "stood down in silence: no lane mirrored and nothing said so")
            self.assertIn("stood down", r.stderr)
            self.assertIn("runner.lock", r.stderr, "the line does not name the lock")
            self.assertGreaterEqual(m.runner_block().get("lock_held_s") or 0, self.SMALL,
                                    "the record does not say how long the lock has been held")

    def test_a_tick_that_gets_through_clears_the_streak(self):
        """Otherwise the first stand-down ever seen stands in the record forever, and the
        console reports a wedge on a machine that is mirroring perfectly."""
        with tempfile.TemporaryDirectory() as tmp:
            m = self.box(tmp)
            m.fire()
            lock = self.hold_lock(m, 5)
            m.fire()
            self.assertEqual(m.runner_block().get("stand_downs"), 1)
            lock.rmdir()                             # the long tick finished
            m.fire()
            b = m.runner_block()
            self.assertFalse(b["skipped_overlap"], b)
            self.assertEqual(b.get("stand_downs"), 0, b)
            self.assertIsNone(b.get("stand_down_since"), b)
            self.assertEqual(m.runs("one"), 2, "the tick that got through mirrored nothing")

    def test_a_reclaimed_lock_stays_in_the_record_and_on_the_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.box(tmp)
            m.fire()
            self.hold_lock(m, 4 * self.SMALL)        # older than twice the interval: dead
            r = m.fire()
            self.assertIn("reclaimed", r.stderr)
            self.assertTrue(m.runner_block()["reclaimed_lock"],
                            "the record does not carry the reclaim, so nothing can tell a tick "
                            "that died from one that never started")
            self.assertEqual(m.runs("one"), 2, "the tick that reclaimed the lock ran nothing")


if __name__ == "__main__":
    unittest.main()
