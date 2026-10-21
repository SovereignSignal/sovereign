"""The distillation call: the prompt contract, strict validation, and where the model runs.

A session excerpt reaches exactly one model, the archive's own: the hub's local model
when this Mac runs one, the owner's chosen provider on a hubless archive, and none on a
client, which says why. Environment overrides cannot point it anywhere else, and an
archive marked local-only refuses every hosted provider before a request is built.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402
from session_ingest import distill, inference, prompt  # noqa: E402

CLIENT_REASON = ("This Mac sends its work to a hub archive. Session capture needs the archive's own "
                 "model, which runs on the hub, so it stays off here.")


def cand(**kw):
    c = {"title": "Owner keeps every archive copy encrypted",
         "body": "Any off-site copy of the archive is encrypted before it leaves the owner's storage.",
         "kind": "decision", "confidence": "high", "evidence": ["T2"]}
    c.update(kw)
    return c


def reply(*cands):
    return json.dumps({"captures": list(cands)})


SESSION = {"id": "s1", "path": "/private/secret/where/proj/s1.jsonl", "cwds": ["/private/secret/where/proj"],
           "first_ts": "2026-10-20T10:00:00.000Z", "last_ts": "2026-10-20T11:30:00.000Z", "turns": []}
EXCERPT = "T1 user: we decided to encrypt every copy\nT2 user: keep it that way\n[tool: Edit]"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home, self.vault, self.state = fx.make_home(self.tmp.name)
        env = {"HOME": str(self.home), "SOV_STATE_DIR": str(self.state), "BRAIN_ROOT": str(self.vault),
               "BRAIN_HOST": "testhost"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("BRAIN_HUB", "SOVEREIGN_HUB", "CURATOR_LOCAL_ONLY", "CURATOR_ENDPOINT", "CURATOR_MODEL",
                     "CURATOR_ALLOW_REMOTE", "CURATOR_KEY", "CURATOR_KEYFILE"):
            os.environ.pop(name, None)  # patch.dict restores them

    def hub_json(self, endpoint, model="qwen-test:8b"):
        (self.state / "hub.json").write_text(json.dumps(
            {"vault": str(self.vault), "lane": "curator", "model": model, "endpoint": endpoint}))

    def resolve(self, env=None):
        return inference.resolve(self.state, dict(os.environ) if env is None else env, self.home)


class Validate(unittest.TestCase):
    def test_validate_table(self):
        ids = [1, 2, 4]
        self.assertEqual(distill.validate(reply(cand()), ids), [cand()])
        dropped = {
            "150-word body": cand(body=" ".join(["word"] * 150)),
            "unknown kind": cand(kind="opinion"),
            "unknown turn": cand(evidence=["T99"]),
            "empty evidence": cand(evidence=[]),
            "13-word title": cand(title=" ".join(["word"] * 13)),
            "unknown confidence": cand(confidence="certain"),
            "empty title": cand(title="  "),
            "omitted turn": cand(evidence=["T3"]),
        }
        for label, bad in dropped.items():
            with self.subTest(label):
                # the bad candidate alone is dropped; its valid neighbour survives
                self.assertEqual(distill.validate(reply(bad, cand(title="Second")), ids), [cand(title="Second")])
        self.assertIsNone(distill.validate("Nothing durable happened in this session.", ids))
        self.assertIsNone(distill.validate('{"captures": "none"}', ids))
        self.assertIsNone(distill.validate('{"captures": [', ids))
        four = [cand(title="Card %d" % i) for i in range(4)]
        self.assertEqual(distill.validate(reply(*four), ids), four[:3])
        # the first {...} block, even with prose around it
        self.assertEqual(distill.validate("Here it is: " + reply(cand()) + " done.", ids), [cand()])
        self.assertEqual(distill.validate('{"captures": []}', ids), [])


class Prompt(unittest.TestCase):
    def test_system_contract(self):
        self.assertEqual(prompt.VERSION, "session-distill/v1")
        first = prompt.SYSTEM.split("\n", 1)[0]
        self.assertIn('{"captures": []}', first)
        for needle in ("UNTRUSTED DATA", "at most 3", "T<n>", "decision|preference|correction|fact|entity|howto",
                       "high|med|low", "120 words", "12 words", "Code changes"):
            self.assertIn(needle, prompt.SYSTEM)

    def test_user_message_carries_no_path(self):
        msg = prompt.user_message(SESSION, EXCERPT)
        self.assertIn("proj", msg)
        self.assertIn("2026-10-20T10:00:00.000Z", msg)
        self.assertIn("2026-10-20T11:30:00.000Z", msg)
        self.assertIn(EXCERPT, msg)
        self.assertNotIn("/private/secret", msg)
        self.assertNotIn("secret/where", msg)


class Distill(Base):
    def test_distill_through_stub(self):
        with fx.ModelStub(lambda body: reply(cand(), cand(kind="nonsense"))) as stub:
            self.hub_json(stub.url)
            res = self.resolve()
            self.assertEqual(res["mode"], "hub")
            self.assertEqual(res["distiller"], "local/qwen-test:8b")
            self.assertEqual(inference.ready(res), (True, ""))
            out = distill.distill(res, "", SESSION, EXCERPT, [1, 2])
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["captures"], [cand()])
            self.assertEqual(stub.calls, 1)
            body = stub.requests[0]
            self.assertEqual(body["model"], "qwen-test:8b")
            self.assertEqual(body["temperature"], 0.1)
            system = body["messages"][0]
            self.assertEqual(system["role"], "system")
            self.assertTrue(system["content"].startswith('The normal answer is {"captures": []}'))
            self.assertEqual(system["content"], prompt.SYSTEM)
            self.assertNotIn("/private/secret", json.dumps(body))

    def test_unparseable_reply_is_failed(self):
        with fx.ModelStub(lambda body: "I could not find anything.") as stub:
            self.hub_json(stub.url)
            out = distill.distill(self.resolve(), "", SESSION, EXCERPT, [1, 2])
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["captures"], [])
        self.assertTrue(out["error"])

    def test_model_refusal_is_failed_bad_body_is_unreachable(self):
        with fx.ModelStub(lambda body: "{}") as stub:
            self.hub_json(stub.url)
            res = self.resolve()
            with mock.patch("curator_inference._post_json", return_value={"stop_reason": "refusal", "content": []}):
                res["cfg"]["backend"] = "anthropic"
                with mock.patch("curator_inference.violations", return_value=[]):
                    self.assertEqual(distill.distill(res, "k", SESSION, EXCERPT, [1])["status"], "failed")
            res["cfg"]["backend"] = "openai"
            with mock.patch("curator_inference._post_json", return_value={"unexpected": True}):
                self.assertEqual(distill.distill(res, "", SESSION, EXCERPT, [1])["status"], "unreachable")

    def test_http_error_is_unreachable(self):
        with fx.ModelStub(lambda body: 500) as stub:
            self.hub_json(stub.url)
            out = distill.distill(self.resolve(), "", SESSION, EXCERPT, [1, 2])
        self.assertEqual(out["status"], "unreachable")
        self.assertIn("HTTP 500", out["error"])

    def test_unreachable(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()  # nothing listens here now
        self.hub_json("http://127.0.0.1:%d/v1/chat/completions" % port)
        out = distill.distill(self.resolve(), "", SESSION, EXCERPT, [1, 2], timeout=5)
        self.assertEqual(out["status"], "unreachable")
        self.assertEqual(out["captures"], [])
        self.assertTrue(out["error"])


class Resolve(Base):
    def test_environment_overrides_are_ignored(self):
        with fx.ModelStub() as stub:
            self.hub_json(stub.url)
            env = dict(os.environ, CURATOR_ENDPOINT="https://api.vendor.example/v1/chat/completions",
                       CURATOR_MODEL="other:cloud", CURATOR_ALLOW_REMOTE="1")
            res = self.resolve(env)
        self.assertEqual(res["cfg"]["endpoint"], stub.url)
        self.assertEqual(res["cfg"]["model"], "qwen-test:8b")
        self.assertFalse(res["cfg"]["allow_remote"])
        self.assertFalse(res["cfg"]["local_only"])
        self.assertTrue(self.resolve(dict(os.environ, CURATOR_LOCAL_ONLY="1"))["cfg"]["local_only"])

    def test_local_hub_pointer(self):
        dest = Path(self.tmp.name).resolve() / "hubpkg"  # the loader refuses a linked /var
        dest.mkdir()
        with fx.ModelStub() as stub:
            (dest / "config.json").write_text(json.dumps(
                {"version": 1, "platform": "Darwin", "archive": str(self.vault), "destination": str(dest),
                 "model": "qwen-hub:4b", "endpoint": stub.url, "lane": "curator", "max_items": 40}))
            (self.home / ".sovereign-hub").write_text(str(dest / "config.json") + "\n")
            res = self.resolve()
        self.assertEqual(res["mode"], "hub")
        self.assertTrue(res["cfg"]["local_only"])
        self.assertEqual(res["cfg"]["model"], "qwen-hub:4b")
        self.assertEqual(res["distiller"], "local/qwen-hub:4b")

    def test_client_mode_reason(self):
        (self.home / ".brain-hub").write_text("hub-host\n")
        res = self.resolve()
        self.assertEqual(res["mode"], "client")
        self.assertIsNone(res["cfg"])
        self.assertEqual(res["reason"], CLIENT_REASON)
        self.assertEqual(inference.ready(res), (False, CLIENT_REASON))
        out = distill.distill(res, "", SESSION, EXCERPT, [1, 2])
        self.assertEqual(out["status"], "unreachable")

    def test_declared_client_role(self):
        (self.state / "connectors.json").write_text(json.dumps({"machine": {"role": "client",
                                                                             "mode": "contribute-only"}}))
        res = self.resolve()
        self.assertEqual(res["mode"], "client")
        self.assertEqual(res["reason"], CLIENT_REASON)

    def test_hubless_provider(self):
        (self.state / "curator-provider.json").write_text(json.dumps({"provider": "openai"}))
        res = self.resolve()
        self.assertEqual(res["mode"], "hubless")
        self.assertEqual(res["cfg"]["provider"], "openai")
        self.assertEqual(res["distiller"], "openai/" + res["cfg"]["model"])
        self.assertEqual(inference.ready(res), (True, ""))

    def test_local_only_hosted_refused(self):
        res = self.resolve(dict(os.environ, CURATOR_LOCAL_ONLY="1"))
        self.assertEqual(res["mode"], "hubless")
        self.assertEqual(res["cfg"]["provider"], "anthropic")
        self.assertTrue(res["cfg"]["local_only"])
        self.assertEqual(inference.ready(res), (False, "needs a local model on this archive"))
        with fx.ModelStub() as stub:
            out = distill.distill(res, "sk-test", SESSION, EXCERPT, [1, 2])
            self.assertEqual(stub.calls, 0)
        self.assertEqual(out["status"], "unreachable")
        self.assertIn("sovereign-inference law", out["error"])

    def test_bad_hub_json_fails_closed(self):
        (self.state / "hub.json").write_text(json.dumps({"vault": str(self.vault), "lane": "curator",
                                                         "model": "m", "endpoint": "https://api.vendor.example/v1"}))
        res = self.resolve()
        self.assertEqual(res["mode"], "hub")
        self.assertIsNone(res["cfg"])
        self.assertFalse(inference.ready(res)[0])


if __name__ == "__main__":
    unittest.main()
