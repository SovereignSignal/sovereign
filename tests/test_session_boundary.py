"""The boundary: transcripts never enter the archive, nothing the reader drops reaches the
model or a capture, sessions that ran inside an archive are refused outright, and a
fresh install calls nothing and writes nothing until the owner turns capture on.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import brain_local  # noqa: E402
import session_fixtures as fx  # noqa: E402
from test_connectors_install import Box  # noqa: E402

VALID = {"title": "Every archive copy stays encrypted",
         "body": "Any copy of the archive that leaves the owner's storage is encrypted first.",
         "kind": "decision", "confidence": "high", "evidence": ["T1"]}


def valid(body):
    return json.dumps({"captures": [VALID]})


class Boundary(unittest.TestCase):
    def rig(self, reply_fn=valid, **cfg):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = fx.Rig(tmp.name, reply_fn, **cfg)
        self.addCleanup(rig.close)
        return rig

    def test_nothing_dropped_reaches_the_model_or_the_lane(self):
        rig = self.rig()
        for i in range(2):
            rig.transcript("5e551011-0000-4000-8000-0000000000c%d" % i)
        r = rig.tick()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 2)
        self.assertEqual(len(rig.captures()), 2)
        sent = json.dumps(rig.stub.requests)
        lane_text = "".join(p.read_text() for p in rig.lane.rglob("*") if p.is_file())
        for marker in fx.MARKERS:
            self.assertNotIn(marker, sent)
            self.assertNotIn(marker, lane_text)
        for key in fx.KEYS:
            self.assertNotIn(key, sent)
            self.assertNotIn(key, lane_text)
        self.assertNotIn(str(rig.proj), sent)  # the project's folder name only, never its path
        self.assertEqual([str(p) for p in rig.vault.rglob("*.jsonl")], [])

    def test_sessions_that_ran_inside_an_archive_are_refused(self):
        rig = self.rig()
        second = Path(brain_local.create(rig.tmp / "second", ROOT)["root"])
        link = rig.tmp / "work" / "shortcut"
        link.symlink_to(rig.vault / "workstreams")
        cases = {"5e551011-0000-4000-8000-0000000000d1": {"cwd": rig.vault},
                 "5e551011-0000-4000-8000-0000000000d2": {"cwd": second / "workstreams"},
                 "5e551011-0000-4000-8000-0000000000d3": {"cwd": link},
                 "5e551011-0000-4000-8000-0000000000d4": {"extra_cwds": [str(rig.vault / "knowledge")]}}
        for sid, kw in cases.items():
            rig.transcript(sid, **kw)
        r = rig.tick()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 0)
        for sid in cases:
            self.assertEqual(rig.verdict(sid), "refused-archive", sid)
        self.assertEqual(rig.captures(), [])
        self.assertIn("refused 4.", rig.manifest())

    def test_a_denied_project_is_never_read_past_its_cwd(self):
        rig = self.rig(deny=[])
        cfg = json.loads((rig.state / "session-capture.json").read_text())
        cfg["deny"] = [str(rig.proj)]
        (rig.state / "session-capture.json").write_text(json.dumps(cfg))
        rig.transcript("5e551011-0000-4000-8000-0000000000e1")
        self.assertEqual(rig.tick().returncode, 0)
        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(rig.verdict("5e551011-0000-4000-8000-0000000000e1"), "denied")

    def test_off_is_silent(self):
        rig = self.rig(enabled=False)
        rig.transcript("5e551011-0000-4000-8000-0000000000f1")
        r = rig.tick()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(rig.stub.calls, 0)
        self.assertFalse(rig.sessions.exists())
        self.assertFalse((rig.state / "sessions").exists())

    def test_a_guard_refusal_makes_no_call_and_says_why(self):
        rig = self.rig()
        (rig.state / "hub.json").unlink()   # hubless: the owner's provider, Anthropic by default
        rig.transcript("5e551011-0000-4000-8000-0000000000f2")
        r = rig.tick(CURATOR_LOCAL_ONLY="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(rig.captures(), [])
        self.assertIsNone(rig.verdict("5e551011-0000-4000-8000-0000000000f2"))
        self.assertIn("Waiting: needs a local model on this archive.", rig.manifest())
        self.assertEqual(rig.watermark()["waiting"]["reason"], "needs a local model on this archive")


class OffByDefault(unittest.TestCase):
    """A fresh `sov connect claude-code` declares the session wire beside the memory
    mirror, and that wire calls nothing and writes nothing until the owner turns it on."""

    def test_fresh_install_calls_nothing_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, fx.ModelStub(valid) as stub:
            b = Box(tmp)
            b.state.mkdir(parents=True, exist_ok=True)
            (b.state / "hub.json").write_text(json.dumps(
                {"vault": str(b.vault), "lane": "curator", "model": "qwen-test:8b", "endpoint": stub.url}))
            fx.transcript(b.home, "-work-proj", "5e551011-0000-4000-8000-000000000a01", tmp, list(fx.PROMPTS))
            r = b.connect("claude-code")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            m = b.manifest()["harnesses"]
            self.assertEqual(sorted(m), ["claude-code", "claude-code-sessions"])
            wire = m["claude-code-sessions"]
            self.assertEqual(wire["parent"], "claude-code")
            self.assertTrue(wire["mirror"].endswith("connectors/harness/claude-code/sessions.sh"))
            self.assertEqual(wire["lane_dir"], m["claude-code"]["lane_dir"] + "/sessions")
            self.assertEqual((wire["cadence_s"], wire["timeout_s"]), (900, 300))
            self.assertEqual(wire["lane"], m["claude-code"]["lane"])

            time.sleep(1.1)
            tick = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-connectors-run"), "--force"],
                                  capture_output=True, text=True, env=b.env(), timeout=300)
            self.assertEqual(tick.returncode, 0, tick.stdout + tick.stderr)
            runs = json.loads((b.state / "runs.json").read_text())
            self.assertEqual(runs["lanes"]["claude-code-sessions"]["last_exit"], 0)
            self.assertEqual(stub.calls, 0)
            self.assertFalse(Path(wire["lane_dir"]).exists())
            self.assertFalse((b.state / "sessions").exists())

            r = b.disconnect("claude-code")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {})

    def test_disconnect_all_takes_the_session_wire_with_its_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            self.assertEqual(b.connect("claude-code").returncode, 0)
            self.assertIn("claude-code-sessions", b.manifest()["harnesses"])
            r = subprocess.run(["/bin/bash", str(ROOT / "bin" / "sov"), "disconnect", "all", "--apply"],
                               capture_output=True, text=True, env=b.env(), timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("claude-code-sessions", r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {})


if __name__ == "__main__":
    unittest.main()
