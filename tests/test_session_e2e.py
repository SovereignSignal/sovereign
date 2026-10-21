"""One quiet session, end to end through sessions.sh: excerpt, the archive's own model,
captures in the tool's own lane, and the curator able to judge what landed.

The model is a loopback stub named by hub.json, so the archive's one model is the stub.
Strict validation keeps one of the two candidates it returns: the other's body is 150
words. An empty answer is the normal one and writes nothing.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402

SID = "5e551011-0000-4000-8000-00000000e2e1"
VALID = {"title": "Every archive copy stays encrypted",
         "body": "Any copy of the archive that leaves the owner's storage is encrypted first, and the "
                 "owner alone holds the key.",
         "kind": "decision", "confidence": "high", "evidence": ["T1", "T2"]}
LONG = dict(VALID, title="Tests run against the staging copy", body=" ".join(["word"] * 150))
LABELS = ("type", "source", "created", "title", "origin", "session_title", "project", "span",
          "distiller", "prompt", "kind", "confidence", "evidence")


def frontmatter(text):
    head = text.split("---\n")[1]
    return [line.split(":", 1)[0] for line in head.splitlines() if line.strip()], head


class EndToEnd(unittest.TestCase):
    def rig(self, reply_fn):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = fx.Rig(tmp.name, reply_fn)
        self.addCleanup(rig.close)
        return rig

    def test_one_valid_candidate_lands_with_every_label(self):
        rig = self.rig(lambda body: json.dumps({"captures": [VALID, LONG]}))
        rig.transcript(SID)
        r = rig.tick()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 1)
        caps = rig.captures()
        self.assertEqual(len(caps), 1, [p.name for p in caps])
        self.assertTrue(caps[0].name.startswith("every-archive-copy-stays-encrypted-5e551011"), caps[0].name)
        text = caps[0].read_text()
        keys, head = frontmatter(text)
        self.assertEqual(keys, list(LABELS))
        self.assertIn("source: %s\n" % fx.LANE, head)
        self.assertIn("origin: claude-code-session:%s\n" % SID, head)
        self.assertIn("session_title: Synthetic session\n", head)
        self.assertIn("project: proj\n", head)
        self.assertRegex(head, r"span: \d{4}-\d\d-\d\dT\d\d:\d\dZ\.\.\d{4}-\d\d-\d\dT\d\d:\d\dZ\n")
        self.assertIn("distiller: local/qwen-test:8b\n", head)
        self.assertIn("prompt: session-distill/v1\n", head)
        self.assertIn("kind: decision\n", head)
        self.assertIn("confidence: high\n", head)
        self.assertIn("evidence: [T1, T2]\n", head)
        self.assertIn(VALID["body"], text)
        self.assertNotIn("word word word", text)

        row = rig.watermark()["sessions"][SID]
        self.assertEqual(row["verdict"], "distilled")
        self.assertEqual(row["captures"], 1)
        self.assertEqual(row["distiller"], "local/qwen-test:8b")
        self.assertEqual(row["prompt"], "session-distill/v1")
        self.assertEqual(row["project"], "proj")
        manifest = rig.manifest()
        self.assertIn("source: %s" % fx.LANE, manifest)
        self.assertIn("Last run: ", manifest)
        self.assertIn("Sessions this week: distilled 1, captures 1, skipped 0, waiting 0, failed 0, refused 0.",
                      manifest)
        self.assertNotIn("Waiting:", manifest)

        # The curator sees the capture as one new item and judges it.
        with fx.ModelStub(lambda body: json.dumps({"promote": False, "reason": "stub verdict"})) as judge:
            only = Path(rig.tmp) / "only.txt"
            only.write_text(os.path.relpath(str(caps[0]), str(rig.vault)) + "\n")
            env = {"PATH": "/usr/bin:/bin", "HOME": str(rig.home), "PYTHONPATH": str(ROOT / "lib"),
                   "SOVS_VAULT": str(rig.vault), "CURATOR_LANE": "stubtest", "CURATOR_ENDPOINT": judge.url,
                   "CURATOR_SCREEN": ""}
            done = subprocess.run([sys.executable, str(ROOT / "bin" / "curator-run"), "--since-days", "1",
                                   "--only", str(only), "--dry"], capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("judged 1 new item", done.stdout)
            self.assertEqual(judge.calls, 1)
            self.assertIn("Every archive copy stays encrypted", json.dumps(judge.requests[0]))

    def test_an_empty_answer_writes_nothing_and_marks_distilled(self):
        rig = self.rig(lambda body: '{"captures": []}')
        rig.transcript(SID)
        r = rig.tick()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 1)
        self.assertEqual(rig.captures(), [])
        row = rig.watermark()["sessions"][SID]
        self.assertEqual(row["verdict"], "distilled")
        self.assertEqual(row["captures"], 0)
        self.assertIn("distilled 1, captures 0,", rig.manifest())

    def test_skips_are_named_and_counted(self):
        rig = self.rig(lambda body: '{"captures": []}')
        rig.transcript("5e551011-0000-4000-8000-0000000000a1", prompts=["just one prompt"])
        rig.transcript("5e551011-0000-4000-8000-0000000000a2", entrypoint="sdk-py")
        rig.transcript("5e551011-0000-4000-8000-0000000000a3", age_s=60)  # still being written
        r = rig.tick()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(rig.verdict("5e551011-0000-4000-8000-0000000000a1"), "skipped:few-prompts")
        self.assertEqual(rig.verdict("5e551011-0000-4000-8000-0000000000a2"), "skipped:entrypoint")
        self.assertIsNone(rig.verdict("5e551011-0000-4000-8000-0000000000a3"))  # active: unmarked
        self.assertIn("distilled 0, captures 0, skipped 2, waiting 0, failed 0, refused 0.", rig.manifest())


if __name__ == "__main__":
    unittest.main()
