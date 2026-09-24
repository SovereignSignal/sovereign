"""The judge thinks by default, and CURATOR_REASONING_EFFORT reaches the wire when set.

On 2026-09-23 thinking was 68% of judge time, so the owner switched it off ("none").
It tied on the bake-off corpus and ran 3x faster, but live it lost recall: 1 promote
in its first 100 judgments against ~11% before, and 2 of 10 paired skips flipped to
promote with thinking on. The owner reverted the same day. The default therefore
omits the field, which is what leaves the model's own thinking on; any value set is
sent as-is. Both halves are only real if the request body shows them, so these cases
run the real script against a loopback stub and read what it sent.
"""
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "bin" / "curator-run"
VERDICT = {"promote": False, "reason": "stub verdict"}


class Stub:
    """Loopback model endpoint that records every request body."""

    def __init__(self):
        self.bodies = []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                stub.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                out = json.dumps({"choices": [{"message": {"content": json.dumps(VERDICT)}}]}).encode()
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


def run_once(extra_env):
    """One --dry pass over one raw note, isolated HOME so the real model lock is untouched."""
    home = tempfile.mkdtemp()
    vault = Path(tempfile.mkdtemp())
    (vault / "knowledge" / "concepts").mkdir(parents=True)
    note = vault / "raw" / "tools" / "stub" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntype: capture\nsource: stub\n---\n\n# A note\n\nSomething worth judging.\n",
                    encoding="utf-8")
    stub = Stub()
    try:
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "PYTHONPATH": str(ROOT / "lib"),
               "SOVS_VAULT": str(vault), "CURATOR_LANE": "stubtest",
               "CURATOR_ENDPOINT": stub.url, "CURATOR_SCREEN": ""}
        env.update(extra_env)
        done = subprocess.run([sys.executable, str(CURATOR), "--since-days", "1", "--max", "1", "--dry"],
                              capture_output=True, text=True, timeout=120, env=env)
        return done, stub.bodies
    finally:
        stub.close()


class JudgeReasoningEffort(unittest.TestCase):

    def test_default_omits_the_field_so_the_judge_thinks(self):
        done, bodies = run_once({})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(bodies, "the judge never called the model:\n" + done.stdout + done.stderr)
        for body in bodies:
            self.assertNotIn("reasoning_effort", body)

    def test_a_set_value_is_sent(self):
        done, bodies = run_once({"CURATOR_REASONING_EFFORT": "none"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(bodies, "the judge never called the model:\n" + done.stdout + done.stderr)
        for body in bodies:
            self.assertEqual(body.get("reasoning_effort"), "none")

    def test_the_rest_of_the_body_is_unchanged(self):
        """The refactor into one body builder must not move anything the judge relied on."""
        _, bodies = run_once({})
        body = bodies[0]
        self.assertEqual(body["temperature"], 0.1)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])


if __name__ == "__main__":
    unittest.main()
