"""Receipt evidence and the existing context hook, against isolated archives."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import brain_local as local

class ContextEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'archive'
        local.create(self.root, ROOT)
        self.root = local.archive_root(self.root)
        self.stamp = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    def receipt(self, path='raw/tools/example/brain-load-usage.md', text=None):
        p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text or f'- {self.stamp} example scope=workstream cards=2 source=startup session=real\n')
        return p

    def test_receipt_proves_preparation_only(self):
        p = self.receipt(); before = p.read_bytes()
        result = local.context_state(self.root)
        self.assertEqual(result['total'], 1)
        self.assertTrue(result['receipts'][0]['prepared'])
        self.assertIsNone(result['receipts'][0]['delivered'])
        self.assertIsNone(result['receipts'][0]['loaded'])
        self.assertEqual(p.read_bytes(), before)

    def test_manual_receipt_remains_a_test(self):
        self.receipt(text=f'- {self.stamp} example scope=workstream cards=1 source=startup session=manual\n')
        self.assertTrue(local.context_state(self.root)['receipts'][0]['test'])

    def test_invalid_or_future_receipt_cannot_look_current(self):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.receipt(text=f'- {future} example scope=core cards=1 source=startup session=x\n- garbage\n')
        self.assertEqual(local.context_state(self.root)['total'], 0)

    def test_latest_receipt_per_producer(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.receipt(text=f'- {self.stamp} new scope=workstream cards=2 source=startup session=x\n- {old} old scope=core cards=1 source=startup session=x\n')
        self.assertEqual(local.context_state(self.root)['receipts'][0]['topic'], 'new')

    def test_nested_producer_lane_is_visible(self):
        self.receipt('raw/workspaces/example/codex/brain-load-usage.md')
        self.assertEqual(local.context_state(self.root)['receipts'][0]['producer'], 'workspaces/example/codex')

    def test_symlink_receipt_and_linked_folder_are_excluded(self):
        outside = self.base / 'outside'; outside.mkdir()
        file = outside / 'brain-load-usage.md'; file.write_text(f'- {self.stamp} secret scope=core cards=1 source=startup session=x\n')
        lane = self.root / 'raw/tools/link'; lane.symlink_to(outside)
        local_lane = self.root / 'raw/tools/file-link'; local_lane.mkdir()
        (local_lane / 'brain-load-usage.md').symlink_to(file)
        self.assertEqual(local.context_state(self.root)['total'], 0)

    def test_hidden_cold_and_deep_receipts_are_excluded(self):
        for path in ('archive/brain-load-usage.md', 'raw/tools/.hidden/brain-load-usage.md', 'raw/workspaces/a/b/c/brain-load-usage.md'):
            self.receipt(path)
        self.assertEqual(local.context_state(self.root)['total'], 0)

    def test_cli_exposes_evidence_without_other_tools(self):
        self.receipt()
        result = subprocess.run([sys.executable, str(ROOT / 'bin/sov-local')], input=json.dumps({'action': 'context', 'root': str(self.root)}), capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'HOME': str(self.base)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['total'], 1)

    def test_existing_codex_hook_reuses_only_reviewed_knowledge(self):
        """Raw candidate stays absent until the fixture owner explicitly promotes it."""
        home = self.base / 'home'; home.mkdir()
        workspace = self.root / 'workstreams/example'; workspace.mkdir()
        trusted = self.root / 'knowledge/concepts/example.md'
        trusted.write_text('# Example\nKeep the source links.\n')
        raw = self.root / 'raw/workspaces/example/candidate.md'; raw.parent.mkdir(parents=True)
        raw.write_text('# Finding\nNEW_REVIEWED_LEARNING\n')
        env = dict(os.environ, HOME=str(home), BRAIN_ROOT=str(self.root), BRAIN_CORE='', BRAIN_HOST='pilot', BRAIN_STAGE=str(self.root), BRAIN_LANE='')
        def run():
            result = subprocess.run([sys.executable, str(ROOT / 'connectors/harness/codex/session-start.py')], input=json.dumps({'cwd': str(workspace), 'session_id': 'pilot-test', 'source': 'startup'}), text=True, capture_output=True, env=env, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
        initial = run(); self.assertIn('Keep the source links.', initial)
        self.assertNotIn('NEW_REVIEWED_LEARNING', initial)
        # Explicit owner promotion in this disposable fixture, not an app auto-approval.
        (self.root / 'knowledge/concepts/finding.md').write_text(raw.read_text())
        trusted.write_text(trusted.read_text()+'\n[[finding]]\n')
        self.assertIn('NEW_REVIEWED_LEARNING', run())
        self.assertTrue(local.context_state(self.root)['receipts'][0]['test'])
        self.assertEqual(raw.read_text(), '# Finding\nNEW_REVIEWED_LEARNING\n')

if __name__ == '__main__': unittest.main()
