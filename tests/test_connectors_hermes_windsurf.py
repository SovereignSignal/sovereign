"""Hermes and Windsurf connectors against a fake home and a throwaway vault."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "connectors" / "harness"
CARD = "---\ntype: {typ}\nsource: owner\ncreated: 2026-01-01\n---\n# {title}\n\n{body}\n"


def make_vault(tmp):
    v = Path(tmp) / "vault"
    for sub in ("knowledge/entities", "workstreams/sky", "raw/tools"):
        (v / sub).mkdir(parents=True)
    (v / "knowledge/entities/me.md").write_text(CARD.format(typ="entity", title="Me", body="The owner."))
    (v / "knowledge/entities/sky.md").write_text(CARD.format(typ="entity", title="Sky", body="A protocol."))
    return v


def env_for(tmp, vault, **extra):
    e = dict(os.environ)
    e.update({"HOME": str(Path(tmp) / "home"), "BRAIN_ROOT": str(vault), "BRAIN_CORE": "me",
              "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage"), "HERMES_HOME": str(Path(tmp) / "hermes")})
    e.update(extra)
    (Path(tmp) / "home").mkdir(exist_ok=True)
    return e


class HermesHook(unittest.TestCase):
    def run_hook(self, env, payload):
        return subprocess.run([sys.executable, str(H / "hermes" / "session-start.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=60)

    def test_first_turn_injects_core_and_named_workstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp); env = env_for(tmp, v)
            r = self.run_hook(env, {"session_id": "s1", "extra": {"user_message": "help me with [sky] today", "conversation_history": []}})
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertIn("# Sky", out["context"]); self.assertIn("# Me", out["context"])
            receipt = Path(tmp) / "stage/raw/tools/hermes-testbox/brain-load-usage.md"
            self.assertIn("source=pre_llm_call", receipt.read_text())

    def test_mid_conversation_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp); env = env_for(tmp, v)
            r = self.run_hook(env, {"session_id": "s1", "extra": {"user_message": "more", "conversation_history": [{"a": 1}, {"b": 2}, {"c": 3}]}})
            self.assertEqual(r.stdout.strip(), "{}")
            self.assertFalse((Path(tmp) / "stage/raw/tools/hermes-testbox").exists())


class HermesRegistration(unittest.TestCase):
    def test_hooks_py_adds_block_and_consent_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            hh = Path(tmp) / "hermes"; hh.mkdir()
            (hh / "config.yaml").write_text("model: x\nagent:\n  name: h\n")
            env = dict(os.environ); env.update({"HERMES_HOME": str(hh)})
            script = str(H / "hermes" / "hooks.py")
            r0 = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, env=env)
            self.assertEqual(r0.returncode, 2)
            r1 = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
            self.assertIn("config written", r1.stdout); self.assertIn("consent written", r1.stdout)
            cfg = (hh / "config.yaml").read_text()
            self.assertIn("hooks:\n  pre_llm_call:\n    - command: \"", cfg)
            self.assertTrue(cfg.startswith("model: x\nagent:\n  name: h\n"))
            allow = json.loads((hh / "shell-hooks-allowlist.json").read_text())
            self.assertEqual(allow["approvals"][0]["event"], "pre_llm_call")
            self.assertTrue(allow["approvals"][0]["command"].endswith("hermes/session-start.py"))
            r2 = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
            self.assertIn("config already", r2.stdout); self.assertIn("consent already", r2.stdout)
            self.assertEqual(cfg, (hh / "config.yaml").read_text())
            r3 = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, env=env)
            self.assertEqual(r3.returncode, 0)

    def test_hooks_py_extends_an_existing_hooks_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            hh = Path(tmp) / "hermes"; hh.mkdir()
            (hh / "config.yaml").write_text("model: x\nhooks:\n  pre_tool_call:\n    - matcher: terminal\n      command: /x/guard.sh\nskills:\n  a: 1\n")
            env = dict(os.environ); env.update({"HERMES_HOME": str(hh)})
            subprocess.run([sys.executable, str(H / "hermes" / "hooks.py")], capture_output=True, text=True, env=env)
            cfg = (hh / "config.yaml").read_text()
            self.assertIn("  pre_tool_call:\n    - matcher: terminal\n      command: /x/guard.sh\n  pre_llm_call:\n    - command: \"", cfg)
            self.assertTrue(cfg.rstrip().endswith("skills:\n  a: 1".rstrip()) or "skills:\n  a: 1" in cfg)


class HermesMirror(unittest.TestCase):
    def test_mirrors_memory_markdown_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            hh = Path(tmp) / "hermes" / "memories"; hh.mkdir(parents=True)
            (hh / "MEMORY.md").write_text("# m\n"); (hh / "USER.md").write_text("# u\n"); (hh / "state.db").write_text("x")
            env = dict(os.environ); env.update({"HOME": str(Path(tmp) / "home"), "HERMES_HOME": str(Path(tmp) / "hermes"),
                                                "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
            (Path(tmp) / "home").mkdir()
            r = subprocess.run(["/bin/bash", str(H / "hermes" / "mirror.sh")], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            lane = Path(tmp) / "stage/raw/tools/hermes-testbox"
            self.assertTrue((lane / "memories" / "MEMORY.md").exists()); self.assertTrue((lane / "memories" / "USER.md").exists())
            self.assertFalse((lane / "memories" / "state.db").exists())
            self.assertIn("Items mirrored: 1. Failed: 0.", (lane / "MANIFEST.md").read_text())


class WindsurfConnector(unittest.TestCase):
    def test_mirror_and_rules_instruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            home = Path(tmp) / "home"; mem = home / ".codeium" / "windsurf" / "memories"; mem.mkdir(parents=True)
            (mem / "global_rules.md").write_text("Be brief.\n"); (mem / "auto.md").write_text("remembered\n"); (mem / "cascade.pb").write_bytes(b"\x00")
            env = dict(os.environ); env.update({"HOME": str(home), "BRAIN_ROOT": str(v), "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
            r = subprocess.run(["/bin/bash", str(H / "windsurf" / "mirror.sh")], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            lane = Path(tmp) / "stage/raw/tools/windsurf-testbox"
            self.assertTrue((lane / "memories" / "auto.md").exists())
            self.assertFalse((lane / "memories" / "cascade.pb").exists())
            rules = (mem / "global_rules.md").read_text()
            self.assertTrue(rules.startswith("Be brief."))
            self.assertEqual(rules.count("[Sovereign]"), 1)
            self.assertIn(str(v), rules)
            subprocess.run(["/bin/bash", str(H / "windsurf" / "mirror.sh")], capture_output=True, text=True, env=env)
            self.assertEqual((mem / "global_rules.md").read_text().count("[Sovereign]"), 1)
            self.assertTrue(list(mem.glob("global_rules.md.bak-*")))


if __name__ == "__main__":
    unittest.main()
