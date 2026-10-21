"""A new hubless archive judges what its tools already saved, not only the last two days.

curator-run's first pass, with no watermark, looks back two days by mtime. The connectors
copy memory with rsync -a, which keeps each file's original time, so a newcomer who
connects Claude Code lands months of memory in raw/ and the curator never judges any of
it. A hub drains that backlog with its own burndown job; the hubless curator has none, so
its watermark starts at zero instead. A lane that has already run keeps its watermark.
"""
import http.server
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import brain_local as local  # noqa: E402


def sov_curator():
    loader = importlib.machinery.SourceFileLoader("sov_curator_backfill", str(ROOT / "bin/sov-curator"))
    spec = importlib.util.spec_from_loader("sov_curator_backfill", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FirstPassBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.root = self.home / "archive"
        local.create(self.root, ROOT)
        self.lane = self.root / "raw/workspaces/curator"
        self.sources = []
        test = self

        class Model(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"][-1]["content"]
                test.sources += re.findall(r"SOURCE: (\S+\.md)", text)
                result = {"promote": False, "reason": "synthetic"}
                body = json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def memory(self, name, days_old):
        path = self.root / "raw/tools/claude-code-test/memory/-proj" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name[:-3]}\n---\nThe owner is building a garden planner ({name}).\n")
        stamp = time.time() - days_old * 86400
        os.utime(path, (stamp, stamp))

    def curate(self):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "SOVS_VAULT": str(self.root),
               "CURATOR_LANE": "curator", "CURATOR_SCREEN": "", "CURATOR_JUDGE_PARALLEL": "1",
               "PYTHONPATH": str(ROOT / "lib"), "PYTHONDONTWRITEBYTECODE": "1",
               "CURATOR_ENDPOINT": "http://127.0.0.1:%d/v1/chat/completions" % self.server.server_port}
        run = subprocess.run([sys.executable, str(ROOT / "bin/curator-run"), "--max", "20"],
                             env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return {Path(s).name for s in self.sources}

    def test_without_the_seed_older_memory_is_never_judged(self):
        """The defect, held in place so the seed's reason stays visible."""
        self.memory("old.md", 30)
        self.memory("new.md", 0)
        self.assertEqual(self.curate(), {"new.md"})

    def test_a_new_archive_judges_everything_already_saved(self):
        self.memory("old.md", 30)
        self.memory("new.md", 0)
        sov_curator().seed_backfill(self.root)
        self.assertEqual(self.curate(), {"old.md", "new.md"})

    def test_a_lane_that_has_run_keeps_its_watermark(self):
        self.lane.mkdir(parents=True, exist_ok=True)
        (self.lane / ".last-run").write_text("1700000000.0")
        sov_curator().seed_backfill(self.root)
        self.assertEqual((self.lane / ".last-run").read_text(), "1700000000.0")

    def test_enable_and_run_both_seed_before_the_first_pass(self):
        source = (ROOT / "bin/sov-curator").read_text()
        for fn in ("def enable(", "def run("):
            body = source[source.index(fn):]
            body = body[:body.index("\ndef ", 1)]
            self.assertIn("seed_backfill(root)", body, fn)


if __name__ == "__main__":
    unittest.main()
