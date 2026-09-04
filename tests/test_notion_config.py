import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.config import Config, ConfigError, load_config, norm_id  # noqa: E402


class LoadConfig(unittest.TestCase):
    def test_reads_env_file_and_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            vault = Path(tmp) / "vault"
            (vault / "raw" / "tools" / "Notion").mkdir(parents=True)
            (state / "mirror.env").write_text(
                'NOTION_API_KEY="secret_x"\nBRAIN_ROOT=%s\nNOTION_FILES=skip\nNOTION_SHRINK_FLOOR=80\n' % vault
            )
            (state / "roots.json").write_text(
                '{"default": "Private & Shared", "required": {"1B0000C0-D590-8025-871F-D52D5773E2AE": "Team HQ"}}'
            )
            cfg = load_config(state, env={})
            self.assertEqual(cfg.token, "secret_x")
            self.assertEqual(cfg.version, "2026-03-11")
            self.assertEqual(cfg.brain_root, vault)
            self.assertEqual(cfg.lane_dir, vault / "raw" / "tools" / "Notion")
            self.assertEqual(cfg.files, "skip")
            self.assertEqual(cfg.shrink_floor, 80)
            self.assertFalse(cfg.allow_shrink)
            self.assertEqual(cfg.default_root, "Private & Shared")
            self.assertEqual(cfg.required_roots, {"1b0000c0d5908025871fd52d5773e2ae": "Team HQ"})

    def test_environment_wins_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "mirror.env").write_text("NOTION_API_KEY=file\nBRAIN_ROOT=%s\n" % tmp)
            cfg = load_config(state, env={"NOTION_API_KEY": "env"})
            self.assertEqual(cfg.token, "env")

    def test_missing_key_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_config(Path(tmp), env={})

    def test_bad_files_mode_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\nNOTION_FILES=maybe\n" % tmp)
            with self.assertRaises(ConfigError):
                load_config(Path(tmp), env={})

    def test_norm_id(self):
        self.assertEqual(norm_id("1B00000C-0D59-0802-5871-FD52D5773E2A"), "1b00000c0d5908025871fd52d5773e2a")
        self.assertEqual(norm_id(None), "")


if __name__ == "__main__":
    unittest.main()
