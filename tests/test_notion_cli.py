import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tests.notion_fake import FakeClient, hid  # noqa: E402
from notion_mirror import cli  # noqa: E402


def setup(tmp, roots=None):
    vault = Path(tmp) / "vault"
    (vault / "raw" / "tools" / "Notion").mkdir(parents=True)
    state = Path(tmp) / "state"
    state.mkdir()
    (state / "mirror.env").write_text("NOTION_API_KEY=k\nBRAIN_ROOT=%s\nNOTION_FILES=skip\n" % vault)
    if roots is not None:
        (state / "roots.json").write_text(roots)
    client = FakeClient()
    client.add_page(1, "Root", client.workspace())
    client.add_page(2, "Child", client.under(1))
    return state, client, vault


def run(argv, client):
    out, err = io.StringIO(), io.StringIO()
    # Snapshot all NOTION_* and BRAIN_ROOT vars, then remove them to test config loading from files
    saved_env = {}
    for key in list(os.environ.keys()):
        if key.startswith("NOTION_") or key == "BRAIN_ROOT":
            saved_env[key] = os.environ.pop(key)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv, client_factory=lambda cfg: client)
        return code, out.getvalue(), err.getvalue()
    finally:
        for key in list(os.environ.keys()):
            if key.startswith("NOTION_") or key == "BRAIN_ROOT":
                os.environ.pop(key, None)
        os.environ.update(saved_env)


class Cli(unittest.TestCase):
    def test_check_prints_roots_and_exit_code_reflects_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp, roots='{"default": "Private & Shared", "required": {"%s": "Private & Shared"}}' % hid(1))
            code, out, err = run(["--check", "--state-dir", str(state)], client)
            self.assertEqual(code, 0, err)
            self.assertIn("bot: TestBot", out)
            self.assertIn(hid(1) + "  Root", out)
            self.assertIn("missing roots: none", out)
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp, roots='{"required": {"%s": "Team"}}' % hid(9))
            code, out, err = run(["--check", "--state-dir", str(state)], client)
            self.assertEqual(code, 2)
            self.assertIn(hid(9), out)

    def test_full_dry_run_then_full_then_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            code, out, err = run(["--full", "--dry-run", "--state-dir", str(state)], client)
            self.assertEqual(code, 0, err)
            self.assertIn("oracle 0/2", out)
            self.assertIn("would write", out)
            self.assertEqual(list((vault / "raw" / "tools" / "Notion").rglob("*.md")), [])
            code, out, err = run(["--full", "--state-dir", str(state)], client)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(list((vault / "raw" / "tools" / "Notion").rglob("*.md"))), 2)
            code, out, err = run(["--state-dir", str(state)], client)
            self.assertEqual(code, 0, err)
            self.assertIn("delta:", out)

    def test_status_and_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            code, out, err = run(["--status", "--state-dir", str(state)], client)
            self.assertEqual(code, 0)
            self.assertIn("lane:", out)
            self.assertIn("pace:", out)
            self.assertIn("0.34", out)
            code, out, err = run(["--status", "--state-dir", str(Path(tmp) / "nowhere")], client)
            self.assertEqual(code, 64)
            self.assertIn("NOTION_API_KEY", err)

    def test_errors_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            client.fail_children_for.add(hid(2))
            code, out, err = run(["--full", "--state-dir", str(state)], client)
            self.assertEqual(code, 1)
            self.assertIn("errors 1", out)

    def test_coverage_prints_groups_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            export = Path(tmp) / "export"
            (export / "Private & Shared" / "Gone").mkdir(parents=True)
            (export / "Private & Shared" / "Gone" / ("Page %s.md" % hid(9))).write_text("x")
            code, out, err = run(["--coverage", str(export), "--state-dir", str(state)], client)
            self.assertEqual(code, 0, err)
            self.assertIn("unreachable 1", out)
            self.assertIn("Private & Shared/Gone", out)
            self.assertEqual(list((vault / "raw" / "tools" / "Notion").rglob("*.md")), [])

    def test_corrupt_manifest_is_a_failed_status_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            (state / "state").mkdir()
            (state / "state" / "manifest.json").write_text("{not json")
            code, out, err = run(["--full", "--state-dir", str(state)], client)
            self.assertEqual(code, 1)
            self.assertIn("crashed", err)
            self.assertNotIn("Traceback", err)
            self.assertTrue((state / "last-status").read_text().startswith("FAILED "))


if __name__ == "__main__":
    unittest.main()


class ExcludesAndScan(unittest.TestCase):
    def test_status_shows_exclude_rule_and_scanner(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            code, out, err = run(["--status", "--state-dir", str(state)], client)
            self.assertEqual(code, 0)
            self.assertIn("exclude:    titles key management, credential", out)
            self.assertIn("scan:       (none)", out)

    def test_check_counts_excluded_and_full_lists_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            client.add_page(3, "Creds", client.under(1))
            code, out, err = run(["--check", "--state-dir", str(state)], client)
            self.assertEqual(code, 0)
            self.assertIn("excluded: 1", out)
            code, out, err = run(["--full", "--dry-run", "--state-dir", str(state)], client)
            self.assertIn("excluded (marker in place) (1):", out)
            self.assertIn("Creds %s.md" % hid(3), out)

    def test_secrets_flagged_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, client, vault = setup(tmp)
            scanner = Path(tmp) / "scan.sh"
            scanner.write_text("#!/bin/sh\ncat \"$1\"\nexit 1\n")
            scanner.chmod(0o755)
            with open(state / "mirror.env", "a") as fh:
                fh.write("NOTION_SECRET_SCAN=%s\n" % scanner)
            code, out, err = run(["--full", "--state-dir", str(state)], client)
            self.assertEqual(code, 1)
            self.assertIn("SECRETS flagged (2):", out)
            self.assertTrue((state / "last-status").read_text().startswith("FAILED "))
