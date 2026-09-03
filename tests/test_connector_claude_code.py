"""Connector: Claude Code. Both wires, against a throwaway vault and a fake home.

Nothing here touches the real vault, the real ~/.claude, or the real pointer files:
HOME, BRAIN_ROOT, BRAIN_CORE, BRAIN_HOST and BRAIN_STAGE are all pointed at temp dirs.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "connectors" / "harness" / "claude-code" / "session-start.py"
MIRROR = ROOT / "connectors" / "harness" / "claude-code" / "mirror.sh"

CARD = "---\ntype: {typ}\nsource: owner\ncreated: 2026-01-01\n---\n# {title}\n\n{body}\n"


def make_vault(tmp):
    v = Path(tmp) / "vault"
    for sub in ("knowledge/entities", "knowledge/concepts", "knowledge/syntheses",
                "workstreams/sky", "repos/tool", "raw/tools"):
        (v / sub).mkdir(parents=True)
    (v / "knowledge/entities/me.md").write_text(CARD.format(typ="entity", title="Me", body="The owner."))
    (v / "knowledge/entities/sky.md").write_text(
        CARD.format(typ="entity", title="Sky", body="A protocol. See [[sky-process]]."))
    (v / "knowledge/concepts/sky-process.md").write_text(
        CARD.format(typ="concept", title="Sky process", body="How Sky work runs."))
    (v / "workstreams/sky/overview.md").write_text("---\ntype: note\nsource: owner\ncreated: 2026-01-01\nidentity: wolf\n---\n# Sky\n")
    return v


def run_hook(cwd, env):
    stdin = json.dumps({"cwd": str(cwd), "session_id": "test-session", "source": "startup"})
    res = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                         text=True, env=env, timeout=60)
    return res


class HookTests(unittest.TestCase):
    def env(self, tmp, vault):
        e = dict(os.environ)
        e.update({"HOME": str(Path(tmp) / "home"), "BRAIN_ROOT": str(vault), "BRAIN_CORE": "me",
                  "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
        (Path(tmp) / "home").mkdir(exist_ok=True)
        return e

    def test_workstream_cwd_loads_topic_pack_and_leaves_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            res = run_hook(v / "workstreams" / "sky", self.env(tmp, v))
            self.assertEqual(res.returncode, 0, res.stderr)
            out = json.loads(res.stdout)
            ctx = out["hookSpecificOutput"]["additionalContext"]
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn("# Sky", ctx)
            self.assertIn("# Sky process", ctx)   # one hop of links followed
            self.assertIn("# Me", ctx)            # always-on core rides along
            self.assertIn("Do not copy it into memory files", ctx)
            self.assertIn("Identity for this workstream: wolf", ctx)
            self.assertIn("'sky'", out["systemMessage"])
            receipt = Path(tmp) / "stage" / "raw" / "tools" / "claude-code-testbox" / "brain-load-usage.md"
            self.assertTrue(receipt.exists())
            self.assertIn("sky scope=workstream", receipt.read_text())

    def test_outside_vault_loads_core_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            res = run_hook(Path(tmp) / "home", self.env(tmp, v))
            out = json.loads(res.stdout)
            ctx = out["hookSpecificOutput"]["additionalContext"]
            self.assertIn("# Me", ctx)
            self.assertNotIn("# Sky", ctx)
            self.assertIn("Identity for this context: the default", ctx)
            self.assertIn("'core'", out["systemMessage"])

    def test_not_connected_is_silent_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            e = self.env(tmp, v)
            e.pop("BRAIN_ROOT")
            res = run_hook(v / "workstreams" / "sky", e)
            self.assertEqual(res.returncode, 0)
            self.assertEqual(res.stdout.strip(), "")

    def test_never_writes_the_pack_into_the_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = make_vault(tmp)
            run_hook(v / "workstreams" / "sky", self.env(tmp, v))
            lane = Path(tmp) / "stage" / "raw" / "tools" / "claude-code-testbox"
            names = sorted(p.name for p in lane.rglob("*") if p.is_file())
            self.assertEqual(names, ["brain-load-usage.md"])


class MirrorTests(unittest.TestCase):
    def test_mirrors_every_project_memory_and_skips_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            for key in ("-Users-x", "-Users-x-proj-a"):
                m = home / ".claude" / "projects" / key / "memory"
                m.mkdir(parents=True)
                (m / "MEMORY.md").write_text("# index\n")
                (m / "fact.md").write_text("a fact\n")
                (home / ".claude" / "projects" / key / "session.jsonl").write_text("{}\n")
            (home / ".claude" / "projects" / "-Users-x-empty" / "memory").mkdir(parents=True)
            env = dict(os.environ)
            env.update({"HOME": str(home), "BRAIN_HOST": "testbox", "BRAIN_STAGE": str(Path(tmp) / "stage")})
            res = subprocess.run(["/bin/bash", str(MIRROR)], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            lane = Path(tmp) / "stage" / "raw" / "tools" / "claude-code-testbox" / "memory"
            self.assertTrue((lane / "-Users-x" / "fact.md").exists())
            self.assertTrue((lane / "-Users-x-proj-a" / "MEMORY.md").exists())
            self.assertFalse((lane / "-Users-x-empty").exists())
            self.assertEqual([p for p in lane.rglob("*.jsonl")], [])
            manifest = (lane / "MANIFEST.md").read_text()
            self.assertIn("Items mirrored: 2. Failed: 0.", manifest)
            self.assertIn("-Users-x-proj-a", manifest)

    def test_no_destination_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env.update({"HOME": str(Path(tmp) / "nohome"), "BRAIN_HOST": "testbox"})
            env.pop("BRAIN_ROOT", None); env.pop("BRAIN_STAGE", None)
            res = subprocess.run(["/bin/bash", str(MIRROR)], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0)
            self.assertIn("no destination", res.stderr)


if __name__ == "__main__":
    unittest.main()
