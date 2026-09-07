"""The shared connector runner: bin/sov-connectors-run.

One job on this machine runs every tool's write wire, so every property that used to
come free from one launchd job per tool has to be proved here: a failing lane does not
stop the others, a hung lane is killed at its own bound and takes its children with it,
a lane that was not due still records that it was visited, and a lane's own chatter
never reaches the job's stderr.

Nothing is inherited. HOME, the state directory, the manifest and every mirror script
live inside a temp dir: a run that picked up the developer's real ~/.brain-root or
~/.vault-staging would either pass falsely or write into a real vault.
"""
import datetime
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "bin" / "sov-connectors-run"
PY = "/usr/bin/python3"
PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def age_s(ts):
    """Seconds since an ISO-8601 Z stamp written by the runner."""
    d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if not d.tzinfo:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - d).total_seconds()


def mirror(tmp, hid, body, raw=False):
    """A stand-in mirror.sh. Real ones are `set -uo pipefail` (never -e) and end in a
    literal `exit 0`, so the fakes are shaped the same way."""
    d = Path(tmp) / "mirrors" / hid
    d.mkdir(parents=True, exist_ok=True)
    p = d / "mirror.sh"
    p.write_text(body if raw else "#!/bin/bash\nset -uo pipefail\n%s\nexit 0\n" % body)
    p.chmod(0o755)
    return p


def entry(tmp, hid, body, cadence_s=900, timeout_s=60, raw=False, env=None, enabled=True):
    return {"label": "com.sovereign.connector.%s" % hid,
            "mirror": str(mirror(tmp, hid, body, raw)),
            "lane": "%s-testbox" % hid,
            "lane_dir": str(Path(tmp) / "lanes" / hid),
            "cadence_s": cadence_s, "timeout_s": timeout_s, "enabled": enabled,
            "env": env or {}, "registered": "2026-01-01"}


def declare(state, harnesses, interval_s=900):
    state.mkdir(parents=True, exist_ok=True)
    (state / "connectors.json").write_text(json.dumps(
        {"version": 1,
         "runner": {"label": "com.sovereign.connector.runner", "interval_s": interval_s,
                    "state_dir": str(state), "log_dir": str(state / "lanes")},
         "harnesses": harnesses}, indent=2))


