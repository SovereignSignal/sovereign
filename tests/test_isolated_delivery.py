import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from test_lane_delivery import LaneFixture, ROOT, m


class IsolatedDelivery(LaneFixture, unittest.TestCase):
    def capture(self):
        self.git('checkout', '-q', 'lane/fixture')
        self.write('raw/workspaces/fixture/note.md', 'incoming capture\n')
        source = self.commit('capture')
        self.git('checkout', '-q', 'main')
        return source

    def owner_work(self):
        self.write('knowledge/card.md', 'owner draft\n')
        self.write('workstreams/new.md', 'new untracked draft\n')
        (self.p/'workstreams/binary.bin').write_bytes(b'\x00\xff\x01')
        (self.p/'workstreams/link').symlink_to('new.md')

    def fingerprints(self):
        result = {}
        for path in (self.p/'knowledge/card.md', *sorted((self.p/'workstreams').iterdir())):
            result[str(path.relative_to(self.p))] = path.readlink().as_posix() if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def test_prepare_does_not_touch_live_index_or_files(self):
        self.capture(); self.owner_work()
        before = self.fingerprints()
        prepared = m.prepare(self.p, self.plan())
        self.assertEqual(prepared['state'], 'prepared')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)
        self.assertEqual(self.fingerprints(), before)
        # git status can refresh stat metadata; the logical index must stay equal.
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 1)
        self.assertEqual(self.git('rev-parse', prepared['prepared_ref']), prepared['prepared_commit'])

    def test_promote_preserves_unrelated_modified_untracked_binary_and_link(self):
        source = self.capture(); self.owner_work()
        before = self.fingerprints(); dirty = self.git('status', '--porcelain')
        prepared = m.prepare(self.p, self.plan())
        result = m.promote(self.p, prepared)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(self.fingerprints(), before)
        self.assertEqual(self.git('status', '--porcelain'), dirty)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        self.assertEqual(self.git('show', 'HEAD:knowledge/card.md'), 'original')
        self.assertEqual(self.git('rev-list', '--parents', '-n', '1', 'HEAD').split()[1:], [self.seed, source])
        self.assertEqual(self.git('rev-parse', 'HEAD^{tree}'), prepared['tree'])

    def test_deleted_owner_file_stays_deleted_and_uncommitted(self):
        self.capture(); (self.p/'knowledge/card.md').unlink()
        prepared = m.prepare(self.p, self.plan()); m.promote(self.p, prepared)
        self.assertFalse((self.p/'knowledge/card.md').exists())
        self.assertEqual(self.git('show', 'HEAD:knowledge/card.md'), 'original')
        self.assertEqual(self.git('status', '--porcelain'), 'D knowledge/card.md')

    def test_owner_edit_during_merge_preparation_survives(self):
        self.capture()
        real_apply = m.apply
        def writing_apply(root, report, **kwargs):
            self.owner_work()
            return real_apply(root, report, **kwargs)
        with mock.patch.object(m, 'apply', side_effect=writing_apply):
            prepared = m.prepare(self.p, self.plan())
        before = self.fingerprints(); m.promote(self.p, prepared)
        self.assertEqual(self.fingerprints(), before)

    def test_new_unrelated_file_after_checks_is_preserved(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        real_run = m.run
        def injecting_run(root, *args, **kwargs):
            if args[:2] == ('merge', '--ff-only'):
                self.write('workstreams/arrived.md', 'arrived during promotion\n')
            return real_run(root, *args, **kwargs)
        with mock.patch.object(m, 'run', side_effect=injecting_run):
            result = m.promote(self.p, prepared)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual((self.p/'workstreams/arrived.md').read_text(), 'arrived during promotion\n')
        self.assertNotIn('workstreams/arrived.md', self.git('ls-tree', '-r', '--name-only', 'HEAD'))

    def test_staged_owner_work_refused_and_preserved(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        self.write('knowledge/card.md', 'staged owner work'); self.git('add', 'knowledge/card.md')
        index = (self.p/'.git/index').read_bytes()
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual((self.p/'.git/index').read_bytes(), index)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)
        self.assertEqual(self.git('show', ':knowledge/card.md'), 'staged owner work')

    def test_untracked_lane_work_refused_and_recoverable(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        self.write('raw/workspaces/fixture/draft.md', 'local lane draft')
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual((self.p/'raw/workspaces/fixture/draft.md').read_text(), 'local lane draft')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)
        self.assertEqual(self.git('rev-parse', prepared['prepared_ref']), prepared['prepared_commit'])
        # Simulate the owner resolving the fixture-only conflict, then retry.
        (self.p/'raw/workspaces/fixture/draft.md').unlink()
        self.assertEqual(m.promote(self.p, prepared)['state'], 'accepted')

    def test_ignored_collision_is_not_overwritten(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        (self.p/'.git/info/exclude').write_text('raw/workspaces/fixture/note.md\n')
        self.write('raw/workspaces/fixture/note.md', 'ignored owner file')
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual((self.p/'raw/workspaces/fixture/note.md').read_text(), 'ignored owner file')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)
        self.assertFalse((self.p/'.git/MERGE_HEAD').exists())

    def test_overlapping_edit_arrives_after_checks_autostash_stays_disabled(self):
        self.write('raw/workspaces/fixture/note.md', 'base'); self.commit('base note')
        self.git('checkout', '-q', 'lane/fixture'); self.git('merge', '--ff-only', 'main'); self.git('checkout', '-q', 'main')
        self.capture(); prepared = m.prepare(self.p, self.plan())
        baseline = self.git('rev-parse', 'HEAD')
        self.git('config', 'merge.autoStash', 'true')
        real_run = m.run
        def injecting_run(root, *args, **kwargs):
            if args[:2] == ('merge', '--ff-only'):
                self.write('raw/workspaces/fixture/note.md', 'late local edit')
            return real_run(root, *args, **kwargs)
        with mock.patch.object(m, 'run', side_effect=injecting_run):
            with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual(self.git('rev-parse', 'HEAD'), baseline)
        self.assertEqual((self.p/'raw/workspaces/fixture/note.md').read_text(), 'late local edit')
        self.assertEqual(self.git('stash', 'list'), '')

    def test_moved_main_keeps_owner_commit(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        self.write('knowledge/card.md', 'new owner commit'); owner = self.commit('owner advances')
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual(self.git('rev-parse', 'HEAD'), owner)
        self.assertEqual((self.p/'knowledge/card.md').read_text(), 'new owner commit')

    def test_failed_preparation_never_aborts_live_owner_work(self):
        self.capture(); self.owner_work(); before = self.fingerprints()
        hook = self.p/'.git/hooks/pre-commit'; hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o755)
        with self.assertRaises(m.Refused): m.prepare(self.p, self.plan())
        self.assertEqual(self.fingerprints(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        self.assertFalse((self.p/'.git/MERGE_HEAD').exists())
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 1)

    def test_injected_git_failure_retains_candidate_and_owner_work(self):
        self.capture(); self.owner_work(); before = self.fingerprints()
        prepared = m.prepare(self.p, self.plan()); real_run = m.run
        def failing_run(root, *args, **kwargs):
            if args[:2] == ('merge', '--ff-only'):
                return subprocess.CompletedProcess(args, 1, b'', b'failure')
            return real_run(root, *args, **kwargs)
        with mock.patch.object(m, 'run', side_effect=failing_run):
            with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual(self.fingerprints(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)
        self.assertEqual(self.git('rev-parse', prepared['prepared_ref']), prepared['prepared_commit'])

    def test_bad_candidate_tree_refused(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        prepared['tree'] = self.git('rev-parse', 'HEAD^{tree}')
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)

    def test_main_advances_between_final_check_and_git_is_not_rewound(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        real_run = m.run; owner = []
        def advancing_run(root, *args, **kwargs):
            if args[:2] == ('merge', '--ff-only'):
                self.write('knowledge/card.md', 'concurrent committed work')
                owner.append(self.commit('concurrent main'))
            return real_run(root, *args, **kwargs)
        with mock.patch.object(m, 'run', side_effect=advancing_run):
            with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertEqual(self.git('rev-parse', 'HEAD'), owner[0])
        self.assertEqual((self.p/'knowledge/card.md').read_text(), 'concurrent committed work')

    def test_git_operation_marker_refuses_without_cleanup_of_owner_state(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        marker = self.p/'.git/MERGE_HEAD'; marker.write_text(prepared['source_head'] + '\n')
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertTrue(marker.exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.seed)

    def test_live_lane_symlink_is_refused(self):
        self.capture(); prepared = m.prepare(self.p, self.plan())
        folder = self.p/'raw/workspaces/fixture'; folder.rename(self.p/'lane-owner-copy')
        folder.symlink_to(self.p/'lane-owner-copy', target_is_directory=True)
        with self.assertRaises(m.Refused): m.promote(self.p, prepared)
        self.assertTrue(folder.is_symlink())
        self.assertFalse((self.p/'lane-owner-copy/note.md').exists())

    def test_receipt_failure_keeps_accepted_state(self):
        self.capture(); self.owner_work()
        real_receipt = m.receipt
        def failing_receipt(root, report):
            if report['state'] == 'accepted': raise OSError('receipt write failed')
            return real_receipt(root, report)
        argv = ['sov-merge-lane', '--root', str(self.p), '--ref', 'lane/fixture', '--lane', 'fixture', '--apply-isolated']
        import contextlib
        import io
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(m, 'receipt', side_effect=failing_receipt), contextlib.redirect_stdout(output):
            code = m.main()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(result['accepted_commit'], self.git('rev-parse', 'HEAD'))
        self.assertFalse((self.p/'.git/sovereign-integration.lock').exists())

    def test_git_error_after_advancement_reports_accepted_with_failure_exit(self):
        self.capture(); real_run = m.run
        def late_error(root, *args, **kwargs):
            result = real_run(root, *args, **kwargs)
            if args[:2] == ('merge', '--ff-only'):
                return subprocess.CompletedProcess(args, 1, result.stdout, b'late error')
            return result
        import contextlib
        import io
        output = io.StringIO()
        argv = ['sov-merge-lane', '--root', str(self.p), '--ref', 'lane/fixture', '--lane', 'fixture', '--apply-isolated']
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(m, 'run', side_effect=late_error), contextlib.redirect_stdout(output):
            code = m.main()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(result['accepted_commit'], self.git('rev-parse', 'HEAD'))
        self.assertIn('warning', result)

    def test_existing_integration_lock_is_not_removed(self):
        lock = self.p/'.git/sovereign-integration.lock'; lock.write_text('another process\n')
        with self.assertRaises(m.Refused):
            with m.integration_lock(self.p): pass
        self.assertEqual(lock.read_text(), 'another process\n')

    def test_cli_receipt_and_cleanup(self):
        source = self.capture(); self.owner_work(); before = self.fingerprints()
        output = subprocess.check_output([sys.executable, str(ROOT/'bin/sov-merge-lane'), '--root', str(self.p),
                                         '--ref', 'lane/fixture', '--lane', 'fixture', '--apply-isolated'], text=True)
        result = json.loads(output)
        self.assertEqual(result['state'], 'accepted')
        receipt = json.loads((self.p/'.git/sovereign-delivery.json').read_text())['lanes']['fixture']
        self.assertEqual(receipt['source_head'], source)
        self.assertEqual(receipt['accepted_commit'], self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.fingerprints(), before)
        self.assertEqual(self.git('for-each-ref', '--format=%(refname)', 'refs/sovereign/prepared'), '')
        self.assertFalse((self.p/'.git/sovereign-integration.lock').exists())
