"""sov import chatgpt: a pasted answer becomes one untrusted capture per memory, and the curator sees each."""
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import brain_local as local  # noqa: E402
import sovereign_import as imp  # noqa: E402

TOKEN = "gh" + "p_" + "y" * 36  # a GitHub token shape, built so the repo's own scan never sees one
ANSWER = f"""Here is what I remember.

## Garden planner project
You're building a garden planner for small urban plots. It has to work fully offline.

## **Preferred stack**
You prefer plain files and SQLite over hosted databases, and you dislike heavy frameworks.

### Working style
You want short answers first, then detail on request. You once pasted {TOKEN} by mistake.

## Too short
Tiny.

## Garden planner project
A second memory under the same title: the planner targets beds under four square metres.
"""


class Split(unittest.TestCase):
    def test_sections_titles_and_short_bodies(self):
        items = imp.split_memories(ANSWER)
        self.assertEqual([t for t, _ in items],
                         ["Garden planner project", "Preferred stack", "Working style", "Garden planner project"])
        self.assertNotIn("Here is what I remember", " ".join(b for _, b in items))

    def test_an_answer_with_no_headings_is_one_memory(self):
        self.assertEqual(imp.split_memories("You build garden software and you work offline first."),
                         [("Imported memory", "You build garden software and you work offline first.")])
        self.assertEqual(imp.split_memories("too short"), [])


class Import(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.root = self.home / "archive"
        local.create(self.root, ROOT)
        self.answer = self.home / "answer.md"
        self.answer.write_text(ANSWER)
        self.lane = self.root / "raw/workspaces/chatgpt-import"
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "BRAIN_ROOT": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1"}

    def sov(self, *args, stdin=None):
        return subprocess.run(["/bin/bash", str(ROOT / "bin/sov"), "import", *args], input=stdin,
                              capture_output=True, text=True, env=self.env, timeout=120)

    def test_no_answer_prints_the_prompt_and_writes_nothing(self):
        r = self.sov("chatgpt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"## <short title>"', r.stdout)
        self.assertIn("Don't guess", r.stdout)
        self.assertFalse(self.lane.exists())
        only = self.sov("chatgpt", "--prompt")
        self.assertEqual(only.stdout.strip(), imp.CHATGPT_PROMPT)

    def test_dry_run_plans_writes_nothing_and_says_it_will_declare_the_lane(self):
        r = self.sov("chatgpt", "--from", str(self.answer))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4 new", r.stdout)
        self.assertIn("chatgpt-garden-planner-project-2", r.stdout)
        self.assertIn("1 secret-shaped value(s) will be redacted", r.stdout)
        self.assertIn("declares the lane", r.stdout)
        self.assertFalse(self.lane.exists())

    def test_apply_writes_one_redacted_capture_per_memory_then_is_a_no_op(self):
        r = self.sov("chatgpt", "--from", "-", "--apply", stdin=ANSWER)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = sorted(p.name for p in self.lane.glob("*.md"))
        self.assertEqual(names, ["LANE.md", "chatgpt-garden-planner-project-2.md", "chatgpt-garden-planner-project.md",
                                 "chatgpt-preferred-stack.md", "chatgpt-working-style.md"])
        style = (self.lane / "chatgpt-working-style.md").read_text()
        self.assertTrue(style.startswith("---\n"), style)
        self.assertIn("type: capture", style)
        self.assertIn("Untrusted until judged", style)
        self.assertNotIn(TOKEN, style)
        self.assertEqual(list((self.root / "knowledge").rglob("chatgpt-*")), [])
        again = self.sov("chatgpt", "--from", str(self.answer), "--apply")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("0 new, 4 already imported", again.stdout)
        self.assertEqual(len(list(self.lane.glob("*.md"))), 5)

    def test_a_later_answer_with_changed_memories_brings_in_only_what_changed(self):
        self.assertEqual(self.sov("chatgpt", "--from", str(self.answer), "--apply").returncode, 0)
        later = ANSWER.replace("It has to work fully offline.", "It has to work offline and sync over Wi-Fi.")
        r = self.sov("chatgpt", "--from", "-", "--apply", stdin=later)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 new, 3 already imported", r.stdout)
        self.assertIn("chatgpt-garden-planner-project-3", r.stdout)
        self.assertIn("sync over Wi-Fi", (self.lane / "chatgpt-garden-planner-project-3.md").read_text())

    def test_a_heading_yaml_would_misread_still_makes_valid_labels(self):
        r = self.sov("chatgpt", "--from", "-", "--apply", stdin="## [Work] C# notes: 2026\nYou write the planner's sync layer in C# and ship it in 2026.\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = next(self.lane.glob("chatgpt-work-c-notes-2026.md")).read_text()
        self.assertIn('title: "[Work] C# notes: 2026"', text)

    def test_an_oversized_or_empty_answer_is_refused(self):
        big = self.home / "big.md"
        big.write_bytes(b"x" * (imp.MAX_INPUT + 1))
        self.assertNotEqual(self.sov("chatgpt", "--from", str(big)).returncode, 0)
        self.assertNotEqual(self.sov("chatgpt", "--from", "-", stdin="nothing").returncode, 0)

    def test_the_curator_judges_every_imported_memory(self):
        """Landing somewhere the curator never walks (raw/imports/) would make the import a silent loss."""
        self.assertEqual(self.sov("chatgpt", "--from", str(self.answer), "--apply").returncode, 0)
        sources = []

        class Model(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"][-1]["content"]
                sources.extend(re.findall(r"SOURCE: (\S+\.md)", text))
                body = json.dumps({"choices": [{"message": {"content": json.dumps({"promote": False, "reason": "t"})}}]})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode())

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = dict(self.env, SOVS_VAULT=str(self.root), CURATOR_LANE="curator", CURATOR_SCREEN="",
                   CURATOR_JUDGE_PARALLEL="1", PYTHONPATH=str(ROOT / "lib"),
                   CURATOR_ENDPOINT="http://127.0.0.1:%d/v1/chat/completions" % server.server_port)
        run = subprocess.run([sys.executable, str(ROOT / "bin/curator-run"), "--max", "20"],
                             env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual({Path(s).name for s in sources},
                         {"chatgpt-garden-planner-project.md", "chatgpt-garden-planner-project-2.md",
                          "chatgpt-preferred-stack.md", "chatgpt-working-style.md"})


if __name__ == "__main__":
    unittest.main()
