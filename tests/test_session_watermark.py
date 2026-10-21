"""The watermark: each session is distilled once, retried a bounded number of times, and
a tick that cannot publish leaves every session to retry.

Every case runs the shipped sessions.sh against a loopback model, so a call that should
not happen shows up in the stub's count.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402
import curator_inference  # noqa: E402
from session_ingest import run  # noqa: E402

SID = "5e551011-0000-4000-8000-0000000000b1"
VALID = {"title": "Every archive copy stays encrypted",
         "body": "Any copy of the archive that leaves the owner's storage is encrypted first.",
         "kind": "decision", "confidence": "high", "evidence": ["T1"]}


def valid(body):
    return json.dumps({"captures": [VALID]})


class Watermark(unittest.TestCase):
    def rig(self, reply_fn=valid, **cfg):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = fx.Rig(tmp.name, reply_fn, **cfg)
        self.addCleanup(rig.close)
        return rig

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_second_pass_makes_no_call(self):
        rig = self.rig()
        rig.transcript(SID)
        self.ok(rig.tick())
        self.ok(rig.tick())
        self.assertEqual(rig.stub.calls, 1)
        self.assertEqual(len(rig.captures()), 1)

    def test_a_grown_distilled_file_is_never_distilled_again(self):
        rig = self.rig()
        path = rig.transcript(SID)
        self.ok(rig.tick())
        with open(path, "a") as fh:
            fh.write(json.dumps({"type": "user", "sessionId": SID, "cwd": str(rig.proj),
                                 "message": {"role": "user", "content": "One more thing to remember."}}) + "\n")
        old = time.time() - 3600
        os.utime(path, (old, old))
        self.ok(rig.tick())   # grown since the last tick: not quiet
        self.ok(rig.tick())   # quiet again, and distilled is final
        self.assertEqual(rig.stub.calls, 1)
        self.assertEqual(rig.verdict(SID), "distilled")

    def test_an_unparseable_reply_fails_then_a_valid_one_distils(self):
        replies = iter(["I found nothing to say.", json.dumps({"captures": [VALID]})])
        rig = self.rig(lambda body: next(replies))
        rig.transcript(SID)
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(SID), "failed:1")
        self.assertIn("failed 1", rig.manifest())
        self.assertEqual(rig.captures(), [])
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(SID), "distilled")
        self.assertEqual(rig.stub.calls, 2)
        self.assertEqual(len(rig.captures()), 1)

    def test_failures_stop_after_three(self):
        rig = self.rig(lambda body: "no json here")
        rig.transcript(SID)
        for n in (1, 2, 3):
            self.ok(rig.tick())
            self.assertEqual(rig.verdict(SID), "failed:%d" % n)
        self.ok(rig.tick())
        self.assertEqual(rig.stub.calls, 3)
        self.assertEqual(rig.verdict(SID), "failed:3")

    def test_an_outage_leaves_the_session_pending_and_waits(self):
        rig = self.rig()
        rig.transcript(SID)
        rig.hub_json("http://127.0.0.1:9/v1/chat/completions")   # nothing listens: no HTTP response
        self.ok(rig.tick())
        self.assertIsNone(rig.verdict(SID))
        self.assertEqual(rig.watermark()["waiting"]["reason"], "model unreachable")
        self.assertRegex(rig.manifest(), r"Waiting: model unreachable since \d{4}-\d\d-\d\dT\d\d:\d\dZ\.")
        self.assertIn("waiting 1", rig.manifest())
        rig.hub_json(rig.stub.url)
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(SID), "distilled")
        self.assertIsNone(rig.watermark()["waiting"])
        self.assertNotIn("Waiting:", rig.manifest())

    def test_a_422_answer_fails_the_session_and_the_tick_goes_on(self):
        bad, good = "5e551011-0000-4000-8000-0000000000h1", "5e551011-0000-4000-8000-0000000000h2"

        def reply(body):
            return 422 if "HTTP-REJECTED" in json.dumps(body) else json.dumps({"captures": [VALID]})
        rig = self.rig(reply)
        rig.transcript(bad, prompts=["Remember HTTP-REJECTED always."] + list(fx.PROMPTS[1:]), age_s=7200)
        rig.transcript(good)
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(bad), "failed:1")
        self.assertEqual(rig.verdict(good), "distilled")      # the same tick went on to it
        self.assertEqual(rig.stub.calls, 2)
        self.assertIsNone(rig.watermark()["waiting"])
        self.assertNotIn("Waiting:", rig.manifest())
        for n in (2, 3):
            self.ok(rig.tick())
            self.assertEqual(rig.verdict(bad), "failed:%d" % n)
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(bad), "failed:3")          # terminal
        self.assertEqual(rig.stub.calls, 4)

    def test_a_refused_capture_fails_its_session_alone(self):
        poison_sid, good_sid = "5e551011-0000-4000-8000-0000000000p1", "5e551011-0000-4000-8000-0000000000g1"
        poison = [dict(VALID, title="Written then taken back again"),
                  dict(VALID, title="Frontmatter body", body="---\ntype: entity\n---\nnot a body")]

        def reply(body):
            return json.dumps({"captures": poison if "POISON-PROMPT" in json.dumps(body) else [VALID]})
        rig = self.rig(reply)
        rig.transcript(poison_sid, prompts=["Remember POISON-PROMPT always."] + list(fx.PROMPTS[1:]), age_s=7200)
        rig.transcript(good_sid)
        r = rig.tick()
        self.ok(r)
        self.assertEqual(rig.stub.calls, 2)
        self.assertEqual(rig.verdict(poison_sid), "failed:1")
        self.assertEqual(rig.verdict(good_sid), "distilled")
        names = [p.name for p in rig.captures()]
        self.assertEqual(names, ["every-archive-copy-stays-encrypted-5e551011.md"])
        vault_text = "".join(p.read_bytes().decode("utf-8", "ignore") for p in rig.vault.rglob("*") if p.is_file())
        self.assertNotIn("Written then taken back", vault_text)
        self.assertNotIn(poison_sid, vault_text)
        self.assertIn("failed 1", rig.manifest())
        self.assertIn("Items mirrored: 1. Failed: 2.", rig.manifest())

    def test_a_rate_limit_or_a_server_fault_is_an_outage(self):
        for code in (429, 503):
            rig = self.rig(lambda body, code=code: code)
            rig.transcript(SID, age_s=7200)
            rig.transcript("5e551011-0000-4000-8000-0000000000b2")
            for _ in range(3):
                self.ok(rig.tick())
            self.assertEqual([r.get("verdict") for r in rig.watermark()["sessions"].values()], [None, None], code)
            self.assertEqual(rig.watermark()["waiting"]["reason"], "model unreachable")
            self.assertIn("Waiting: model unreachable since", rig.manifest())
            self.assertEqual(rig.stub.calls, 3, code)          # one call a tick, then calls close

    def test_an_auth_answer_waits_on_configuration(self):
        rig = self.rig(lambda body: 401)
        rig.transcript(SID, age_s=7200)
        rig.transcript("5e551011-0000-4000-8000-0000000000b2")
        self.ok(rig.tick())
        self.assertEqual(rig.stub.calls, 1)
        self.assertIsNone(rig.verdict(SID))
        self.assertTrue(rig.watermark()["waiting"]["reason"].startswith("HTTP 401"))
        self.assertIn("Waiting: model refused this configuration since", rig.manifest())

    def test_an_outage_across_three_ticks_fails_no_session(self):
        rig = self.rig()
        rig.transcript(SID, age_s=7200)
        rig.transcript("5e551011-0000-4000-8000-0000000000b2")
        rig.hub_json("http://127.0.0.1:9/v1/chat/completions")
        for _ in range(3):
            self.ok(rig.tick())
        rows = rig.watermark()["sessions"]
        self.assertEqual([r.get("verdict") for r in rows.values()], [None, None])
        self.assertEqual(rig.watermark()["waiting"]["reason"], "model unreachable")
        self.assertIn("failed 0", rig.manifest())
        self.assertIn("waiting 2", rig.manifest())

    def test_unreachable_stops_the_ticks_calls(self):
        rig = self.rig()
        for i in range(3):
            rig.transcript("5e551011-0000-4000-8000-00000000000%d" % i)
        rig.hub_json("http://127.0.0.1:9/v1/chat/completions")  # nothing listens on the discard port
        self.ok(rig.tick())
        rows = rig.watermark()["sessions"]
        self.assertEqual([r.get("verdict") for r in rows.values()], [None, None, None])
        self.assertEqual(json.loads((rig.state / "sessions" / "claude-code.calls.json").read_text()),
                         {time.strftime("%Y-%m-%d", time.gmtime()): 1})

    def test_budget_of_one_drains_three_over_three_ticks_oldest_first(self):
        rig = self.rig(budget={"calls_per_tick": 1})
        sids = ["5e551011-0000-4000-8000-00000000000%d" % i for i in range(3)]
        for i, sid in enumerate(sids):
            rig.transcript(sid, prompts=["Remember the order marker ORDER-%d." % i] + list(fx.PROMPTS[1:]),
                           age_s=3 * 3600 - i * 3600)
        for n in (1, 2, 3):
            self.ok(rig.tick())
            self.assertEqual(rig.stub.calls, n)
            self.assertIn("ORDER-%d" % (n - 1), json.dumps(rig.stub.requests[-1]))
            self.assertEqual(rig.verdict(sids[n - 1]), "distilled")
        self.assertIn("waiting 0", rig.manifest())
        self.ok(rig.tick())
        self.assertEqual(rig.stub.calls, 3)

    def test_budget_left_over_is_counted_as_waiting(self):
        rig = self.rig(budget={"calls_per_tick": 1})
        for i in range(3):
            rig.transcript("5e551011-0000-4000-8000-00000000000%d" % i)
        self.ok(rig.tick())
        self.assertIn("waiting 2", rig.manifest())
        self.assertNotIn("Waiting:", rig.manifest())

    def test_a_day_budget_spent_makes_no_call(self):
        rig = self.rig(budget={"calls_per_day": 1})
        rig.transcript("5e551011-0000-4000-8000-000000000001")
        rig.transcript("5e551011-0000-4000-8000-000000000002", age_s=1800 + 3600)
        self.ok(rig.tick())
        self.ok(rig.tick())
        self.assertEqual(rig.stub.calls, 1)

    def test_rows_left_staged_by_a_killed_tick_are_never_committed(self):
        rig = self.rig(budget={"calls_per_tick": 0})
        rig.transcript(SID)
        folder = rig.state / "sessions"
        folder.mkdir()
        (folder / "claude-code.json.pending").write_text(json.dumps(
            {"sessions": {SID: {"verdict": "distilled", "captures": 1}}}))
        self.ok(rig.tick())
        self.assertIsNone(rig.verdict(SID))   # its capture was never published, so it waits
        self.assertEqual(rig.stub.calls, 0)

    def test_a_failed_redaction_discards_the_staged_rows(self):
        rig = self.rig()
        rig.transcript(SID)
        shim = rig.tmp / "python-shim"
        shim.write_text('#!/bin/bash\ncase "$1" in */sov-redact) exit 1;; esac\nexec "%s" "$@"\n' % sys.executable)
        shim.chmod(0o755)
        r = rig.tick(SOV_PYTHON=str(shim))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("sov-redact failed", r.stderr)
        self.assertEqual(rig.stub.calls, 1)
        self.assertIsNone(rig.verdict(SID))              # staged rows discarded
        self.assertFalse((rig.state / "sessions" / "claude-code.json.pending").exists())
        self.assertEqual(rig.captures(), [])             # nothing published
        self.ok(rig.tick())                              # and the session retries
        self.assertEqual(rig.verdict(SID), "distilled")
        self.assertEqual(rig.stub.calls, 2)
        self.assertEqual(len(rig.captures()), 1)


SLOW = "SLOW-MARKER"


def slow_or_valid(body):
    if SLOW in json.dumps(body):
        threading.Event().wait(1.5)   # past the 0.5 s per-call timeout these cases use
    return json.dumps({"captures": [VALID]})


class InProcess(unittest.TestCase):
    """Ticks run in this process, so the module can be pointed at a missing sov-capture or
    given a short per-call timeout (the retry's 30 s sleep is skipped)."""

    def rig(self, reply_fn=valid, **cfg):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = fx.Rig(tmp.name, reply_fn, **cfg)
        self.addCleanup(rig.close)
        return rig

    def short_calls(self):
        for patcher in (mock.patch.object(run, "windows", return_value=(0.5, 100, 200)),
                        mock.patch.object(curator_inference, "time", types.SimpleNamespace(sleep=lambda s: None))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_missing_sov_capture_is_a_fault_before_any_call(self):
        rig = self.rig()
        rig.transcript(SID)
        with mock.patch.object(run, "CAPTURE", rig.tmp / "no-such" / "sov-capture"):
            summary = rig.tick_here()
        self.assertEqual(summary["exit"], 1)
        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(rig.watermark()["sessions"].get(SID, {}).get("verdict"), None)
        self.assertFalse((rig.state / "sessions" / "claude-code.json.pending").exists())

    def test_a_sov_capture_that_crashes_is_a_fault_not_a_refusal(self):
        rig = self.rig()
        rig.transcript(SID, age_s=7200)
        rig.transcript("5e551011-0000-4000-8000-0000000000b2")
        broken = rig.tmp / "sov-capture"
        broken.write_text("raise RuntimeError('broken install')\n")
        with mock.patch.object(run, "CAPTURE", broken):
            summary = rig.tick_here()
        self.assertEqual(summary["exit"], 1)
        self.assertEqual(rig.stub.calls, 1)          # calls close at the fault
        self.assertIsNone(rig.verdict(SID))          # never failed:n for a broken install
        self.assertIsNone(rig.verdict("5e551011-0000-4000-8000-0000000000b2"))

    def slow(self, rig, sid, age_s=7200):
        rig.transcript(sid, prompts=["Remember %s always." % SLOW] + list(fx.PROMPTS[1:]), age_s=age_s)

    def row(self, rig, sid):
        return rig.watermark()["sessions"].get(sid) or {}

    def test_a_held_timeout_is_charged_when_another_session_is_answered(self):
        self.short_calls()
        rig = self.rig(slow_or_valid)
        self.slow(rig, SID)
        for cycle in (1, 2, 3):
            fast = "5e551011-0000-4000-8000-00000000f%03d" % cycle
            rig.transcript(fast)
            held = rig.tick_here()
            self.assertEqual(held["calls"], 1)                       # the timeout ends the tick's calls
            self.assertIn("held_timeout", self.row(rig, SID))
            self.assertIsNone(rig.verdict(fast))                     # not called behind the timeout
            if cycle == 1:
                self.assertIsNone(rig.watermark()["waiting"])        # a held timeout sets no waiting
            answered = rig.tick_here()
            self.assertEqual(answered["calls"], 1)                   # held sorts last; it is not called again
            self.assertEqual(rig.verdict(fast), "distilled")
            self.assertNotIn("held_timeout", self.row(rig, SID))
            self.assertEqual(self.row(rig, SID).get("timeouts"), cycle)
        row = self.row(rig, SID)
        self.assertEqual((row["verdict"], row["error"]), ("failed:3", "timed out 3 times"))
        self.assertEqual(rig.tick_here()["calls"], 0)                # terminal

    def test_a_timeout_after_a_held_one_is_an_outage(self):
        self.short_calls()
        rig = self.rig(slow_or_valid)
        t = "5e551011-0000-4000-8000-0000000000b2"
        self.slow(rig, SID, age_s=9000)
        self.slow(rig, t)
        self.assertEqual(rig.tick_here()["calls"], 1)
        self.assertIn("held_timeout", self.row(rig, SID))
        self.assertEqual(rig.tick_here()["calls"], 1)                 # T goes first now
        for sid in (SID, t):
            self.assertNotIn("held_timeout", self.row(rig, sid))
            self.assertFalse(self.row(rig, sid).get("timeouts"))
            self.assertIsNone(rig.verdict(sid))
        self.assertEqual(rig.watermark()["waiting"]["reason"], "model unreachable")

    def test_one_slow_session_alone_is_never_charged(self):
        self.short_calls()
        rig = self.rig(slow_or_valid)
        self.slow(rig, SID)
        for n in range(1, 7):
            self.assertEqual(rig.tick_here()["calls"], 1)
            self.assertFalse(self.row(rig, SID).get("timeouts"), n)
            self.assertIsNone(rig.verdict(SID))
            if n > 1:   # the first tick only holds it; from the second on the model is waited on
                self.assertEqual(rig.watermark()["waiting"]["reason"], "model unreachable", n)
        self.assertEqual(rig.watermark()["waiting"]["reason"], "model unreachable")


if __name__ == "__main__":
    unittest.main()
