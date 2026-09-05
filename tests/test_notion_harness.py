"""The Notion harness: sov connect notion. Dry run writes nothing; apply writes the
instance files, builds roots.json from what the token can see, and writes the plist
without loading it when asked. The check step is stubbed through SOV_TEST_CHECK_OUTPUT
so no test touches the network."""
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "connectors" / "harness" / "notion" / "install.sh"
HID = "%032x"

CHECK = "bot: TestBot\nworkspace: Test WS\nitems: 3 (page 3)\nroots reachable:\n  %s  Root A\n  %s  Root B\nmissing roots: none\n" % (HID % 1, HID % 2)


def run(args, home, vault, env_extra=None):
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SOV_TEST_CHECK_OUTPUT": CHECK}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(INSTALL), "--vault", str(vault), "--host", "testbox"] + args,
                          capture_output=True, text=True, env=env, cwd=str(ROOT))


def brain(tmp):
    home = Path(tmp) / "home"
    vault = Path(tmp) / "vault"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (vault / "knowledge").mkdir(parents=True)
    (vault / "raw" / "tools").mkdir(parents=True)
    return home, vault


class Harness(unittest.TestCase):
    def test_harness_json_and_catalog_row(self):
        meta = json.loads((ROOT / "connectors" / "harness" / "notion" / "harness.json").read_text())
        self.assertEqual(meta["lane"], "Notion")
        self.assertEqual(meta["read"], "none")
        self.assertEqual(meta["write"], "pull")
        self.assertEqual(meta["detect"], [])
        self.assertEqual(meta["secret"]["env"], "NOTION_API_KEY")
        self.assertNotIn("flag", meta["secret"])
        self.assertEqual(meta["last_success_file"], "~/.notion-mirror/last-success")
        self.assertEqual(meta["last_status_file"], "~/.notion-mirror/last-status")
        self.assertIn("integration", meta["manual_step"].lower())
        tools = json.loads((ROOT / "connectors" / "harness" / "_lib" / "known-tools.json").read_text())["tools"]
        row = next(t for t in tools if t["id"] == "notion")
        self.assertEqual(row["connector"], "notion")
        self.assertEqual(row["detect"], [])

    def test_dry_run_prints_plan_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            r = run([], home, vault)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("dry run", r.stdout)
            self.assertIn("token      MISSING", r.stdout)
            self.assertFalse((home / ".notion-mirror").exists())
            self.assertFalse((home / ".brain-root").exists())
            self.assertEqual(os.listdir(vault / "raw" / "tools"), [])

    def test_apply_without_token_stops_with_the_manual_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            r = run(["--apply", "--no-launchd"], home, vault)
            self.assertEqual(r.returncode, 65)
            self.assertIn("mirror.env", r.stdout + r.stderr)
            self.assertFalse((home / ".notion-mirror" / "mirror.env").exists())

    def test_apply_writes_instance_files_roots_lane_and_plist(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            r = run(["--apply", "--no-launchd", "--secret", "ntn_test_token", "--at", "04:10"], home, vault)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            env_path = home / ".notion-mirror" / "mirror.env"
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
            env_text = env_path.read_text()
            self.assertIn("NOTION_API_KEY=ntn_test_token\n", env_text)
            self.assertIn("BRAIN_ROOT=%s\n" % vault, env_text)
            self.assertIn("NOTION_LANE=raw/tools/Notion\n", env_text)
            self.assertNotIn("ntn_test_token", r.stdout + r.stderr)
            roots = json.loads((home / ".notion-mirror" / "roots.json").read_text())
            self.assertEqual(roots["default"], "Private & Shared")
            self.assertEqual(roots["required"], {HID % 1: "Private & Shared", HID % 2: "Private & Shared"})
            lane_md = (vault / "raw" / "tools" / "Notion" / "LANE.md").read_text()
            self.assertIn("lane: Notion\n", lane_md)
            self.assertIn("write: pull", lane_md)
            self.assertIn("read: none", lane_md)
            self.assertTrue((home / "brain-bin" / "brain-mirror-notion").is_symlink())
            plist_path = home / "Library" / "LaunchAgents" / "com.sovereign.connector.notion.plist"
            plist = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(plist["Label"], "com.sovereign.connector.notion")
            self.assertEqual(plist["StartCalendarInterval"], {"Hour": 4, "Minute": 10})
            self.assertFalse(plist["RunAtLoad"])
            self.assertTrue(plist["StandardErrorPath"].endswith("com.sovereign.connector.notion.error.log"))
            self.assertTrue(plist["ProgramArguments"][-1].endswith("connectors/harness/notion/mirror.sh"))
            self.assertIn("not loaded", r.stdout)

    def test_apply_preserves_other_env_keys_and_existing_lane_and_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            (home / ".notion-mirror").mkdir()
            (home / ".notion-mirror" / "mirror.env").write_text("NOTION_SHRINK_FLOOR=80\nNOTION_API_KEY=old\n")
            (home / ".notion-mirror" / "roots.json").write_text('{"default": "Private & Shared", "required": {"%s": "Team"}}' % (HID % 9))
            (vault / "raw" / "tools" / "Notion").mkdir()
            (vault / "raw" / "tools" / "Notion" / "LANE.md").write_text("---\nlane: Notion\nowner: hand written\n---\n")
            r = run(["--apply", "--no-launchd"], home, vault)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            env_text = (home / ".notion-mirror" / "mirror.env").read_text()
            self.assertIn("NOTION_SHRINK_FLOOR=80\n", env_text)
            self.assertIn("NOTION_API_KEY=old\n", env_text)
            self.assertEqual(json.loads((home / ".notion-mirror" / "roots.json").read_text())["required"], {HID % 9: "Team"})
            self.assertIn("owner: hand written", (vault / "raw" / "tools" / "Notion" / "LANE.md").read_text())
            self.assertIn("LANE.md kept", r.stdout)

    def test_lane_cannot_escape_the_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            for bad in ("../../etc/foo", "raw/../../x", "/abs/path"):
                r = run(["--lane", bad], home, vault)
                self.assertEqual(r.returncode, 64, bad)
                self.assertIn("--lane", r.stderr)
                self.assertFalse((home / ".notion-mirror").exists())

    def test_stale_status_from_previous_importer_is_parked_when_never_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            (home / ".notion-mirror").mkdir()
            (home / ".notion-mirror" / "last-status").write_text("OK 2026-01-01 00:00:00 old importer")
            (home / ".notion-mirror" / "last-success").write_text("2026-01-01T00:00:00Z")
            r = run(["--apply", "--no-launchd", "--secret", "ntn_test_token"], home, vault)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse((home / ".notion-mirror" / "last-status").exists())
            self.assertFalse((home / ".notion-mirror" / "last-success").exists())
            self.assertEqual((home / ".notion-mirror" / "last-status.pre-api").read_text(), "OK 2026-01-01 00:00:00 old importer")
            self.assertEqual((home / ".notion-mirror" / "last-success.pre-api").read_text(), "2026-01-01T00:00:00Z")
            self.assertIn("parked", r.stdout)

    def test_stale_status_left_alone_when_cursor_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, vault = brain(tmp)
            (home / ".notion-mirror").mkdir()
            (home / ".notion-mirror" / "last-status").write_text("OK 2026-01-01 00:00:00 old importer")
            (home / ".notion-mirror" / "last-success").write_text("2026-01-01T00:00:00Z")
            (home / ".notion-mirror" / "state").mkdir()
            (home / ".notion-mirror" / "state" / "cursor").write_text("2026-01-01T00:00:00.000Z\n")
            r = run(["--apply", "--no-launchd", "--secret", "ntn_test_token"], home, vault)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((home / ".notion-mirror" / "last-status").exists())
            self.assertTrue((home / ".notion-mirror" / "last-success").exists())
            self.assertFalse((home / ".notion-mirror" / "last-status.pre-api").exists())
            self.assertFalse((home / ".notion-mirror" / "last-success.pre-api").exists())
            self.assertNotIn("parked", r.stdout)

    def test_scripts_parse(self):
        for name in ("install.sh", "mirror.sh", "watchdog.sh"):
            r = subprocess.run(["bash", "-n", str(ROOT / "connectors" / "harness" / "notion" / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, name + ": " + r.stderr)


if __name__ == "__main__":
    unittest.main()
