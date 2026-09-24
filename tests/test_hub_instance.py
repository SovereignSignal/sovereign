"""hub.json holds everything that is the owner's. The template never reads a path of the
owner's from anywhere else, and the moved scripts get their settings from `sov hub env`."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import instance  # noqa: E402

GOOD = {
    "version": 1,
    "vault": "/tmp/v",
    "lane": "curator",
    "model": "local-model:tag",
    "audit_model": "local-model:tag",
    "endpoint": "http://localhost:11434/v1/chat/completions",
    "exclude": ["raw/tools/Private"],
    "pending_limit": 50,
    "burndown": {"since_days": 400, "max": 120, "pending_limit": 200, "keep_floor_pct": 2},
    "remotes": ["origin", "exchange"],
    "snapshot": {"folder": "/tmp/snaps", "keep": 30},
    "notify": {"archive": "/tmp/tg-archive.env", "alerts": "/tmp/tg-alerts.env"},
    "kit": {"include": ["~/.hermes/.env"], "key_file": "/tmp/keys/hub.key", "targets": ["keep:git/hub-kit/"], "keep": 7},
    "offsite": {"vault": "keep:git/vault.git", "template": "keep:git/template.git"},
    "instance_jobs": {},
}


class Instance(unittest.TestCase):
    def test_validate_accepts_the_full_shape_and_rejects_a_missing_vault(self):
        self.assertEqual(instance.validate(dict(GOOD))["lane"], "curator")
        bad = dict(GOOD); del bad["vault"]
        with self.assertRaises(ValueError):
            instance.validate(bad)

    def test_endpoint_must_be_loopback(self):
        bad = dict(GOOD, endpoint="http://other.local:11434/v1/chat/completions")
        with self.assertRaises(ValueError):
            instance.validate(bad)

    def test_judge_parallel_is_a_small_positive_integer(self):
        self.assertEqual(instance.validate(dict(GOOD, judge_parallel=2))["judge_parallel"], 2)
        for bad in (0, 5, "2", True, 1.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                instance.validate(dict(GOOD, judge_parallel=bad))

    def test_curate_auto_promote_max_is_a_bounded_integer(self):
        self.assertEqual(instance.validate(dict(GOOD, curate_auto_promote_max=12))["curate_auto_promote_max"], 12)
        self.assertEqual(instance.validate(dict(GOOD, curate_auto_promote_max=0))["curate_auto_promote_max"], 0)
        for bad in (-1, 51, "12", True, 2.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                instance.validate(dict(GOOD, curate_auto_promote_max=bad))

    def test_env_exports_are_what_the_scripts_expect(self):
        out = instance.env_exports(instance.validate(dict(GOOD)))
        self.assertIn("export SOVS_VAULT='/tmp/v'", out)
        self.assertIn("export CURATOR_LANE='curator'", out)
        self.assertIn("export CURATOR_MODEL='local-model:tag'", out)
        self.assertIn("export CURATOR_AUDIT_MODEL='local-model:tag'", out)
        self.assertIn("export CURATOR_ENDPOINT='http://localhost:11434/v1/chat/completions'", out)
        self.assertIn("export CURATOR_EXCLUDE='raw/tools/Private'", out)
        self.assertIn("export ARCHIVIST_PENDING_LIMIT='50'", out)
        self.assertIn("export CURATOR_JUDGE_PARALLEL='1'", out, "one judge call at a time unless the owner says otherwise")
        self.assertIn("export SOV_CURATE_AUTO_PROMOTE_MAX='4'", out, "the tick's cap, never the nightly's")
        self.assertNotIn("ARCHIVIST_AUTO_PROMOTE_MAX", out, "exporting that name would move the nightly and burndown")
        self.assertIn("export BURNDOWN_KEEP_FLOOR_PCT='2'", out)
        self.assertIn("export SOV_HUB_REMOTES='origin exchange'", out)
        self.assertIn("export SOV_HUB_EXCHANGE='exchange'", out, "the exchange defaults to the last remote")
        self.assertIn("export SOV_HUB_DIGEST=''", out)
        self.assertIn("export SOV_HUB_SNAPSHOT_DIR='/tmp/snaps'", out)
        self.assertIn("export TG_ENV_FILE='/tmp/tg-archive.env'", out)
        # a shell can eval it
        r = subprocess.run(["/bin/bash", "-c", out + '\necho "$CURATOR_LANE:$SOV_HUB_SNAPSHOT_KEEP"'], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "curator:30")

    def test_from_scripts_reads_export_lines_into_fields(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            s = Path(tmp) / "nightly.sh"
            s.write_text('#!/bin/bash\nexport SOVS_VAULT="$HOME/Vault"\nexport CURATOR_LANE=curator\n'
                         'export CURATOR_MODEL="m:1"\nexport CURATOR_ENDPOINT="http://localhost:11434/v1/chat/completions"\n'
                         'export CURATOR_EXCLUDE="a:b c"\n')
            got = instance.from_scripts([s], home="/opt/owner")
            self.assertEqual(got["vault"], "/opt/owner/Vault")
            self.assertEqual(got["exclude"], ["a", "b c"])
            self.assertEqual(got["model"], "m:1")

    def test_write_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            instance.write(tmp, dict(GOOD))
            self.assertTrue((Path(tmp) / "hub.json").exists())
            with self.assertRaises(ValueError):
                instance.write(tmp, dict(GOOD))
            self.assertEqual(instance.load(tmp)["vault"], "/tmp/v")


if __name__ == "__main__":
    unittest.main()
