"""Execute the actual remote status reader against a disposable hub and old log."""
import importlib.machinery
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("hub_job_status", str(ROOT / "bin/sov-status"))
spec = importlib.util.spec_from_loader(loader.name, loader)
status = importlib.util.module_from_spec(spec)
loader.exec_module(status)


class HubJobStatus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.vault = self.home / "archive"
        self.vault.mkdir()
        (self.home / "brain-bin").mkdir()
        (self.home / "brain-bin/sov").symlink_to(ROOT / "bin/sov")
        self.state = self.home / "instance-state"
        self.receipts = self.state / "hub"
        self.receipts.mkdir(parents=True)
        self.config = self.state / "hub.json"
        self.config.write_text(json.dumps({"vault": str(self.vault), "lane": "fixture",
            "model": "fixture", "endpoint": "http://localhost:1234",
            "instance_jobs": {"health": {"program": "fixture", "hours": [8, 20], "minute": 0}}}))
        log = self.home / "old.log"
        log.write_text("2000-01-01T00:00:00Z run job=vault-autocommit exit=0 dur=7s\n")
        (self.home / ".brain-cron-log").write_text(str(log))

    def read(self):
        result = subprocess.run([sys.executable, "-", str(self.vault)], input=status.HUB_SCRIPT,
            env=dict(os.environ, HOME=str(self.home), SOV_STATE_DIR=str(self.state)),
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def receipt(self, name, value):
        (self.receipts / name).write_text(str(value))

    def test_current_failure_supersedes_retired_success(self):
        self.receipt("autocommit.last-run", 1700000000)
        self.receipt("autocommit.last-ok", 1699900000)
        self.receipt("autocommit.last-exit", 1)
        jobs = self.read()["jobs"]
        self.assertNotIn("vault-autocommit", jobs)
        self.assertEqual(jobs["autocommit"]["exit"], 1)
        self.assertEqual(jobs["autocommit"]["last_ok"], 1699900000)
        self.assertEqual(jobs["autocommit"]["source"], "hub-runner")
        self.assertEqual(jobs["autocommit"]["ts"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(jobs["fleet-watch"]["cadence_s"], 300)
        self.assertEqual(jobs["weekly-audit"]["cadence_s"], 604800)
        self.assertEqual(jobs["health"]["cadence_s"], 43200)

    def test_no_completed_receipt_is_unknown_even_with_old_success(self):
        jobs = self.read()["jobs"]
        self.assertIsNone(jobs["autocommit"]["ts"])
        self.assertIsNone(jobs["autocommit"]["exit"])
        self.assertIsNone(jobs["nightly"]["ts"])

    def test_broken_receipt_does_not_claim_success(self):
        self.receipt("autocommit.last-run", "invalid")
        self.receipt("autocommit.last-exit", 0)
        row = self.read()["jobs"]["autocommit"]
        self.assertIsNone(row["ts"])
        self.assertIsNone(row["exit"])

    def test_invalid_config_reports_unknown_instead_of_old_green_log(self):
        self.config.write_text("invalid")
        result = self.read()
        self.assertEqual(result["jobs"], {})
        self.assertIn("jobs_error", result)

    def test_another_archives_receipts_are_not_borrowed(self):
        inst = json.loads(self.config.read_text())
        inst["vault"] = str(self.home / "different-archive")
        self.config.write_text(json.dumps(inst))
        self.receipt("autocommit.last-run", 1700000000)
        self.receipt("autocommit.last-exit", 0)
        result = self.read()
        self.assertEqual(result["jobs"], {})
        self.assertIn("jobs_error", result)

    def test_legacy_hubs_still_read_their_actual_log(self):
        self.config.unlink()
        row = self.read()["jobs"]["vault-autocommit"]
        self.assertEqual(row["exit"], 0)
        self.assertEqual(row["source"], "legacy-cron")

    def test_older_template_preserves_failure_without_health_module(self):
        older=self.home/'older-template'
        shutil.copytree(ROOT/'lib',older/'lib',ignore=shutil.ignore_patterns('job_health.py','__pycache__'))
        (older/'bin').mkdir();(older/'bin/sov').write_text('fixture')
        (self.home/'brain-bin/sov').unlink();(self.home/'brain-bin/sov').symlink_to(older/'bin/sov')
        self.receipt('autocommit.last-run',1700000000)
        self.receipt('autocommit.last-exit',1)
        result=self.read()
        self.assertNotIn('jobs_error',result)
        self.assertEqual(result['jobs']['autocommit']['exit'],1)
        self.assertEqual(result['jobs']['autocommit']['health'],{})


if __name__ == "__main__":
    unittest.main()
