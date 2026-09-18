"""Name migration must preserve destination choice and the existing command surface."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from sovereign_config import pointer
from sovereign_hub import core


class Compatibility(unittest.TestCase):
    def test_existing_environment_then_pointer_then_new_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            for key in ('ROOT', 'LANE', 'CORE', 'HOST'):
                with self.subTest(key=key):
                    p = Path(tmp) / ('.brain-' + key.lower())
                    env = {'BRAIN_' + key: 'old-env', 'SOVEREIGN_' + key: 'new-env'}
                    p.write_text('old-pointer\n')
                    self.assertEqual(pointer(p, env), 'old-env')
                    del env['BRAIN_' + key]
                    self.assertEqual(pointer(p, env), 'old-pointer')
                    p.unlink()
                    self.assertEqual(pointer(p, env), 'new-env')
                    self.assertFalse(p.exists())
            env = {'SOVS_VAULT': 'old-vault', 'SOVEREIGN_ROOT': 'new-root'}
            self.assertEqual(pointer(Path(tmp) / '.brain-root', env), 'old-vault')

    def test_shell_and_python_choose_the_same_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '.brain-root'
            base = {'HOME': tmp, 'PATH': '/usr/bin:/bin', 'SOVEREIGN_ROOT': 'new-root'}
            for legacy in ('none', 'pointer', 'environment'):
                with self.subTest(legacy=legacy):
                    env = dict(base)
                    if legacy == 'pointer': p.write_text('old-pointer\n')
                    if legacy == 'environment': env['SOVS_VAULT'] = 'old-env'
                    cp = subprocess.run(['/bin/bash', '-c', '. "$1"; _sov_pointer "$2"', '_', str(ROOT / 'bin/_sov-config.sh'), str(p)], env=env, capture_output=True, text=True, check=True)
                    self.assertEqual(cp.stdout, pointer(p, env))

    def test_old_commands_are_links_and_help_does_not_write(self):
        aliases = sorted((ROOT / 'bin').glob('brain-*')) + [ROOT / 'bin/new-brain.sh']
        self.assertEqual(len(aliases), 18)
        with tempfile.TemporaryDirectory() as tmp:
            env = {'HOME': tmp, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'SOV_PYTHON': sys.executable, 'PYTHONDONTWRITEBYTECODE': '1', 'SOV_STATE_DIR': tmp + '/state'}
            for command in aliases:
                with self.subTest(command=command.name):
                    self.assertTrue(command.is_symlink())
                    self.assertTrue(command.resolve().is_file())
                    self.assertTrue(command.resolve().name.startswith('sov-'))
                    runner = '/bin/bash' if 'bash' in command.read_text().splitlines()[0] else sys.executable
                    cp = subprocess.run([runner, str(command), '--help'], cwd=tmp, env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
                    self.assertTrue(cp.stdout.strip())
            self.assertEqual(list(Path(tmp).rglob('*')), [])

    def test_new_root_selects_archive_and_old_pointer_still_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old, new = home / 'old', home / 'new'
            for root, label in ((old, 'OLD'), (new, 'NEW')):
                (root / 'knowledge').mkdir(parents=True)
                (root / 'knowledge/topic.md').write_text('# Topic\n' + label)
            env = {'HOME': tmp, 'PATH': '/usr/bin:/bin', 'SOVEREIGN_ROOT': str(new), 'PYTHONDONTWRITEBYTECODE': '1'}
            args = [sys.executable, str(ROOT / 'bin/sov-load'), 'topic']
            cp = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
            self.assertIn('NEW', cp.stdout)
            (home / '.brain-root').write_text(str(old))
            cp = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
            self.assertIn('OLD', cp.stdout)
            self.assertNotIn('NEW', cp.stdout)

    def test_skeleton_and_template_law_match(self):
        self.assertEqual((ROOT / 'CLAUDE.md').read_bytes(), (ROOT / 'skeleton/CLAUDE.md').read_bytes())

    def test_gate_and_curator_root_resolution_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '.brain-root'; p.write_text('/pointer-archive\n')
            for extra, expected in (({'BRAIN_ROOT': '/env-archive'}, '/env-archive'),
                                    ({'BRAIN_ROOT': '/env-archive', 'SOVS_VAULT': '/explicit-archive'}, '/explicit-archive'),
                                    ({'SOVEREIGN_ROOT': '/new-archive'}, '/pointer-archive')):
                env = dict(HOME=tmp, PATH='/usr/bin:/bin', **extra)
                cp = subprocess.run(['/bin/bash', '-c', '. "$1"; printf "%s" "$VAULT"', '_', str(ROOT / 'bin/_curator-lib.sh')], env=env, capture_output=True, text=True, check=True)
                self.assertEqual(cp.stdout, expected)
                self.assertEqual(cp.stdout, env.get('SOVS_VAULT') or pointer(p, env))

    def test_recovered_legacy_engine_gets_runnable_jobs_and_audit_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); b = d / 'engine/bin'; b.mkdir(parents=True)
            for name in ('brain-hub', 'brain-audit'):
                (b / name).write_text('# fixture command\n')
            (d / 'jobs').mkdir(); (d / 'bin').mkdir()
            config = {'destination': tmp, 'archive': str(d / 'archive'), 'max_items': 1}
            core.write_jobs(config)
            for job in core.JOBS:
                self.assertEqual(Path(core.job_definition(config, job)['ProgramArguments'][3]), b / 'brain-hub')
            self.assertEqual(core.run(config, 'audit')['command'][2], str(b / 'brain-audit'))
            (b / 'sov-managed-hub').write_text('# current\n'); (b / 'sov-audit').write_text('# current\n')
            self.assertEqual(Path(core.job_definition(config, 'nightly')['ProgramArguments'][3]), b / 'sov-managed-hub')
            self.assertEqual(core.run(config, 'audit')['command'][2], str(b / 'sov-audit'))

    def test_autocommit_detects_both_supported_audit_names(self):
        import re
        script = (ROOT / 'bin/hub/autocommit').read_text()
        matcher = re.search(r"pgrep -qf '([^']+)'", script).group(1)
        for name in ('curator-run', 'brain-audit', 'sov-audit'):
            self.assertRegex('python3 /fixture/bin/' + name + ' --no-llm', matcher)

    def test_client_aliases_block_local_hub_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve(); tmp = str(home)
            for alias in ('BRAIN_HUB', 'SOVEREIGN_HUB'):
                with patch.dict(os.environ, {'HOME': tmp, alias: 'remote-fixture:/archive'}, clear=True), patch.object(core, 'archive_root', return_value=home / 'archive'):
                    with self.assertRaisesRegex(ValueError, 'Client'):
                        core.install_plan(home / 'archive', home / 'hub', 'fixture-model')
                    with self.assertRaisesRegex(ValueError, 'Client'):
                        core.activation_plan({'destination': str(home / 'hub')})
            with patch.dict(os.environ, {'HOME': tmp, 'SOVEREIGN_HUB': 'new', 'BRAIN_HUB': 'old'}, clear=True):
                (home / '.brain-hub').write_text('pointer')
                self.assertEqual(core.client_hub(), 'old')
                del os.environ['BRAIN_HUB']; self.assertEqual(core.client_hub(), 'pointer')
                (home / '.brain-hub').unlink(); self.assertEqual(core.client_hub(), 'new')

    def test_host_rejoin_preserves_existing_clone_and_legacy_commands(self):
        import ast
        tree = ast.parse((ROOT / 'bin/sov-host-add').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'remote_script' for t in n.targets))
        script = ast.literal_eval(node.value.func.value).format(alias='fixture', keep_host='fixture.invalid', keep_user='git', tmpl_path='template.git', name='fixture', keep_url='fixture:archive.git', core='topic')
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            for directory in ('.ssh', 'brain/.git', 'sovs-brain-template/.git', 'commands'):
                (home / directory).mkdir(parents=True)
            (home / 'sovs-brain-template/bin').symlink_to(ROOT / 'bin')
            (home / '.brain-root').write_text(str(home / 'brain'))
            stub = home / 'commands/git'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/git-calls"\n')
            stub.chmod(0o700)
            env = {'HOME': str(home), 'PATH': str(home / 'commands') + ':/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}
            subprocess.run(['/bin/bash', '-c', script], env=env, capture_output=True, text=True, check=True)
            self.assertEqual((home / '.brain-root').read_text(), str(home / 'brain'))
            self.assertNotIn('clone', (home / 'git-calls').read_text())
            self.assertFalse((home / 'archive').exists())
            for command in ('brain-load', 'brain-capture', 'brain-lane-scope', 'sov-load', 'sov-capture', 'sov-lane-scope'):
                self.assertTrue((home / 'brain-bin' / command).resolve().is_file())

if __name__ == '__main__': unittest.main()
