import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import unittest
from unittest.mock import patch

from sovereign_intake import client, collector, importer, server
from sovereign_intake.common import IntakeError, atomic, encoded, git, locked, now


class Intake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sovereign-intake-", dir="/private/tmp" if Path("/private/tmp").exists() else None)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "sources"
        self.source.mkdir()
        (self.source / "method.md").write_text("# Keep\nRepeat the checked workflow.\n# Private\nUnselected private prose.\n")
        self.config = dict(client_id="worker-a", source_root=str(self.source), spool=str(self.base / "spool"), remote=str(self.base / "intake.git"), selectors=[dict(id="method", path="method.md", title="Working method", topics=["method"], extractor="sections", argument=["Keep"])])
        server.init(self.config["remote"])
        client.init_spool(self.config, "Fixture Operator", "fixture@example.invalid")
        self.state = self.base / "client-state"
        self.hubstate = self.base / "hub-state"
        self.root = self.base / "brain"
        self.lane = self.root / "raw/workspaces/worker-a"
        self.lane.mkdir(parents=True)
        (self.lane / "LANE.md").write_text("---\nproducer: worker-a\n---\nOwner-owned contract.\n")
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge/private.md").write_text("Private brain fixture.\n")
        self.hubcfg = dict(client_id="worker-a", lane="worker-a", remote=self.config["remote"], sources={"method": "method.md"})

    def tearDown(self):
        self.temp.cleanup()

    def run_client(self):
        return client.run(self.config, self.state)

    def import_items(self, **kw):
        return importer.import_client(self.hubcfg, self.hubstate, self.root, apply=True, **kw)

    def files(self):
        return {str(p.relative_to(self.base)): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.base.rglob("*") if p.is_file() and not p.is_symlink()}

    def add_payload(self, name, raw, symlink=False):
        spool = Path(self.config["spool"])
        p = spool / name
        if symlink:
            p.symlink_to(raw)
        else:
            p.write_bytes(raw)
        git(spool, "add", "--", name)
        git(spool, "commit", "-m", "Fixture malformed intake")
        git(spool, "push", self.config["remote"], "HEAD:refs/heads/main")

    def test_assessment_is_zero_write_and_selects_only_named_section(self):
        before = self.files()
        result = collector.assess(self.config)
        self.assertTrue(result["ok"])
        self.assertEqual(before, self.files())
        self.assertIn("Repeat the checked workflow", result["items"][0]["body"])
        self.assertNotIn("Unselected private", json.dumps(result))

    def test_import_plan_has_no_writes_or_network(self):
        before = self.files()
        result = importer.import_client(self.hubcfg, self.hubstate, self.root)
        self.assertFalse(result["writes"])
        self.assertFalse(result["network"])
        self.assertEqual(before, self.files())

    def test_round_trip_versions_and_idempotency_never_promote(self):
        delivered = self.run_client()
        first = self.import_items()
        files = {p.name: p.read_bytes() for p in self.lane.glob("*.md")}
        self.run_client()
        second = self.import_items()
        self.assertEqual(first["head"], second["head"])
        self.assertEqual(files, {p.name: p.read_bytes() for p in self.lane.glob("*.md")})
        self.assertEqual(first["imported_at"], second["imported_at"])
        self.assertEqual(delivered["delivery"]["state"], "delivered")
        self.assertEqual(first["promotion"], "not-evaluated")
        self.assertEqual(len(list((self.root / "knowledge").glob("*"))), 1)
        (self.source / "method.md").write_text("# Keep\nAn updated method.\n")
        self.run_client()
        self.import_items()
        self.assertEqual(len(list(self.lane.glob("method-*.md"))), 2)

    def test_failed_push_retries_committed_work_with_no_source_change(self):
        real = client.git
        def failed(repo, *args, **kw):
            if args[0] == "push":
                raise IntakeError("git_push_failed")
            return real(repo, *args, **kw)
        with patch.object(client, "git", failed), self.assertRaises(IntakeError):
            self.run_client()
        head = git(self.config["spool"], "rev-parse", "HEAD").stdout
        state = json.loads((self.state / "contribution.json").read_text())
        self.assertEqual(state["delivery"]["state"], "error")
        self.assertTrue(state["collection"]["succeeded_at"])
        self.run_client()
        self.assertEqual(head, git(self.config["spool"], "rev-parse", "HEAD").stdout)
        self.assertEqual(self.import_items()["imported_current"], 1)

    def test_receive_only_and_hub_outage_preserve_recoverability(self):
        self.run_client()
        received = self.import_items(receive_only=True)
        self.assertEqual(received["state"], "received")
        self.assertFalse(list(self.lane.glob("method-*.md")))
        real = importer.git
        def failed(repo, *args, **kw):
            if args[0] == "fetch":
                raise IntakeError("git_fetch_failed")
            return real(repo, *args, **kw)
        with patch.object(importer, "git", failed), self.assertRaises(IntakeError):
            self.import_items()
        state = json.loads((self.hubstate / "intake-worker-a.json").read_text())
        self.assertEqual(state["state"], "error")
        self.assertEqual(state["received_at"], received["received_at"])
        recovered = self.import_items()
        self.assertEqual(recovered["imported_current"], 1)
        self.assertNotIn("reason", recovered)

    def test_missing_empty_oversize_and_symlink_sources(self):
        path = self.source / "method.md"
        for kind in ("missing", "empty", "oversize", "symlink"):
            with self.subTest(kind=kind):
                if path.exists() or path.is_symlink():
                    path.unlink()
                if kind == "empty": path.write_text("")
                if kind == "oversize": path.write_text("x" * (collector.MAX_SOURCE + 1))
                if kind == "symlink": path.symlink_to(self.root / "knowledge/private.md")
                result = collector.assess(self.config)
                self.assertFalse(result["items"])
                self.assertEqual(result["ok"], kind == "empty")

    def test_traversal_and_directory_links_are_rejected(self):
        for name in ("../brain/knowledge/private.md", "/etc/passwd", "a/../../private.md"):
            self.config["selectors"][0]["path"] = name
            self.assertFalse(collector.assess(self.config)["ok"])
        (self.source / "linked").symlink_to(self.root / "knowledge", target_is_directory=True)
        self.config["selectors"][0]["path"] = "linked/private.md"
        self.assertFalse(collector.assess(self.config)["ok"])

    def test_filtered_lines_leave_visible_omissions(self):
        secret = "ghp_" + "aB3dE5" * 8
        (self.source / "method.md").write_text("# Keep\nKeep this rule.\n" + secret + "\nBudget $300\nAddress 192.0.2.1\n")
        item = collector.assess(self.config)["items"][0]
        self.assertNotIn(secret, item["body"])
        self.assertIn("line withheld", item["body"])

    def test_malformed_path_type_and_secret_payloads_are_rejected_without_body_logs(self):
        self.run_client()
        bad = copy.deepcopy(collector.assess(self.config)["items"][0])
        bad["body"] = "ghp_" + "aB3dE5" * 8
        bad["capture_id"] = collector.digest(collector.identity(bad))
        self.add_payload("items/" + bad["capture_id"] + ".json", encoded(bad))
        self.add_payload("outside.json", b'{}')
        self.add_payload("items/" + "a" * 64 + ".json", str(self.root / "knowledge/private.md"), symlink=True)
        with self.assertRaises(IntakeError): self.import_items()
        state = (self.hubstate / "intake-worker-a.json").read_text()
        self.assertNotIn(bad["body"], state)
        self.assertNotIn("Private brain fixture", state)
        self.assertEqual(len(json.loads(state)["rejections"]), 3)
        self.assertEqual(len(list(self.lane.glob("method-*.md"))), 1)

    def test_hub_controls_source_and_lane_mapping(self):
        self.run_client()
        self.hubcfg["sources"] = {"another-source": "method.md"}
        with self.assertRaises(IntakeError): self.import_items()
        self.assertFalse(list(self.lane.glob("method-*.md")))
        self.hubcfg["lane"] = "../../knowledge"
        with self.assertRaises(IntakeError): self.import_items()

    def test_capture_collision_refuses_overwrite_and_linked_destination(self):
        self.run_client()
        self.import_items()
        p = next(self.lane.glob("method-*.md"))
        p.write_text("Owner changed this capture.\n")
        with self.assertRaises(IntakeError): self.import_items()
        self.assertEqual(p.read_text(), "Owner changed this capture.\n")
        p.unlink()
        p.symlink_to(self.root / "knowledge/private.md")
        with self.assertRaises(OSError): self.import_items()
        self.assertEqual((self.root / "knowledge/private.md").read_text(), "Private brain fixture.\n")

    def test_one_writer_lock_and_explicit_git_identity(self):
        self.state.mkdir()
        with locked(self.state / "contribute.lock"), self.assertRaises(IntakeError): self.run_client()
        git(self.config["spool"], "config", "--local", "--unset", "user.email")
        with self.assertRaises(IntakeError): self.run_client()

    def test_interrupted_unpublished_write_does_not_block_retry_or_get_sent(self):
        (Path(self.config["spool"]) / "items/.intake-tmp-interrupted").write_text("Incomplete unpublished data")
        self.run_client()
        imported = self.import_items()
        self.assertEqual(imported["imported_current"], 1)
        self.assertNotIn("intake-tmp", git(self.config["spool"], "ls-files").stdout)
        self.assertIn('topics: ["method"]', next(self.lane.glob("method-*.md")).read_text())

    def test_hub_rejects_source_path_substitution(self):
        self.run_client()
        self.hubcfg["sources"]["method"] = "different.md"
        with self.assertRaises(IntakeError): self.import_items()
        self.assertFalse(list(self.lane.glob("method-*.md")))

    def test_receipts_cannot_be_reused_for_another_archive(self):
        self.run_client()
        self.import_items()
        other = self.base / "other"
        (other / "raw/workspaces/worker-a").mkdir(parents=True)
        (other / "raw/workspaces/worker-a/LANE.md").write_text("Owner fixture.")
        with self.assertRaisesRegex(IntakeError, "another_archive"):
            importer.import_client(self.hubcfg, self.hubstate, other, apply=True)
        self.assertEqual(len(list((other / "raw/workspaces/worker-a").glob("*"))), 1)

    def test_heading_prefix_cannot_select_a_different_numbered_section(self):
        (self.source / "method.md").write_text("# 4.10 Private section\nLeave this out.\n# 4.1 Allowed section\nKeep this rule.\n")
        self.config["selectors"][0]["argument"] = ["4.1"]
        body = collector.assess(self.config)["items"][0]["body"]
        self.assertIn("Keep this rule", body)
        self.assertNotIn("Leave this out", body)

    def test_forced_command_allows_only_own_intake_and_no_shell(self):
        allowed = server.command(self.config["remote"], "intake.git", "git-upload-pack 'intake.git'")
        self.assertEqual(allowed[-1], self.config["remote"])
        for command in ("sh", "id", "git-upload-pack 'brain.git'", "git-upload-pack '../brain.git'", "git-receive-pack other.git", "git-upload-pack intake.git; id", "git-upload-pack --help", "git-upload-pack intake.git extra"):
            with self.subTest(command=command), self.assertRaises(IntakeError):
                server.command(self.config["remote"], "intake.git", command)

    def test_server_refuses_tags_deletion_and_history_rewrites(self):
        self.run_client()
        spool, remote = self.config["spool"], self.config["remote"]
        git(spool, "tag", "unexpected")
        for spec in ("refs/tags/unexpected", ":refs/heads/main"):
            self.assertNotEqual(git(spool, "push", remote, spec, check=False).returncode, 0)
        (self.source / "method.md").write_text("# Keep\nChanged rule.\n")
        self.run_client()
        self.assertNotEqual(git(spool, "push", "--force", remote, "HEAD~1:refs/heads/main", check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
