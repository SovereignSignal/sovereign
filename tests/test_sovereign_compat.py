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

if __name__ == '__main__': unittest.main()
