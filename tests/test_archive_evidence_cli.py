import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CARD = b"---\nsource: owner\n---\n# Test Card\n\nPrivate trusted statement.\n"


class CliTests(unittest.TestCase):
    def test_project_wrapper_exposes_isolated_help(self):
        wrapper = Path(__file__).parents[1] / "bin" / "brain-evidence"

        proc = subprocess.run([str(wrapper), "--help"], capture_output=True, text=True)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("--project-root", proc.stdout)

    def test_project_wrapper_resolves_when_invoked_through_symlink(self):
        wrapper = Path(__file__).parents[1] / "bin" / "brain-evidence"
        with tempfile.TemporaryDirectory() as tmp:
            linked = Path(tmp) / "brain-evidence"
            linked.symlink_to(wrapper)

            proc = subprocess.run([str(linked), "--help"], capture_output=True, text=True)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("--project-root", proc.stdout)

    def test_opaque_reference_writes_private_evidence_and_sanitizes_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            run = project / "run"
            vault = base / "vault"
            project.mkdir(mode=0o700)
            run.mkdir(mode=0o700)
            card = vault / "knowledge" / "concepts" / "private-topic.md"
            card.parent.mkdir(parents=True)
            card.write_bytes(CARD)
            overlay = run / "overlay.json"
            overlay.write_text(
                json.dumps(
                    {
                        "references": {
                            "opaque-1": {
                                "opaque_ref": "opaque-1",
                                "slug": "private-topic",
                                "relative_path": "knowledge/concepts/private-topic.md",
                                "content_sha256": hashlib.sha256(CARD).hexdigest(),
                                "enrolled": True,
                                "as_of": "2026-07-01",
                                "verified_at": "2026-07-20",
                                "freshness_class": "operational",
                                "status": "current",
                                "source": "overlay-source",
                                "conflicts": [],
                            }
                        }
                    }
                )
            )
            overlay.chmod(0o600)
            output = run / "evidence.json"
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "lib"))

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "archive_evidence.cli",
                    "--root",
                    str(vault),
                    "--project-root",
                    str(project),
                    "--overlay",
                    str(overlay),
                    "--ref",
                    "opaque-1",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            receipt = json.loads(proc.stdout)
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["record_count"], 1)
            self.assertNotIn("Private trusted statement", proc.stdout + proc.stderr)
            self.assertNotIn("private-topic", proc.stdout + proc.stderr)
            self.assertNotIn(str(vault), proc.stdout + proc.stderr)
            detailed = json.loads(output.read_text())
            record = detailed["evidence"]["records"][0]
            self.assertEqual(record["text"], "Private trusted statement.")
            self.assertEqual(record["as_of"], "2026-07-01")
            self.assertEqual(record["freshness_class"], "operational")
            self.assertEqual(record["source"], "overlay-source")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_audit_overlay_reports_freshness_without_emitting_card_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            run = project / "run"
            vault = base / "vault"
            project.mkdir(mode=0o700)
            run.mkdir(mode=0o700)
            card = vault / "knowledge" / "concepts" / "private-topic.md"
            card.parent.mkdir(parents=True)
            card.write_bytes(CARD)
            overlay = run / "overlay.json"
            overlay.write_text(
                json.dumps(
                    {
                        "references": {
                            "opaque-1": {
                                "opaque_ref": "opaque-1",
                                "slug": "private-topic",
                                "relative_path": "knowledge/concepts/private-topic.md",
                                "content_sha256": hashlib.sha256(CARD).hexdigest(),
                                "enrolled": True,
                                "as_of": "2000-01-01",
                                "verified_at": "2000-01-01",
                                "freshness_class": "operational",
                                "status": "current",
                            }
                        }
                    }
                )
            )
            overlay.chmod(0o600)
            output = run / "audit.json"
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "lib"))

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "archive_evidence.cli",
                    "--root",
                    str(vault),
                    "--project-root",
                    str(project),
                    "--overlay",
                    str(overlay),
                    "--audit-overlay",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            receipt = json.loads(proc.stdout)
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["mode"], "freshness_audit")
            self.assertEqual(receipt["reference_count"], 1)
            self.assertEqual(receipt["freshness_finding_count"], 1)
            self.assertNotIn("Private trusted statement", proc.stdout + proc.stderr)
            self.assertNotIn("private-topic", proc.stdout + proc.stderr)
            detailed = json.loads(output.read_text())
            self.assertNotIn("evidence", detailed)
            self.assertEqual(detailed["freshness"]["counts"], {"overdue_verification": 1})

    def test_audit_overlay_returns_nonzero_for_blocking_temporal_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            run = project / "run"
            vault = base / "vault"
            project.mkdir(mode=0o700)
            run.mkdir(mode=0o700)
            card = vault / "knowledge" / "concepts" / "private-topic.md"
            card.parent.mkdir(parents=True)
            card.write_bytes(CARD)
            overlay = run / "overlay.json"
            overlay.write_text(
                json.dumps(
                    {
                        "references": {
                            "opaque-1": {
                                "opaque_ref": "opaque-1",
                                "slug": "private-topic",
                                "relative_path": "knowledge/concepts/private-topic.md",
                                "content_sha256": hashlib.sha256(CARD).hexdigest(),
                                "enrolled": True,
                                "as_of": "2999-02-01",
                                "verified_at": "2999-01-01",
                                "freshness_class": "operational",
                                "status": "current",
                            }
                        }
                    }
                )
            )
            overlay.chmod(0o600)
            output = run / "audit.json"
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "lib"))

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "archive_evidence.cli",
                    "--root",
                    str(vault),
                    "--project-root",
                    str(project),
                    "--overlay",
                    str(overlay),
                    "--audit-overlay",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(proc.returncode, 3)
            receipt = json.loads(proc.stdout)
            self.assertFalse(receipt["ok"])
            self.assertEqual(receipt["error_code"], "blocking_freshness")
            self.assertTrue(receipt["freshness_blocking"])
            self.assertTrue(output.exists())
            self.assertEqual(proc.stderr, "")

    def test_stale_binding_failure_exposes_only_stable_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            run = project / "run"
            vault = base / "vault"
            project.mkdir(mode=0o700)
            run.mkdir(mode=0o700)
            card = vault / "knowledge" / "concepts" / "private-topic.md"
            card.parent.mkdir(parents=True)
            card.write_bytes(CARD)
            overlay = run / "overlay.json"
            overlay.write_text(
                json.dumps(
                    {
                        "references": {
                            "opaque-1": {
                                "opaque_ref": "opaque-1",
                                "slug": "private-topic",
                                "relative_path": "knowledge/concepts/private-topic.md",
                                "content_sha256": "0" * 64,
                                "enrolled": False,
                            }
                        }
                    }
                )
            )
            overlay.chmod(0o600)
            output = run / "evidence.json"
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "lib"))

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "archive_evidence.cli",
                    "--root",
                    str(vault),
                    "--project-root",
                    str(project),
                    "--overlay",
                    str(overlay),
                    "--ref",
                    "opaque-1",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout), {"error_code": "stale_binding", "ok": False})
            self.assertEqual(proc.stderr, "")
            self.assertFalse(output.exists())
            self.assertNotIn("private-topic", proc.stdout + proc.stderr)
            self.assertNotIn("Private trusted statement", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
