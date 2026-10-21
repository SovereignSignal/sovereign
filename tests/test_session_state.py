"""Session capture config, watermark and call counter, all under the state directory.

The watermark is staged during a tick and committed or discarded after it, possibly in
another process, so a failed publish leaves every session to retry. Calls are counted
the moment they are made and survive a discard, so the daily budget holds.
"""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from session_ingest import prefilter, state  # noqa: E402


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sd = Path(self.tmp.name, "state")

    def test_defaults_when_missing(self):
        cfg = state.load_config(self.sd)
        self.assertEqual(cfg, {
            "version": 1, "tools": {"claude-code": {"enabled": False, "enabled_at": None}},
            "allow": [], "deny": [], "quiet_min": 45, "min_prompts": 3, "min_score": 2,
            "entrypoints": ["cli"],
            "budget": {"calls_per_tick": 3, "chars_per_tick": 60000, "calls_per_day": 30},
            "phrases": {"memory": [], "decision": [], "correction": []}})
        self.assertFalse(self.sd.exists())
        cfg["allow"].append("/x")
        self.assertEqual(state.load_config(self.sd)["allow"], [])

    def test_state_dir_from_env(self):
        old = os.environ.get("SOV_STATE_DIR")
        os.environ["SOV_STATE_DIR"] = str(self.sd)
        self.addCleanup(lambda: os.environ.pop("SOV_STATE_DIR") if old is None
                        else os.environ.__setitem__("SOV_STATE_DIR", old))
        self.assertEqual(state.state_dir(), self.sd)

    def test_save_round_trip_atomic_mode_600(self):
        cfg = state.load_config(self.sd)
        cfg["tools"]["claude-code"].update(enabled=True, enabled_at="2026-10-21T10:00:00Z")
        cfg["deny"] = ["/work/secret"]
        cfg["budget"]["calls_per_tick"] = 1
        state.save_config(self.sd, cfg)
        path = self.sd / "session-capture.json"
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(state.load_config(self.sd), cfg)
        self.assertEqual([p.name for p in self.sd.iterdir()], ["session-capture.json"])

    def test_partial_file_merges_over_defaults(self):
        self.sd.mkdir()
        (self.sd / "session-capture.json").write_text(json.dumps({"budget": {"calls_per_day": 5},
                                                                 "phrases": {"memory": ["park this"]}}))
        cfg = state.load_config(self.sd)
        self.assertEqual(cfg["budget"], {"calls_per_tick": 3, "chars_per_tick": 60000, "calls_per_day": 5})
        self.assertEqual(cfg["phrases"]["memory"], ["park this"])
        self.assertEqual(cfg["tools"]["claude-code"]["enabled"], False)

    def test_invalid_config_raises(self):
        self.sd.mkdir()
        path = self.sd / "session-capture.json"
        for bad in ("not json", "[]", '{"deny": "/x"}', '{"deny": [1]}', '{"deny": ["relative/path"]}',
                    '{"quiet_min": true}', '{"tools": {"claude-code": {"enabled": "yes"}}}'):
            path.write_text(bad)
            with self.assertRaises(ValueError, msg=bad):
                state.load_config(self.sd)
        path.unlink()
        os.symlink(self.tmp.name, path)
        with self.assertRaises(ValueError):
            state.load_config(self.sd)


class NeedsLook(unittest.TestCase):
    def test_cases(self):
        nl = state.needs_look
        self.assertTrue(nl(None, 100, "p"))
        self.assertFalse(nl({"verdict": "distilled", "size": 100}, 100, "p"))
        self.assertFalse(nl({"verdict": "distilled", "size": 100}, 500, "p"))
        self.assertTrue(nl({"verdict": "failed:1", "size": 100}, 100, "p"))
        self.assertTrue(nl({"verdict": "failed:2", "size": 100}, 100, "p"))
        self.assertFalse(nl({"verdict": "failed:3", "size": 100}, 100, "p"))
        self.assertFalse(nl({"verdict": "failed:x", "size": 100}, 100, "p"))
        self.assertFalse(nl({"verdict": "skipped:low-signal", "size": 100}, 100, "p"))
        self.assertTrue(nl({"verdict": "skipped:low-signal", "size": 100}, 120, "p"))
        for v in ("denied", "refused-archive"):
            self.assertFalse(nl({"verdict": v, "size": 100, "policy": "p"}, 100, "p"))
            self.assertTrue(nl({"verdict": v, "size": 100, "policy": "p"}, 120, "p"))
            self.assertTrue(nl({"verdict": v, "size": 100, "policy": "old"}, 100, "p"))
        self.assertTrue(nl({"size": 100}, 100, "p"))


class WatermarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sd = Path(self.tmp.name, "state")
        self.main = self.sd / "sessions" / "claude-code.json"
        self.pending = self.sd / "sessions" / "claude-code.json.pending"

    def row(self, verdict, size=10):
        return {"size": size, "mtime": 1.0, "cwd": "/w", "project": "w", "verdict": verdict,
                "attempts": 1, "captures": 0, "distiller": "m", "prompt": "1", "at": "t", "policy": "p"}

    def test_empty(self):
        wm = state.Watermark(self.sd, "claude-code")
        self.assertEqual(wm.rows, {})
        self.assertIsNone(wm.waiting)
        self.assertFalse(self.main.exists())

    def test_stage_then_discard_leaves_rows(self):
        wm = state.Watermark(self.sd, "claude-code")
        wm.stage("a", self.row("distilled"))
        wm.commit()
        wm.stage("a", self.row("failed:1"))
        wm.stage("b", self.row("skipped:few-prompts"))
        self.assertTrue(self.pending.exists())
        self.assertEqual(mode(self.pending), 0o600)
        self.assertEqual(set(wm.rows), {"a"})
        self.assertEqual(wm.rows["a"]["verdict"], "distilled")
        wm.discard()
        self.assertFalse(self.pending.exists())
        again = state.Watermark(self.sd, "claude-code")
        self.assertEqual(again.rows, {"a": self.row("distilled")})

    def test_commit_merges_across_processes(self):
        state.Watermark(self.sd, "claude-code").stage("a", self.row("distilled"))
        first = state.Watermark(self.sd, "claude-code")
        first.commit()
        tick = state.Watermark(self.sd, "claude-code")
        tick.stage("b", self.row("skipped:low-signal"))
        tick.stage_waiting({"reason": "model unreachable", "since": "2026-10-21T14:05Z"})
        later = state.Watermark(self.sd, "claude-code")  # a separate --commit-tick process
        later.commit()
        self.assertFalse(self.pending.exists())
        self.assertEqual(mode(self.main), 0o600)
        done = state.Watermark(self.sd, "claude-code")
        self.assertEqual(set(done.rows), {"a", "b"})
        self.assertEqual(done.waiting, {"reason": "model unreachable", "since": "2026-10-21T14:05Z"})
        on_disk = json.loads(self.main.read_text())
        self.assertEqual(set(on_disk), {"sessions", "waiting"})
        done.stage_waiting(None)
        done.commit()
        self.assertIsNone(state.Watermark(self.sd, "claude-code").waiting)
        self.assertEqual(set(state.Watermark(self.sd, "claude-code").rows), {"a", "b"})

    def test_calls_survive_discard_and_keep_seven_days(self):
        wm = state.Watermark(self.sd, "claude-code")
        self.assertEqual(wm.calls_today("2026-10-21"), 0)
        wm.stage("a", self.row("distilled"))
        self.assertEqual(wm.record_call("2026-10-21"), 1)
        self.assertEqual(wm.record_call("2026-10-21"), 2)
        wm.discard()
        fresh = state.Watermark(self.sd, "claude-code")
        self.assertEqual(fresh.calls_today("2026-10-21"), 2)
        self.assertEqual(fresh.rows, {})
        calls = self.sd / "sessions" / "claude-code.calls.json"
        self.assertEqual(mode(calls), 0o600)
        for day in ("2026-10-10", "2026-10-15", "2026-10-16"):
            fresh.record_call(day)
        fresh.record_call("2026-10-22")
        self.assertEqual(sorted(json.loads(calls.read_text())),
                         ["2026-10-16", "2026-10-21", "2026-10-22"])

    def test_commit_without_stage_waiting_preserves_waiting(self):
        wm = state.Watermark(self.sd, "claude-code")
        wm.stage_waiting({"reason": "model unreachable", "since": "2026-10-21T14:05Z"})
        wm.commit()
        tick = state.Watermark(self.sd, "claude-code")
        tick.stage("a", self.row("distilled"))
        self.assertNotIn("waiting", json.loads(self.pending.read_text()))
        state.Watermark(self.sd, "claude-code").commit()  # a separate commit process
        done = state.Watermark(self.sd, "claude-code")
        self.assertEqual(done.waiting, {"reason": "model unreachable", "since": "2026-10-21T14:05Z"})
        self.assertEqual(set(done.rows), {"a"})

    def test_stage_waiting_none_clears_it(self):
        wm = state.Watermark(self.sd, "claude-code")
        wm.stage_waiting({"reason": "model unreachable", "since": "2026-10-21T14:05Z"})
        wm.commit()
        tick = state.Watermark(self.sd, "claude-code")
        tick.stage_waiting(None)
        self.assertIsNone(json.loads(self.pending.read_text())["waiting"])
        state.Watermark(self.sd, "claude-code").commit()
        self.assertIsNone(state.Watermark(self.sd, "claude-code").waiting)

    def test_observe_writes_seen_at_once_and_leaves_verdicts(self):
        wm = state.Watermark(self.sd, "claude-code")
        wm.observe("new", 50, 2.0)
        wm.stage("old", self.row("skipped:low-signal", size=100))
        wm.commit()
        wm.observe("old", 120, 3.0)
        wm.stage("old", self.row("failed:1", size=120))
        wm.discard()
        fresh = state.Watermark(self.sd, "claude-code")
        self.assertEqual(set(fresh.rows["new"]), {"seen"})
        self.assertTrue(state.needs_look(fresh.rows["new"], 50, "p"))
        old = fresh.rows["old"]
        self.assertEqual((old["verdict"], old["size"]), ("skipped:low-signal", 100))
        self.assertEqual((old["seen"]["size"], old["seen"]["mtime"]), (120, 3.0))
        self.assertRegex(old["seen"]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        fresh.stage("old", self.row("distilled", size=120))
        fresh.commit()
        self.assertEqual(state.Watermark(self.sd, "claude-code").rows["old"]["seen"]["size"], 120)

    def test_grown_skipped_session_is_quiet_on_the_next_tick(self):
        wm = state.Watermark(self.sd, "claude-code")
        wm.stage("a", self.row("skipped:low-signal", size=100))
        wm.observe("a", 100, 1.0)
        wm.commit()
        now, old_mtime = 10000.0, 1.0
        # Tick 1: the file has grown to 200 since the last tick.
        tick1 = state.Watermark(self.sd, "claude-code")
        self.assertFalse(prefilter.quiet(200, old_mtime, tick1.rows["a"], now, 45))
        tick1.observe("a", 200, old_mtime)
        # Tick 2: same size as tick 1 saw, so quiet, and the verdict-time size differs.
        tick2 = state.Watermark(self.sd, "claude-code")
        row = tick2.rows["a"]
        self.assertTrue(prefilter.quiet(200, old_mtime, row, now, 45))
        self.assertTrue(state.needs_look(row, 200, "p"))

    def test_grown_distilled_session_stays_final(self):
        wm = state.Watermark(self.sd, "claude-code")
        wm.stage("a", self.row("distilled", size=100))
        wm.commit()
        for size in (150, 150, 300, 300):
            tick = state.Watermark(self.sd, "claude-code")
            tick.observe("a", size, 1.0)
            self.assertFalse(state.needs_look(state.Watermark(self.sd, "claude-code").rows["a"], size, "p"))
        self.assertEqual(state.Watermark(self.sd, "claude-code").rows["a"]["verdict"], "distilled")

    def test_corrupt_call_count_raises(self):
        calls = self.sd / "sessions" / "claude-code.calls.json"
        calls.parent.mkdir(parents=True)
        calls.write_text('{"2026-10-21": "many"}')
        with self.assertRaises(ValueError):
            state.Watermark(self.sd, "claude-code").calls_today("2026-10-21")

    def test_bad_tool_name_refused(self):
        for tool in ("../x", "", "a/b", "Claude"):
            with self.assertRaises(ValueError):
                state.Watermark(self.sd, tool)

    def test_corrupt_watermark_raises(self):
        self.main.parent.mkdir(parents=True)
        self.main.write_text('{"sessions": []}')
        with self.assertRaises(ValueError):
            state.Watermark(self.sd, "claude-code")


if __name__ == "__main__":
    unittest.main()
