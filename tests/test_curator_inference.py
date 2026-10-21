"""The one road a curator's model call takes, importable without running curator-run.

curator-run owned the provider table, the sovereign-inference guard, the config
precedence, the key lookup and the HTTP chat helpers, and it evaluates its own guard at
module level, so nothing else could reuse them without lifting source by AST. These
cases pin the shared module to the behaviour curator-run had: the guard rows its
--self-test checks, the env precedence, the request shape a loopback stub sees, and the
redirect refusal a local-only archive relies on. No network: the stub is on 127.0.0.1.
"""
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import curator_inference as ci  # noqa: E402

LOCAL = "http://localhost:11434/v1/chat/completions"


class Stub:
    """Loopback model endpoint: records each request, answers or redirects."""

    def __init__(self, reply=None):
        self.bodies = []
        self.headers = []
        self.paths = []
        self.redirect_followed = False
        self.reply = reply or {"choices": [{"message": {"content": '{"promote": false}'}}]}
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/landed")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path.startswith("/landed"):
                    stub.redirect_followed = True
                stub.bodies.append(json.loads(body or b"{}"))
                stub.headers.append({k.lower(): v for k, v in self.headers.items()})
                stub.paths.append(self.path)
                out = json.dumps(stub.reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            do_GET = do_POST

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class InferenceModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        env = patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def test_violation_table(self):
        v = ci.inference_violations
        rows = [
            ("loopback clean", 0, v(LOCAL, "qwen3.8:27b", "qwen3.8:27b", False)),
            ("127.0.0.1 clean", 0, v("http://127.0.0.1:8080/v1/chat/completions", "glm-5.3", "glm-5.3", False)),
            ("hosted endpoint refused", 1,
             v("https://api.vendor.com/v1/chat/completions", "qwen3.8:27b", "qwen3.8:27b", False)),
            (":cloud model refused on localhost", 1, v(LOCAL, "qwen3.5:cloud", "qwen3.8:27b", False)),
            (":cloud screen model refused", 1, v(LOCAL, "qwen3.8:27b", "kimi-k3:cloud", False)),
            ("both bad = two", 2, v("https://api.vendor.com/v1/chat/completions", "qwen3.5:cloud", "qwen3.8:27b", False)),
            ("allow_remote clean", 0,
             v("https://api.vendor.com/v1/chat/completions", "qwen3.5:cloud", "kimi-k3:cloud", True)),
            ("anthropic at its own host clean", 0,
             v("https://api.anthropic.com/v1/messages", "claude-opus-5-5", "claude-opus-5-5", False, backend="anthropic")),
            ("anthropic under local_only refused", 1,
             v("https://api.anthropic.com/v1/messages", "claude-opus-5-5", "claude-opus-5-5", True,
               backend="anthropic", local_only=True)),
            ("anthropic wrong host refused", 1,
             v("https://api.vendor.com/v1/messages", "claude-opus-5-5", "claude-opus-5-5", False, backend="anthropic")),
            ("anthropic over http refused", 1,
             v("http://api.anthropic.com/v1/messages", "claude-opus-5-5", "claude-opus-5-5", False, backend="anthropic")),
            ("unknown backend refused", 1, v(LOCAL, "qwen3.8:27b", "qwen3.8:27b", False, backend="cohere")),
            ("openai at its own host clean", 0,
             v("https://api.openai.com/v1/chat/completions", "gpt-5.6", "gpt-5.6", False, provider="openai")),
            ("openai wrong host refused", 1,
             v("https://api.vendor.com/v1/chat/completions", "gpt-5.6", "gpt-5.6", False, provider="openai")),
            ("gemini at its own host clean", 0,
             v("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "gemini-2.5-pro", "gemini-2.5-pro", False, provider="gemini")),
            ("grok over http refused", 1,
             v("http://api.x.ai/v1/chat/completions", "grok-4.7", "grok-4.7", False, provider="grok")),
            ("muse without an https endpoint refused", 1,
             v(LOCAL, "muse-wonder-full-1.0", "muse-wonder-full-1.0", False, provider="muse")),
            ("provider under local_only refused", 1,
             v("https://api.openai.com/v1/chat/completions", "gpt-5.6", "gpt-5.6", False,
               provider="openai", local_only=True)),
            ("provider on the wrong wire shape refused", 1,
             v("https://api.openai.com/v1/chat/completions", "gpt-5.6", "gpt-5.6", False,
               backend="anthropic", provider="openai")),
            ("unknown provider refused", 1, v(LOCAL, "qwen3.8:27b", "qwen3.8:27b", False, provider="cohere")),
        ]
        for name, want, got in rows:
            with self.subTest(name):
                self.assertEqual(len(got), want, got)

    def test_violations_wraps_the_config(self):
        self.assertEqual(ci.violations(ci.config_from_env({})), [])
        cfg = ci.config_from_env({"CURATOR_PROVIDER": "openai", "CURATOR_LOCAL_ONLY": "1"})
        self.assertEqual(len(ci.violations(cfg)), 1)
        cfg = ci.config_from_env({"CURATOR_ENDPOINT": "https://api.vendor.com/v1/chat/completions",
                                  "CURATOR_ALLOW_REMOTE": "yes"})
        self.assertTrue(cfg["allow_remote"])
        self.assertEqual(ci.violations(cfg), [])

    def test_config_precedence(self):
        cfg = ci.config_from_env({})
        self.assertEqual(cfg, {"provider": "", "backend": "openai", "endpoint": LOCAL, "model": "qwen3.8:27b",
                               "screen_model": "qwen3.8:27b", "local_only": False, "allow_remote": False,
                               "keychain_service": "", "keyfile": "", "reasoning_effort": "",
                               "anthropic_effort": "medium"})
        cfg = ci.config_from_env({"CURATOR_BACKEND": "anthropic"})
        self.assertEqual(cfg["provider"], "anthropic")
        self.assertEqual(cfg["endpoint"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(cfg["model"], "claude-opus-5-5")
        self.assertEqual(cfg["keychain_service"], "sovereign-curator-anthropic")
        cfg = ci.config_from_env({"CURATOR_PROVIDER": " OpenAI "})
        self.assertEqual((cfg["provider"], cfg["backend"]), ("openai", "openai"))
        self.assertEqual(cfg["endpoint"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(cfg["model"], "gpt-5.6")
        # the owner may override the endpoint, and the guard still pins the host
        cfg = ci.config_from_env({"CURATOR_PROVIDER": "openai", "CURATOR_ENDPOINT": "https://api.vendor.com/v1"})
        self.assertEqual(cfg["endpoint"], "https://api.vendor.com/v1")
        self.assertEqual(len(ci.violations(cfg)), 1)
        cfg = ci.config_from_env({"CURATOR_MODEL": "glm-5.3", "CURATOR_SCREEN_MODEL": "small",
                                  "CURATOR_REASONING_EFFORT": "none", "CURATOR_EFFORT": "high",
                                  "CURATOR_KEYFILE": "/k", "CURATOR_LOCAL_ONLY": "1"})
        self.assertEqual((cfg["model"], cfg["screen_model"], cfg["reasoning_effort"], cfg["anthropic_effort"],
                          cfg["keyfile"], cfg["local_only"]), ("glm-5.3", "small", "none", "high", "/k", True))

    def test_load_key_order(self):
        keyfile = self.home / "key"
        keyfile.write_text(" from-file \n")
        cfg = ci.config_from_env({"CURATOR_KEYFILE": str(keyfile)})
        self.assertEqual(ci.load_key(cfg, {"CURATOR_KEY": "from-env"}), "from-file")
        cfg = ci.config_from_env({})
        self.assertEqual(ci.load_key(cfg, {"CURATOR_KEY": "from-env"}), "from-env")
        # no provider: the Keychain is never asked
        with patch.object(ci.subprocess, "run", side_effect=AssertionError("keychain asked")):
            self.assertEqual(ci.load_key(cfg, {}), "")
        cfg = ci.config_from_env({"CURATOR_PROVIDER": "grok"})
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            return type("Done", (), {"stdout": "from-keychain\n"})()
        with patch.object(ci.subprocess, "run", side_effect=fake_run):
            self.assertEqual(ci.load_key(cfg, {}), "from-keychain")
        self.assertEqual(calls, [["/usr/bin/security", "find-generic-password", "-s",
                                  "sovereign-curator-grok", "-w"]])
        with patch.object(ci.subprocess, "run", side_effect=OSError("no security")):
            self.assertEqual(ci.load_key(cfg, {}), "")

    def test_chat_openai_shape(self):
        stub = Stub()
        self.addCleanup(stub.close)
        cfg = ci.config_from_env({"CURATOR_ENDPOINT": stub.base + "/v1/chat/completions"})
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        out = ci.chat(cfg, "k", "qwen3.8:27b", 0.1, msgs, 10)
        self.assertEqual(out, '{"promote": false}')
        body = stub.bodies[0]
        self.assertEqual(body["response_format"]["type"], "json_object")
        self.assertEqual((body["model"], body["temperature"], body["stream"]), ("qwen3.8:27b", 0.1, False))
        self.assertEqual(body["messages"], msgs)
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(stub.headers[0].get("authorization"), "Bearer k")
        cfg["reasoning_effort"] = "none"
        ci.chat(cfg, "k", "qwen3.8:27b", 0, msgs, 10)
        self.assertEqual(stub.bodies[1]["reasoning_effort"], "none")

    def test_chat_refuses_an_unguarded_config(self):
        stub = Stub()
        self.addCleanup(stub.close)
        msgs = [{"role": "user", "content": "u"}]
        cfg = ci.config_from_env({"CURATOR_ENDPOINT": "https://api.vendor.com/v1/chat/completions"})
        self.assertFalse(cfg["allow_remote"])
        with self.assertRaises(RuntimeError) as err:
            ci.chat(cfg, "k", "qwen3.8:27b", 0, msgs, 5)
        self.assertIn("sovereign-inference law: endpoint is not local: api.vendor.com", str(err.exception))
        # a config edited after it was checked is checked again at the call
        cfg = ci.config_from_env({"CURATOR_ENDPOINT": stub.base + "/v1/chat/completions"})
        self.assertEqual(ci.violations(cfg), [])
        cfg["model"] = "qwen3.5:cloud"
        with self.assertRaises(RuntimeError):
            ci.chat(cfg, "k", cfg["model"], 0, msgs, 5)
        self.assertEqual(stub.bodies, [])

    def test_chat_anthropic_shape(self):
        reply = {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": "x"},
                                                          {"type": "text", "text": '{"promote": true}'}]}
        stub = Stub(reply)
        self.addCleanup(stub.close)
        cfg = ci.config_from_env({"CURATOR_BACKEND": "anthropic", "CURATOR_EFFORT": "high",
                                  "CURATOR_ENDPOINT": stub.base + "/v1/messages"})
        msgs = [{"role": "system", "content": "brief"}, {"role": "user", "content": "source"}]
        # The guard pins Anthropic to its own https host, so a loopback stub can only
        # see the wire shape with the guard stood aside; the refusal is tested above.
        with patch.object(ci, "violations", return_value=[]):
            out = ci.chat(cfg, "sk-test", "claude-opus-5-5", 0.1, msgs, 10)
            self.assertEqual(out, '{"promote": true}')
            self.assertEqual(stub.paths[0], "/v1/messages")
            head = stub.headers[0]
            self.assertEqual(head.get("x-api-key"), "sk-test")
            self.assertEqual(head.get("anthropic-version"), "2023-06-01")
            body = stub.bodies[0]
            self.assertEqual(body["system"], "brief")
            self.assertEqual(body["messages"], [{"role": "user", "content": "source"}])
            self.assertNotIn("temperature", body)
            self.assertEqual(body["max_tokens"], 16000)
            self.assertEqual(body["output_config"], {"effort": "high"})
            self.assertEqual(body["model"], "claude-opus-5-5")
            stub.reply = {"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"promo'}]}
            with self.assertRaises(ValueError) as err:
                ci.chat(cfg, "sk-test", "claude-opus-5-5", 0.1, msgs, 10)
            self.assertIn("Claude stopped with max_tokens", str(err.exception))
            stub.reply = {"stop_reason": "refusal", "stop_details": {"category": "cyber"}, "content": []}
            with self.assertRaises(ValueError) as err:
                ci.chat(cfg, "sk-test", "claude-opus-5-5", 0.1, msgs, 10)
            self.assertIn("Claude stopped with refusal (cyber)", str(err.exception))

    def test_local_only_refuses_redirect(self):
        stub = Stub()
        self.addCleanup(stub.close)
        cfg = ci.config_from_env({"CURATOR_ENDPOINT": stub.base + "/redirect/completions",
                                  "CURATOR_LOCAL_ONLY": "1"})
        # local_only comes from cfg, never the process env
        with patch.dict(os.environ, {"CURATOR_LOCAL_ONLY": ""}):
            with self.assertRaises(ValueError):
                ci.chat(cfg, "", "qwen3.8:27b", 0, [{"role": "user", "content": "u"}], 5)
        self.assertFalse(stub.redirect_followed)

    def test_http_error_keeps_the_server_reason(self):
        class Fail(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                out = b'{"error": "temperature is deprecated"}'
                self.send_response(400)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fail)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        cfg = ci.config_from_env({"CURATOR_ENDPOINT": "http://127.0.0.1:%d/v1" % server.server_address[1]})
        with self.assertRaises(RuntimeError) as err:
            ci.chat(cfg, "", "m", 0, [{"role": "user", "content": "u"}], 5)
        self.assertIn("HTTP 400", str(err.exception))
        self.assertIn("temperature is deprecated", str(err.exception))

    def test_chosen_provider(self):
        state = self.home / "state"
        self.assertEqual(ci.chosen_provider(state), "anthropic")
        state.mkdir()
        (state / "curator-provider.json").write_text("not json")
        self.assertEqual(ci.chosen_provider(state), "anthropic")
        (state / "curator-provider.json").write_text(json.dumps({"provider": "cohere"}))
        self.assertEqual(ci.chosen_provider(state), "anthropic")
        (state / "curator-provider.json").write_text(json.dumps({"provider": "grok"}))
        self.assertEqual(ci.chosen_provider(state), "grok")
        self.assertEqual(ci.chosen_provider(str(state)), "grok")

    def test_providers_table(self):
        self.assertEqual(sorted(ci.PROVIDERS), ["anthropic", "gemini", "grok", "muse", "openai"])
        self.assertEqual(ci.PROVIDERS["muse"]["endpoint"], "")


if __name__ == "__main__":
    unittest.main()
