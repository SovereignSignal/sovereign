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
from session_ingest import state  # noqa: E402


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
