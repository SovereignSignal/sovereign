"""Every harness connector against a throwaway vault and a fake home.

Shared read wire (brainhook) through each adapter's output shape, and each mirror's
write wire. HOME, BRAIN_ROOT, BRAIN_CORE, BRAIN_HOST and BRAIN_STAGE all point at temp
dirs: nothing here touches the real vault, the real dotfiles, or the real pointer files.
"""
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
    for sub in ("knowledge/entities", "knowledge/concepts", "workstreams/sky", "raw/tools"):
        (v / sub).mkdir(parents=True)
    (v / "knowledge/entities/me.md").write_text(CARD.format(typ="entity", title="Me", body="The owner."))
    (v / "knowledge/entities/sky.md").write_text(CARD.format(typ="entity", title="Sky", body="A protocol."))
    return v


def env_for(tmp, vault, **extra):
    e = dict(os.environ)
    e.update({"HOME": str(Path(tmp) / "home"), "BRAIN_ROOT": str(vault), "BRAIN_CORE": "me",
              "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
    e.update(extra)
    (Path(tmp) / "home").mkdir(exist_ok=True)
    return e


def run_hook(harness, cwd, env, stdin=None):
    payload = stdin or {"cwd": str(cwd), "session_id": "sess-1234", "source": "startup"}
    return subprocess.run([sys.executable, str(H / harness / "session-start.py")],
                          input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)


class CodexHook(unittest.TestCase):
    def test_same_shape_as_claude_code_and_own_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            res = run_hook("codex", v / "workstreams" / "sky", env_for(tmp, v))
            self.assertEqual(res.returncode, 0, res.stderr)
            out = json.loads(res.stdout)
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn("# Sky", out["hookSpecificOutput"]["additionalContext"])
            receipt = Path(tmp) / "stage/raw/tools/codex-memory-testbox/brain-load-usage.md"
            self.assertIn("sky scope=workstream", receipt.read_text())


class CursorHook(unittest.TestCase):
    def test_project_dir_from_env_and_additional_context_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            e = env_for(tmp, v, CURSOR_PROJECT_DIR=str(v / "workstreams" / "sky"))
            res = run_hook("cursor", Path(tmp), e, stdin={"session_id": "cur-1", "composer_mode": "agent"})
            self.assertEqual(res.returncode, 0, res.stderr)
            out = json.loads(res.stdout)
            self.assertEqual(list(out.keys()), ["additional_context"])
            self.assertIn("# Sky", out["additional_context"])
            receipt = Path(tmp) / "stage/raw/tools/cursor-testbox/brain-load-usage.md"
            self.assertIn("source=agent", receipt.read_text())

    def test_not_connected_prints_empty_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            e = env_for(tmp, v); e.pop("BRAIN_ROOT")
            res = run_hook("cursor", v, e)
            self.assertEqual(res.stdout.strip(), "{}")
            self.assertEqual(res.returncode, 0)


class Mirrors(unittest.TestCase):
    def run_mirror(self, harness, env):
        return subprocess.run(["/bin/bash", str(H / harness / "mirror.sh")], capture_output=True, text=True, env=env)

    def test_codex_mirrors_memories_working_tree_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            mem = home / ".codex" / "memories"; (mem / ".git").mkdir(parents=True)
            (mem / "MEMORY.md").write_text("# m\n"); (mem / ".git" / "HEAD").write_text("ref\n")
            env = dict(os.environ); env.update({"HOME": str(home), "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
            res = self.run_mirror("codex", env)
            self.assertEqual(res.returncode, 0, res.stderr)
            lane = Path(tmp) / "stage/raw/tools/codex-memory-testbox"
            self.assertTrue((lane / "MEMORY.md").exists())
            self.assertFalse((lane / ".git").exists())
            self.assertIn("Items mirrored: 1. Failed: 0.", (lane / "MANIFEST.md").read_text())

    def test_cowork_mirrors_each_nonempty_memory_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            (sessions / "a" / "space1" / "memory").mkdir(parents=True)
            (sessions / "a" / "space1" / "memory" / "MEMORY.md").write_text("x\n")
            (sessions / "b" / ".hidden" / "memory").mkdir(parents=True)
            (sessions / "b" / ".hidden" / "memory" / "MEMORY.md").write_text("y\n")
            (sessions / "c" / "empty" / "memory").mkdir(parents=True)
            env = dict(os.environ); env.update({"HOME": str(Path(tmp) / "home"), "BRAIN_HOST": "testbox",
                                                "BRAIN_STAGE": str(Path(tmp) / "stage"), "COWORK_SESSIONS": str(sessions)})
            (Path(tmp) / "home").mkdir()
            res = self.run_mirror("cowork", env)
            self.assertEqual(res.returncode, 0, res.stderr)
            lane = Path(tmp) / "stage/raw/tools/cowork-testbox"
            self.assertTrue((lane / "space1" / "MEMORY.md").exists())
            self.assertTrue((lane / "hidden" / "MEMORY.md").exists())   # dot dropped
            self.assertFalse((lane / "empty").exists())
            self.assertIn("Items mirrored: 2.", (lane / "MANIFEST.md").read_text())

    def test_cursor_mirrors_plans_and_skills_without_a_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".cursor" / "plans").mkdir(parents=True)
            (home / ".cursor" / "plans" / "p1.md").write_text("plan\n")
            (home / ".cursor" / "projects" / "proj" / "agent-transcripts").mkdir(parents=True)
            (home / ".cursor" / "projects" / "proj" / "agent-transcripts" / "t.md").write_text("t\n")
            env = dict(os.environ); env.update({"HOME": str(home), "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
            res = self.run_mirror("cursor", env)
            self.assertEqual(res.returncode, 0, res.stderr)
            lane = Path(tmp) / "stage/raw/tools/cursor-testbox"
            self.assertTrue((lane / "plans" / "p1.md").exists())
            self.assertTrue((lane / "projects" / "proj" / "agent-transcripts" / "t.md").exists())
            self.assertFalse((lane / "chats").exists())
            self.assertIn("Items mirrored: 2. Failed: 0.", (lane / "MANIFEST.md").read_text())


if __name__ == "__main__":
    unittest.main()


class CoworkInstruction(unittest.TestCase):
    def test_ensure_instruction_covers_every_space_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            sp = sessions / "acct" / "profile"; sp.mkdir(parents=True)
            (sp / "spaces.json").write_text(json.dumps({"spaces": [
                {"id": "1", "name": "A", "instructions": "Read X first."},
                {"id": "2", "name": "B"},
            ]}))
            env = dict(os.environ); env.update({"BRAIN_ROOT": str(Path(tmp) / "vault"), "COWORK_SESSIONS": str(sessions)})
            script = H / "cowork" / "ensure-instruction.py"
            r1 = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
            r2 = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
            self.assertIn("covered 2 space(s) newly covered", r1.stdout)
            self.assertIn("0 space(s) newly covered, 2 already covered", r2.stdout)
            data = json.loads((sp / "spaces.json").read_text())
            self.assertTrue(data["spaces"][0]["instructions"].startswith("Read X first."))
            self.assertEqual(data["spaces"][0]["instructions"].count("[Sovereign]"), 1)
            self.assertIn(str(Path(tmp) / "vault"), data["spaces"][1]["instructions"])
            self.assertTrue(list(sp.glob("spaces.json.bak-*")))


class CodexTrust(unittest.TestCase):
    def test_trust_record_matches_codex_formula_and_is_idempotent(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".codex"; home.mkdir()
            hook = str(H / "codex" / "session-start.py")
            (home / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
                {"matcher": "startup|resume", "hooks": [{"type": "command", "command": hook, "timeout": 30, "statusMessage": "Sovereign: loading brain context"}]}]}}))
            (home / "config.toml").write_text('model = "x"\n\n[hooks.state]\n')
            env = dict(os.environ); env.update({"CODEX_HOME": str(home)})
            script = str(H / "codex" / "trust.py")
            r0 = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, env=env)
            self.assertEqual(r0.returncode, 1, r0.stdout)
            r1 = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
            self.assertIn("written", r1.stdout)
            expected = "sha256:" + hashlib.sha256(json.dumps(
                {"event_name": "session_start", "matcher": "startup|resume",
                 "hooks": [{"type": "command", "command": hook, "timeout": 30, "async": False, "statusMessage": "Sovereign: loading brain context"}]},
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            text = (home / "config.toml").read_text()
            self.assertIn('[hooks.state."%s/hooks.json:session_start:0:0"]' % home, text)
            self.assertIn('trusted_hash = "%s"' % expected, text)
            r2 = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
            self.assertIn("already", r2.stdout)
            self.assertEqual(text, (home / "config.toml").read_text())
            r3 = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, env=env)
            self.assertEqual(r3.returncode, 0)


class Redaction(unittest.TestCase):
    def test_every_write_wire_redacts_what_it_copied_and_leaves_the_source_alone(self):
        token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            mem = home / ".codex" / "memories"; mem.mkdir(parents=True)
            (mem / "MEMORY.md").write_text("# m\nthe deploy token is %s\n" % token)
            env = dict(os.environ); env.update({"HOME": str(home), "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
            res = subprocess.run(["/bin/bash", str(H / "codex" / "mirror.sh")], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            lane = Path(tmp) / "stage/raw/tools/codex-memory-testbox"
            self.assertEqual((lane / "MEMORY.md").read_text(), "# m\nthe deploy token is [redacted github token]\n")
            self.assertIn(token, (mem / "MEMORY.md").read_text())
            self.assertIn("Redacted on this run: 1 in 1 file(s)", (lane / "MANIFEST.md").read_text())
            self.assertIn("mirror: redacted 1 in 1 file(s)", res.stderr)
            # the source still holds the value, so every tick copies and redacts it again, and says so
            res = subprocess.run(["/bin/bash", str(H / "codex" / "mirror.sh")], capture_output=True, text=True, env=env)
            self.assertIn("mirror: redacted 1 in 1 file(s)", res.stderr)
            self.assertNotIn(token, (lane / "MEMORY.md").read_text())
            self.assertEqual((lane / "MANIFEST.md").read_text().count("Redacted on this run"), 1)
            (mem / "MEMORY.md").write_text("# m\nclean now\n")
            res = subprocess.run(["/bin/bash", str(H / "codex" / "mirror.sh")], capture_output=True, text=True, env=env)
            self.assertNotIn("redacted", res.stderr)  # a clean source makes a quiet tick
