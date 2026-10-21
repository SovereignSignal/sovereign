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
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402

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

    def test_a_500_leaves_the_session_pending_and_waits(self):
        replies = iter([500, json.dumps({"captures": [VALID]})])
        rig = self.rig(lambda body: next(replies))
        rig.transcript(SID)
        self.ok(rig.tick())
        self.assertIsNone(rig.verdict(SID))
        waiting = rig.watermark()["waiting"]
        self.assertEqual(waiting["reason"], "model unreachable")
        self.assertRegex(rig.manifest(), r"Waiting: model unreachable since \d{4}-\d\d-\d\dT\d\d:\d\dZ\.")
        self.assertIn("waiting 1", rig.manifest())
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(SID), "distilled")
        self.assertIsNone(rig.watermark()["waiting"])
        self.assertNotIn("Waiting:", rig.manifest())

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

    def test_three_unreachable_results_end_a_session(self):
        rig = self.rig()
        rig.transcript(SID, age_s=7200)
        rig.transcript("5e551011-0000-4000-8000-0000000000b2")
        rig.hub_json("http://127.0.0.1:9/v1/chat/completions")
        for n in (1, 2):
            self.ok(rig.tick())
            self.assertIsNone(rig.verdict(SID))
        self.ok(rig.tick())
        self.assertEqual(rig.verdict(SID), "failed:3")
        rig.hub_json(rig.stub.url)
        self.ok(rig.tick())       # the newer session is no longer blocked behind it
        self.assertEqual(rig.verdict("5e551011-0000-4000-8000-0000000000b2"), "distilled")
        self.assertEqual(rig.verdict(SID), "failed:3")
        self.assertEqual(rig.stub.calls, 1)

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


if __name__ == "__main__":
    unittest.main()
