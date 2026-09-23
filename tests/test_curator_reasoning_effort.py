"""The judge answers without thinking, and that setting reaches the wire.

On 2026-09-23 the Ollama log showed 68% of judge time was qwen3.8 thinking (median
843 tokens a call) that curator-run never reads; the bake-off corpus scored thinking
off at 19/20 against 18/20 with no false promotes either way, at a third of the time.
The owner switched it off. The setting is only real if the request body carries it,
so these cases run the real script against a loopback stub and read what it sent.

Empty CURATOR_REASONING_EFFORT must omit the field entirely: that is how an owner
puts back the model's own default, and how a model that rejects the field is judged.
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

    def test_default_sends_none(self):
        done, bodies = run_once({})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(bodies, "the judge never called the model:\n" + done.stdout + done.stderr)
        for body in bodies:
            self.assertEqual(body.get("reasoning_effort"), "none")

    def test_empty_omits_the_field(self):
        done, bodies = run_once({"CURATOR_REASONING_EFFORT": ""})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(bodies, "the judge never called the model:\n" + done.stdout + done.stderr)
        for body in bodies:
            self.assertNotIn("reasoning_effort", body)

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
