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

    def test_lane_cannot_escape_the_vault(self):
        for bad in ("/abs/path", "../../etc/foo", "raw/../../x"):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "mirror.env").write_text(
                    "NOTION_API_KEY=k\nBRAIN_ROOT=%s\nNOTION_LANE=%s\n" % (tmp, bad))
                with self.assertRaises(ConfigError, msg=bad):
                    load_config(Path(tmp), env={})

    def test_min_interval_defaults_to_0_34(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\n" % tmp)
            cfg = load_config(Path(tmp), env={})
            self.assertEqual(cfg.min_interval, 0.34)

    def test_min_interval_read_from_mirror_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\nNOTION_MIN_INTERVAL=1.5\n" % tmp)
            cfg = load_config(Path(tmp), env={})
            self.assertEqual(cfg.min_interval, 1.5)

    def test_min_interval_non_number_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\nNOTION_MIN_INTERVAL=fast\n" % tmp)
            with self.assertRaises(ConfigError):
                load_config(Path(tmp), env={})

    def test_min_interval_must_be_greater_than_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\nNOTION_MIN_INTERVAL=0\n" % tmp)
            with self.assertRaises(ConfigError):
                load_config(Path(tmp), env={})

    def test_norm_id(self):
        self.assertEqual(norm_id("1B00000C-0D59-0802-5871-FD52D5773E2A"), "1b00000c0d5908025871fd52d5773e2a")
        self.assertEqual(norm_id(None), "")


if __name__ == "__main__":
    unittest.main()


class Excludes(unittest.TestCase):
    def env(self, tmp, extra=""):
        (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\n%s" % (tmp, extra))
        return Path(tmp)

    def test_nothing_excluded_by_name_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(self.env(tmp), env={})
            self.assertEqual(cfg.exclude_titles, [])
            self.assertEqual(cfg.exclude_ids, set())

    def test_titles_from_env_file_and_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(self.env(tmp, "NOTION_EXCLUDE_TITLES= Vault , creds\n"), env={})
            self.assertEqual(cfg.exclude_titles, ["Vault", "creds"])
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(self.env(tmp, "NOTION_EXCLUDE_TITLES=off\n"), env={})
            self.assertEqual(cfg.exclude_titles, [])

    def test_ids_normalized_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(self.env(tmp, "NOTION_EXCLUDE_IDS=1B0000C0-D590-8025-871F-D52D5773E2AE, 2b0000c0d5908025871fd52d5773e2ae\n"), env={})
            self.assertEqual(cfg.exclude_ids, {"1b0000c0d5908025871fd52d5773e2ae", "2b0000c0d5908025871fd52d5773e2ae"})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_config(self.env(tmp, "NOTION_EXCLUDE_IDS=not-an-id\n"), env={})


class SecretScan(unittest.TestCase):
    def env(self, tmp, extra=""):
        (Path(tmp) / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\n%s" % (tmp, extra))
        return Path(tmp)

    def test_default_is_the_scanner_beside_the_bin_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            (bin_dir / "cron-wrappers").mkdir(parents=True)
            self.assertEqual(load_config(self.env(tmp), env={}, bin_dir=bin_dir).secret_scan, "")
            scanner = bin_dir / "cron-wrappers" / "vault-secret-scan.sh"
            scanner.write_text("#!/bin/sh\nexit 0\n")
            scanner.chmod(0o755)
            self.assertEqual(load_config(self.env(tmp), env={}, bin_dir=bin_dir).secret_scan, str(scanner))

    def test_explicit_path_off_and_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            scanner = Path(tmp) / "scan.sh"
            scanner.write_text("#!/bin/sh\nexit 0\n")
            scanner.chmod(0o755)
            cfg = load_config(self.env(tmp, "NOTION_SECRET_SCAN=%s\n" % scanner), env={})
            self.assertEqual(cfg.secret_scan, str(scanner))
            self.assertEqual(load_config(self.env(tmp, "NOTION_SECRET_SCAN=off\n"), env={}).secret_scan, "")
            with self.assertRaises(ConfigError):
                load_config(self.env(tmp, "NOTION_SECRET_SCAN=%s\n" % (Path(tmp) / "nope.sh")), env={})
