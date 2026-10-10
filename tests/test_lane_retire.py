"""Retiring a source is its contract saying so (LANE.md `status: retired`), on the archive's
copy and the staging copy together, so no machine keeps alerting on a source the owner
retired. History stays; restore puts back the status it had."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tests.test_brain_status_jobs as base

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import lane_contract  # noqa: E402

CONTRACT = "---\nlane: tool-desk\nproducer: Tool on desk\nhost: desk\nwrite: rsync\nread: none\ngear: ask-first\nstatus: onboarded\nonboarded: 2026-09-02\n---\n\nBody stays.\n"


class LaneContract(unittest.TestCase):
    def test_retire_then_restore_round_trips_the_status(self):
        retired = lane_contract.retired_text(CONTRACT, "owner stopped using it", "2026-10-10")
        self.assertIn("\nstatus: retired\nretired: 2026-10-10 (owner stopped using it)\nretired_from: onboarded\n---\n", retired)
        self.assertTrue(retired.endswith("\nBody stays.\n"))
        self.assertEqual(lane_contract.retired_text(retired, "again"), retired)
        back = lane_contract.restored_text(retired)
        self.assertIn("\nstatus: onboarded\n---", back)
        self.assertNotIn("retired", back.split("---")[1])

    def test_cli_dry_run_changes_nothing_and_apply_writes_both_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, stage = Path(tmp, "vault"), Path(tmp, "stage")
            for base_dir in (vault, stage):
                (base_dir / "raw" / "tools" / "tool-desk").mkdir(parents=True)
                (base_dir / "raw" / "tools" / "tool-desk" / "LANE.md").write_text(CONTRACT)
            env = dict(os.environ, BRAIN_ROOT=str(vault), BRAIN_STAGE=str(stage))
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "bin" / "sov-lane"), *a], env=env, capture_output=True, text=True)
            dry = run("retire", "tool-desk")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("dry run", dry.stdout)
            self.assertEqual((vault / "raw/tools/tool-desk/LANE.md").read_text(), CONTRACT)
            self.assertEqual(run("retire", "tool-desk", "--apply").returncode, 0)
            for base_dir in (vault, stage):
                self.assertIn("status: retired", (base_dir / "raw/tools/tool-desk/LANE.md").read_text())
            self.assertEqual(run("restore", "tool-desk", "--apply").returncode, 0)
            self.assertEqual((vault / "raw/tools/tool-desk/LANE.md").read_text().count("status: onboarded"), 1)
            self.assertEqual(run("retire", "../etc").returncode, 65)
            self.assertEqual(run("retire", "no-such-lane").returncode, 65)


class StatusReadsTheContract(unittest.TestCase):
    def test_a_lane_retired_by_contract_is_retired_without_a_local_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = base.Box(tmp); b.declare({}); b.record({})
            lane = b.vault / "raw" / "tools" / "tool-desk"
            lane.mkdir(parents=True)
            (lane / "LANE.md").write_text(lane_contract.retired_text(CONTRACT, "owner", "2026-10-10"))
            row = next(l for l in b.status()["lanes"] if l["lane"] == "tool-desk")
            self.assertTrue(row["retired"])
            self.assertEqual(row["findings"][0]["level"], "info")


if __name__ == "__main__":
    unittest.main()
