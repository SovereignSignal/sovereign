"""A document stored as bounded parts is judged once, whole.

The SovsClaw intake keeps long documents as <document>-pNN-<capture>.md parts, each cut
at a byte boundary, often mid-word. Judged alone, a part reads as truncated: on
2026-09-23 the judge answered TRUNCATED on parts that ended "signer/secre", and each
part's hash then sealed it, so 542 unjudged parts were headed the same way. The curator
now reads the whole document and judges it once. These cases hold that against the real
script: one model call per document, the text joined exactly, one frontmatter, every
part recorded as judged, and nothing judged again on the next run.
"""
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "bin" / "curator-run"
DOC = "evidence-a5e3d0a3c1dc62a4"


def part(n, total, source):
    return ('---\ntype: "capture"\nsource: "client:demo/plan.md"\nclient_id: "demo"\n'
            'source_id: "%s-p%02d"\n---\n\n# plan\n\nSource document. Historical evidence.\n'
            'Part: %d/%d\n\n<!-- retained-source-begin -->\n%s\n<!-- retained-source-end -->\n'
            % (DOC, n, n, total, source))


class Stub:
    def __init__(self):
        self.users = []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.users.append(body["messages"][-1]["content"])
                out = json.dumps({"choices": [{"message": {"content": json.dumps(
                    {"promote": False, "reason": "stub"})}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class SplitDocuments(unittest.TestCase):

    def setUp(self):
        self.home, self.vault = tempfile.mkdtemp(), Path(tempfile.mkdtemp())
        (self.vault / "knowledge" / "concepts").mkdir(parents=True)
        lane = self.vault / "raw" / "workspaces" / "demo"
        lane.mkdir(parents=True)
        chunks = ["PART-ONE keeps the signer/secre", "t files apart. PART-TWO then persists before broad",
                  "cast. PART-THREE closes the loop."]
        for i, c in enumerate(chunks, 1):
            (lane / ("%s-p%02d-%s.md" % (DOC, i, ("%x" % i) * 64))).write_text(part(i, 3, c), encoding="utf-8")
        (lane / "plain-note.md").write_text("---\ntype: capture\n---\n\n# A note\n\nWhole on its own.\n",
                                           encoding="utf-8")
        self.lane_state = self.vault / "raw" / "workspaces" / "stubtest"

    def run_curator(self, stub):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "PYTHONPATH": str(ROOT / "lib"),
               "SOVS_VAULT": str(self.vault), "CURATOR_LANE": "stubtest", "CURATOR_ENDPOINT": stub.url,
               "CURATOR_SCREEN": ""}
        return subprocess.run([sys.executable, str(CURATOR), "--since-days", "1", "--max", "10"],
                              capture_output=True, text=True, timeout=120, env=env)

    def rows(self):
        f = self.lane_state / "judgments.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []

    def test_one_call_per_document_and_the_text_joined_exactly(self):
        stub = Stub()
        try:
            done = self.run_curator(stub)
        finally:
            stub.close()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(stub.users), 2, "one call for the split document, one for the note")
        doc = next(u for u in stub.users if "PART-ONE" in u)
        self.assertIn("signer/secret files apart", doc, "parts are cut mid-word and must join exactly")
        self.assertIn("persists before broadcast", doc)
        self.assertLess(doc.index("PART-ONE"), doc.index("PART-TWO"))
        self.assertLess(doc.index("PART-TWO"), doc.index("PART-THREE"))
        self.assertEqual(doc.count('client_id: "demo"'), 1, "one frontmatter, the first part's")
        self.assertEqual(doc.count("retained-source-begin"), 1)
        self.assertIn("Parts: all 3, reassembled", doc)
        self.assertNotIn("Part: 1/3", doc)

    def test_every_part_is_recorded_and_nothing_is_judged_twice(self):
        stub = Stub()
        try:
            self.run_curator(stub)
            rows = self.rows()
            parts = [r for r in rows if DOC in r["source"]]
            self.assertEqual(len(parts), 3, "all three parts count as judged")
            folded = [r for r in parts if r.get("judged_with")]
            self.assertEqual(len(folded), 2)
            rep = {r["judged_with"] for r in folded}
            self.assertEqual(len(rep), 1)
            self.assertIn(rep.pop(), {r["source"] for r in parts if not r.get("judged_with")})
            calls = len(stub.users)
            self.run_curator(stub)
            self.assertEqual(len(stub.users), calls, "a second run judges nothing again")
        finally:
            stub.close()


    def test_source_for_prints_the_whole_document_without_the_model_lock(self):
        """Paired re-judges read the judge's text through --source-for; it must be the
        pipeline's own text and must never wait on, or create, the model lock."""
        rel = next((self.vault / "raw" / "workspaces" / "demo").glob(DOC + "-p02-*.md"))
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "PYTHONPATH": str(ROOT / "lib"),
               "SOVS_VAULT": str(self.vault), "CURATOR_LANE": "stubtest"}
        done = subprocess.run([sys.executable, str(CURATOR), "--source-for", str(rel)],
                              capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("signer/secret files apart", done.stdout)
        self.assertIn("PART-THREE", done.stdout)
        self.assertFalse((Path(self.home) / ".local" / "state" / "sovs-cron" / "model.lock").exists())


if __name__ == "__main__":
    unittest.main()
