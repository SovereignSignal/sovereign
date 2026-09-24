"""Judge calls may run in parallel; nothing about what is judged or written may change.

On 2026-09-23 the curator was catching up ~2,970 past-due items at ~2 minutes each with
thinking on, one call at a time. CURATOR_JUDGE_PARALLEL lets a few judge calls run at
once against a model server with that many slots. The promise that makes it safe: the
verdicts are consumed in candidate order and matched to their own sources, and the
number in flight never exceeds the setting. These cases hold both against the real
script, with a loopback stub that answers slowly and counts overlap.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "bin" / "curator-run"


class SlowStub:
    """Answers after a delay, echoes the SOURCE it was asked about, and counts overlap."""

    def __init__(self, delay=0.4):
        self.inflight = self.peak = 0
        self.lock = threading.Lock()
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with stub.lock:
                    stub.inflight += 1
                    stub.peak = max(stub.peak, stub.inflight)
                time.sleep(delay)
                src = re.search(r"SOURCE: (\S+)", body["messages"][-1]["content"]).group(1)
                with stub.lock:
                    stub.inflight -= 1
                verdict = {"promote": False, "reason": "judged " + src}
                out = json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()
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


def run(parallel, n=5):
    home, vault = tempfile.mkdtemp(), Path(tempfile.mkdtemp())
    (vault / "knowledge" / "concepts").mkdir(parents=True)
    notes = vault / "raw" / "tools" / "stub"
    notes.mkdir(parents=True)
    now = time.time()
    for i in range(n):
        f = notes / ("note-%d.md" % i)
        f.write_text("---\ntype: capture\nsource: stub\n---\n\n# Note %d\n\nBody %d.\n" % (i, i), encoding="utf-8")
        os.utime(f, (now - i, now - i))          # distinct mtimes: a fixed candidate order
    stub = SlowStub()
    try:
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "PYTHONPATH": str(ROOT / "lib"),
               "SOVS_VAULT": str(vault), "CURATOR_LANE": "stubtest", "CURATOR_ENDPOINT": stub.url,
               "CURATOR_SCREEN": "", "CURATOR_JUDGE_PARALLEL": str(parallel)}
        done = subprocess.run([sys.executable, str(CURATOR), "--since-days", "1", "--max", str(n)],
                              capture_output=True, text=True, timeout=120, env=env)
        lane = vault / "raw" / "workspaces" / "stubtest"
        rows = [json.loads(l) for l in (lane / "judgments.jsonl").read_text().splitlines() if l.strip()] \
            if (lane / "judgments.jsonl").exists() else []
        return done, rows, stub.peak
    finally:
        stub.close()


class JudgeParallel(unittest.TestCase):

    def test_two_in_flight_at_most_and_every_verdict_on_its_own_source(self):
        done, rows, peak = run(2)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(rows), 5, done.stdout + done.stderr)
        self.assertEqual(peak, 2, "the look-ahead should overlap calls, and never past the setting")
        for r in rows:
            self.assertEqual(r["reason"], "judged " + r["source"], "a verdict landed on the wrong source")

    def test_parallel_changes_nothing_that_is_written(self):
        _, seq, peak1 = run(1)
        _, par, _ = run(2)
        self.assertEqual(peak1, 1, "the default must stay one call at a time")
        strip = lambda rows: [(r["source"], r["promote"], r["reason"]) for r in rows]
        self.assertEqual(strip(seq), strip(par), "same sources, same order, same verdicts")


if __name__ == "__main__":
    unittest.main()
