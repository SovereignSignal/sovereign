"""Source publication cannot leak recovery refs or overwrite divergent remote work."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from sovereign_hub import kit


class Publication(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / 'source'; self.remote = self.base / 'published.git'
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.call('git', 'init', '-q', '-b', 'main', str(self.repo))
        self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'README').write_text('source')
        self.git('add', 'README'); self.git('commit', '-qm', 'fixture')
        self.git('branch', 'docs/lane-source-map'); self.git('tag', '-a', 'v1', '-m', 'fixture')
        self.git('update-ref', 'refs/recovery/private', 'HEAD')
        self.git('branch', 'private-work')
        self.call('git', 'init', '--bare', '-q', str(self.remote))
        self.git('remote', 'add', 'publication', str(self.remote))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        return subprocess.check_output(args, env=self.env, text=True).strip()

    def git(self, *args):
        return self.call('git', '-C', str(self.repo), *args)

    def refs(self):
        return self.call('git', '-C', str(self.remote), 'for-each-ref', '--format=%(refname) %(objectname)')

    def test_plan_writes_nothing_and_publish_sends_only_the_allowlisted_refs(self):
        plan = kit.publication_plan(self.repo, ['publication'])
        self.assertEqual(self.refs(), '')
        self.assertEqual(set(plan['publication']['refs']), {'refs/heads/main', 'refs/heads/docs/lane-source-map', 'refs/tags/v1'})
        self.assertEqual(kit._publish(self.repo, 'publication', plan['publication'])['state'], 'pushed')
        self.assertEqual({x.split()[0] for x in self.refs().splitlines()}, set(plan['publication']['refs']))

    def test_divergent_remote_fails_atomically_without_overwrite_or_deletion(self):
        plan = kit.publication_plan(self.repo, ['publication'])['publication']
        self.assertEqual(kit._publish(self.repo, 'publication', plan)['state'], 'pushed')
        self.git('checkout', '-qb', 'remote-work')
        (self.repo / 'README').write_text('remote owner work')
        self.git('commit', '-qam', 'remote work'); self.git('push', '-q', 'publication', 'HEAD:main', 'HEAD:refs/heads/keep')
        before = self.refs()
        self.git('checkout', '-q', 'main'); self.git('tag', 'v2')
        plan = kit.publication_plan(self.repo, ['publication'])['publication']
        result = kit._publish(self.repo, 'publication', plan)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.refs(), before)

    def test_missing_docs_and_malformed_targets_fail_before_any_push(self):
        for targets in ('publication', [None], ['--mirror'], [''], ['bad\nremote']):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                kit.publication_plan(self.repo, targets)
        self.git('branch', '-D', 'docs/lane-source-map')
        with self.assertRaisesRegex(ValueError, 'docs/lane-source-map'):
            kit.publication_plan(self.repo, ['publication'])
        self.assertEqual(self.refs(), '')

    def test_no_targets_requires_no_repository(self):
        self.assertEqual(kit.publication_plan(self.base / 'absent', []), {})

    def test_timeout_is_recorded_as_failed(self):
        planned = kit.publication_plan(self.repo, ['publication'])['publication']
        with patch.object(kit.subprocess, 'run', side_effect=subprocess.TimeoutExpired('git', 600)):
            self.assertEqual(kit._publish(self.repo, 'publication', planned)['state'], 'failed')

    def test_build_dry_run_and_failure_receipt(self):
        state = self.base / 'state'; state.mkdir()
        inst = {'vault': str(self.base / 'archive'), 'snapshot': {'folder': str(self.base / 'snapshots')},
                'kit': {'key_file': str(self.base / 'key'), 'template_publications': ['publication']}}
        (state / 'hub.json').write_text(json.dumps(inst))
        with patch.object(kit, 'check_key', return_value=self.base / 'key'):
            result = kit.build(inst, state, self.base, self.repo)
            self.assertEqual(result['publications']['publication']['state'], 'planned')
            self.assertFalse((self.base / 'snapshots').exists()); self.assertEqual(self.refs(), '')
            def seal(entries, key, out, executables=()):
                Path(out).write_bytes(b'fixture sealed kit')
            with patch.object(kit, '_seal', side_effect=seal), patch.object(kit, '_publish', return_value={'state': 'failed', 'detail': 'fixture rejection'}):
                with self.assertRaisesRegex(ValueError, 'publication'):
                    kit.build(inst, state, self.base, self.repo, apply=True)
            receipt = json.loads((state / 'hub/kit.json').read_text())
            self.assertEqual(receipt['publications']['publication']['state'], 'failed')


if __name__ == '__main__':
    unittest.main()