class RunnerCase(unittest.TestCase):
    def box(self, tmp):
        state, home, out = Path(tmp) / "state", Path(tmp) / "home", Path(tmp) / "out"
        home.mkdir()
        out.mkdir()
        (home / ".brain-host").write_text("testbox")
        return state, home, out

    def tick(self, state, home, args=(), timeout=120):
        self.assertTrue(RUNNER.exists(), "bin/sov-connectors-run is missing: the shared connector runner has not landed")
        env = {"HOME": str(home), "PATH": PATH, "SOV_STATE_DIR": str(state),
               "SOV_MANIFEST": str(state / "connectors.json")}
        return subprocess.run([PY, str(RUNNER)] + list(args), capture_output=True, text=True,
                              env=env, timeout=timeout)

    def runs(self, state):
        return json.loads((state / "runs.json").read_text())

    # 1. the whole point: one job, every lane, one record each
    def test_every_declared_lane_runs_and_lands_a_fresh_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            ids = ("alpha", "beta", "gamma")
            declare(state, {h: entry(tmp, h, 'echo ran > "%s/%s"' % (out, h)) for h in ids})
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(r.stdout, "", "a normal tick prints nothing to stdout")
            d = self.runs(state)
            self.assertEqual(d["runner"]["lanes_declared"], 3)
            self.assertEqual(d["runner"]["lanes_ran"], 3)
            self.assertEqual(d["runner"]["lanes_failed"], 0)
            self.assertEqual(d["runner"]["lanes_timed_out"], 0)
            self.assertEqual(d["runner"]["host"], "testbox")
            self.assertLess(age_s(d["runner"]["tick_finished"]), 120)
            for h in ids:
                rec = d["lanes"][h]
                self.assertEqual(rec["last_exit"], 0, h)
                self.assertFalse(rec["timed_out"], h)
                self.assertFalse(rec["in_flight"], h)
                self.assertIsNone(rec["skipped"], h)
                self.assertLess(age_s(rec["checked_at"]), 120, h)
                self.assertLess(age_s(rec["finished_at"]), 120, h)
                self.assertTrue((out / h).exists(), h)

    # 2. a failing lane must not stop the others, and its noise must not reach the job
    def test_a_failing_lane_does_not_stop_the_others_or_dirty_the_job_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {
                "good": entry(tmp, "good", 'echo ok > "%s/good"' % out),
                "bad": entry(tmp, "bad", 'echo "boom from the mirror" >&2\nexit 7'),
                "also": entry(tmp, "also", 'echo ok > "%s/also"' % out)})
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0, "a failing lane never changes the runner's exit code")
            d = self.runs(state)
            self.assertEqual(d["lanes"]["bad"]["last_exit"], 7)
            self.assertEqual(d["runner"]["lanes_failed"], 1)
            for h in ("good", "also"):
                self.assertEqual(d["lanes"][h]["last_exit"], 0, h)
                self.assertTrue((out / h).exists(), h)
            self.assertIn("boom from the mirror", (state / "lanes" / "bad.error.log").read_text())
            self.assertNotIn("boom from the mirror", r.stderr)

    # 3. the per-lane time bound, and that killing reaches the mirror's own children
    def test_a_hung_lane_is_killed_at_its_bound_and_takes_its_children_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            orphan = Path(tmp) / "orphan"
            declare(state, {
                "hung": entry(tmp, "hung", '( sleep 3; touch "%s" ) &\nsleep 600' % orphan, timeout_s=2),
                "good": entry(tmp, "good", 'echo ok > "%s/good"' % out)}, interval_s=60)
            t0 = time.time()
            r = self.tick(state, home, timeout=60)
            wall = time.time() - t0
            self.assertEqual(r.returncode, 0)
            self.assertLess(wall, 12, "the tick is bounded by one lane timeout, not by the hung lane")
            d = self.runs(state)
            self.assertEqual(d["lanes"]["hung"]["last_exit"], 124)
            self.assertTrue(d["lanes"]["hung"]["timed_out"])
            self.assertEqual(d["runner"]["lanes_timed_out"], 1)
            self.assertEqual(d["lanes"]["good"]["last_exit"], 0, "the healthy lane still finished")
            self.assertTrue((out / "good").exists())
            time.sleep(3)
            self.assertFalse(orphan.exists(), "the mirror's own child outlived the kill: killpg did not reach it")

    # 4. a mirror is a child, never sourced: `exit 0` on line 1 must not end the tick
    def test_a_mirror_that_exits_immediately_does_not_truncate_the_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {
                "quiet": entry(tmp, "quiet", "#!/bin/bash\nexit 0\n", raw=True),
                "one": entry(tmp, "one", 'echo ok > "%s/one"' % out),
                "two": entry(tmp, "two", 'echo ok > "%s/two"' % out)})
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            d = self.runs(state)
            self.assertEqual(d["runner"]["lanes_ran"], 3)
            for h in ("quiet", "one", "two"):
                self.assertEqual(d["lanes"][h]["last_exit"], 0, h)
            self.assertTrue((out / "one").exists())
            self.assertTrue((out / "two").exists())

    # 5. the anti-silence signal: a lane that was not due still says it was visited
    def test_a_lane_that_is_not_due_is_still_checked_and_says_why_it_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"slow": entry(tmp, "slow", 'date +%%s%%N >> "%s/slow"' % out, cadence_s=3600)})
            self.assertEqual(self.tick(state, home).returncode, 0)
            first = self.runs(state)["lanes"]["slow"]
            self.assertEqual((out / "slow").read_text().count("\n"), 1)
            time.sleep(1.2)
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            d = self.runs(state)
            self.assertEqual(d["runner"]["lanes_due"], 0)
            self.assertEqual(d["runner"]["lanes_ran"], 0)
            rec = d["lanes"]["slow"]
            self.assertEqual(rec["skipped"], "not due")
            self.assertNotEqual(rec["checked_at"], first["checked_at"], "checked_at is stamped every tick")
            self.assertEqual(rec["attempted_at"], first["attempted_at"], "the last real run is still described")
            self.assertEqual(rec["last_exit"], 0)
            self.assertEqual((out / "slow").read_text().count("\n"), 1, "the mirror did not run again")

    def test_force_and_only_ignore_the_cadence_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"slow": entry(tmp, "slow", 'echo x >> "%s/slow"' % out, cadence_s=3600),
                            "other": entry(tmp, "other", 'echo x >> "%s/other"' % out, cadence_s=3600)})
            self.assertEqual(self.tick(state, home).returncode, 0)
            self.assertEqual(self.tick(state, home, ["--force"]).returncode, 0)
            self.assertEqual((out / "slow").read_text().count("\n"), 2)
            self.assertEqual(self.tick(state, home, ["--only", "slow"]).returncode, 0)
            self.assertEqual((out / "slow").read_text().count("\n"), 3)
            self.assertEqual((out / "other").read_text().count("\n"), 2, "--only runs exactly one lane")

    # 6. null is not zero: a clean lane must report 0 error lines, never "no log"
    def test_a_clean_lane_still_has_both_logs_and_zero_error_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"clean": entry(tmp, "clean", 'echo ok > "%s/clean"' % out)})
            self.assertEqual(self.tick(state, home).returncode, 0)
            err = state / "lanes" / "clean.error.log"
            log = state / "lanes" / "clean.log"
            self.assertTrue(err.exists(), "a missing error log reads as 'never ran' in the console")
            self.assertTrue(log.exists())
            self.assertEqual(err.read_text(), "")
            d = self.runs(state)
            self.assertEqual(d["lanes"]["clean"]["stderr"], str(err))
            self.assertEqual(d["lanes"]["clean"]["log"], str(log))

    # 7. two ticks never overlap, and a lock left by a dead tick is reclaimed loudly
    def test_a_second_tick_started_while_one_is_in_flight_launches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"one": entry(tmp, "one", 'echo ok > "%s/one"' % out)})
            (state / "runner.lock").mkdir()
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(self.runs(state)["runner"]["skipped_overlap"])
            self.assertFalse((out / "one").exists())
            self.assertEqual(r.stderr, "", "a fresh lock is normal and says nothing")

    def test_a_lock_left_by_a_dead_tick_is_reclaimed_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"one": entry(tmp, "one", 'echo ok > "%s/one"' % out)}, interval_s=60)
            lock = state / "runner.lock"
            lock.mkdir()
            old = time.time() - 3600
            os.utime(lock, (old, old))
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0)
            d = self.runs(state)
            self.assertTrue(d["runner"]["reclaimed_lock"])
            self.assertIn("reclaimed", r.stderr)
            self.assertTrue((out / "one").exists())
            self.assertFalse(lock.exists(), "the lock is released at the end of the tick")

    # 8. the only two non-zero exits the runner has
    def test_an_unreadable_or_missing_manifest_is_the_runners_own_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, _ = self.box(tmp)
            state.mkdir(parents=True)
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 78, "a missing manifest is a runner fault")
            self.assertTrue(r.stderr.strip())
            (state / "connectors.json").write_text("{ not json")
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 78)
            self.assertTrue(r.stderr.strip())

    # a lane that can outlive a tick would starve the others: refused, and named
    def test_a_lane_whose_timeout_outlives_the_tick_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"greedy": entry(tmp, "greedy", 'echo x > "%s/greedy"' % out, timeout_s=1800),
                            "fine": entry(tmp, "fine", 'echo ok > "%s/fine"' % out, timeout_s=60)},
                    interval_s=900)
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0)
            self.assertIn("greedy", r.stderr)
            self.assertFalse((out / "greedy").exists())
            self.assertTrue((out / "fine").exists())

    def test_a_declared_mirror_that_is_gone_is_reported_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            e = entry(tmp, "gone", 'echo x > "%s/gone"' % out)
            os.remove(e["mirror"])
            declare(state, {"gone": e, "here": entry(tmp, "here", 'echo ok > "%s/here"' % out)})
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0)
            d = self.runs(state)
            self.assertTrue(d["lanes"]["gone"]["mirror_missing"])
            self.assertLess(age_s(d["lanes"]["gone"]["checked_at"]), 120)
            self.assertIn("gone", r.stderr)
            self.assertTrue((out / "here").exists())

    def test_the_child_gets_a_usable_path_and_the_lanes_own_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            body = 'printf \'%s\\n%s\\n\' "$PATH" "$LANE_TOKEN" > "' + str(out) + '/env"'
            declare(state, {"env": entry(tmp, "env", body, env={"LANE_TOKEN": "from-the-manifest"})})
            r = self.tick(state, home)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            path_line, token_line = (out / "env").read_text().splitlines()[:2]
            self.assertIn("/usr/bin", path_line)
            self.assertIn("/usr/local/bin", path_line)
            self.assertEqual(token_line, "from-the-manifest")

    def test_dry_run_and_list_and_an_unknown_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            declare(state, {"one": entry(tmp, "one", 'echo ok > "%s/one"' % out),
                            "two": entry(tmp, "two", 'echo ok > "%s/two"' % out)})
            r = self.tick(state, home, ["--dry-run"])
            self.assertEqual(r.returncode, 0)
            self.assertIn("one", r.stdout)
            self.assertIn("two", r.stdout)
            self.assertFalse((state / "runs.json").exists(), "--dry-run writes nothing")
            self.assertFalse((out / "one").exists())
            r = self.tick(state, home, ["--list"])
            self.assertEqual(r.returncode, 0)
            self.assertIn("one", r.stdout)
            self.assertIn("two", r.stdout)
            self.assertFalse((out / "one").exists())
            self.assertEqual(self.tick(state, home, ["--nonsense"]).returncode, 64)

    def test_the_runner_compiles(self):
        self.assertTrue(RUNNER.exists(), "bin/sov-connectors-run is missing: the shared connector runner has not landed")
        r = subprocess.run([PY, "-m", "py_compile", str(RUNNER)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
