import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import brain_local as m
ROOT = Path(__file__).resolve().parents[1]

class LocalArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'My archive'
        m.create(self.root, ROOT)
        self.root = m.archive_root(self.root)
    def test_empty_home_needs_no_tools_or_pointers(self):
        self.assertEqual(m.archive_root(self.root), self.root)
        self.assertEqual(m.listing(self.root)['total'], 0)
    def test_existing_folder_never_overwritten(self):
        (self.root / 'owner.txt').write_text('keep')
        with self.assertRaises(FileExistsError): m.create(self.root, ROOT)
        self.assertEqual((self.root / 'owner.txt').read_text(), 'keep')
    def test_capture_search_reopen_and_duplicate_titles(self):
        one=m.capture(self.root,'Reusable method','Some useful finding')
        two=m.capture(self.root,'Reusable method','Another finding')
        self.assertNotEqual(one['path'],two['path'])
        self.assertIn('Some useful finding', m.read(self.root,one['path'])['body'])
        self.assertEqual(m.listing(self.root,'useful')['total'],1)
        self.assertEqual(m.listing(self.root)['total'],2)
    def test_capture_redacts_before_file_exists(self):
        token='gh'+'p_'+'A'*35
        result=m.capture(self.root,'My note',token)
        self.assertEqual(result['redactions'],1)
        self.assertNotIn(token,m.read(self.root,result['path'])['body'])
    def test_external_file_refused(self):
        outside=self.base / 'outside.md';outside.write_text('private')
        for path in ('../outside.md',str(outside), 'archive/cold.md'):
            with self.assertRaises((ValueError,FileNotFoundError)):m.read(self.root,path)
    def test_symlink_read_and_capture_refused(self):
        outside=self.base/'outside';outside.mkdir();(outside/'note.md').write_text('private')
        (self.root/'raw/workspaces/owner').symlink_to(outside)
        with self.assertRaises(ValueError):m.capture(self.root,'note','body')
        with self.assertRaises(ValueError):m.read(self.root,'raw/workspaces/owner/note.md')
        self.assertEqual(len(list(outside.iterdir())),1)
    def test_title_cannot_inject_frontmatter(self):
        with self.assertRaises(ValueError):m.capture(self.root,'title\nsource: other','body')
    def test_cli_with_empty_home_and_minimal_path(self):
        home=self.base/'new-home';home.mkdir()
        r=subprocess.run([sys.executable,str(ROOT/'bin/sov-local')],input=json.dumps({'action':'list','root':str(self.root)}),text=True,capture_output=True,env={'HOME':str(home),'PATH':'/usr/bin:/bin'})
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['total'],0)
        self.assertEqual(list(home.glob('.brain*')),[])

def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True).stdout


def tools_without_git(base):
    """A PATH holding the tools sov-init needs, minus git."""
    bin_dir = base / 'no-git-bin'; bin_dir.mkdir()
    for tool in ('rsync', 'sed', 'cp', 'mkdir', 'basename', 'dirname', 'uname'):
        found = subprocess.run(['/usr/bin/which', tool], capture_output=True, text=True).stdout.strip()
        if found:
            (bin_dir / tool).symlink_to(found)
    return bin_dir


TRACKED = {'.gitignore', 'CLAUDE.md', '.obsidian/templates/note.md', 'raw/tools/.gitkeep',
           'raw/workspaces/.gitkeep', 'workstreams/.gitkeep', 'knowledge/entities/.gitkeep',
           'knowledge/concepts/.gitkeep', 'knowledge/syntheses/.gitkeep'}


class ArchiveHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def test_app_archive_is_a_repository_from_the_first_commit(self):
        out = m.create(self.base / 'My archive', ROOT)
        root = Path(out['root'])
        self.assertIs(out['git'], True); self.assertNotIn('git_message', out)
        self.assertTrue((root / '.git').is_dir())
        ignored = (root / '.gitignore').read_text().splitlines()
        for entry in ('archive/', 'repos/', '.obsidian/workspace*'):
            self.assertIn(entry, ignored)
        self.assertEqual(git(root, 'log', '--format=%s').splitlines(), ['new instance: My archive (from Sovereign)'])
        self.assertEqual(set(git(root, 'ls-files').splitlines()), TRACKED)
        # The five folders exist and keep files, the ignored two stay out of history.
        for folder in m.FOLDERS:
            self.assertTrue(any((root / folder).rglob('.gitkeep')), folder)
        self.assertEqual(git(root, 'status', '--porcelain'), '')

    def test_missing_identity_uses_a_repository_local_one(self):
        config = self.base / 'gitconfig'; config.write_text('[user]\n\tuseConfigOnly = true\n')
        before = config.read_text()
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_NOSYSTEM': '1'}):
            for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL', 'EMAIL'):
                os.environ.pop(key, None)
            out = m.create(self.base / 'Fresh', ROOT)
            root = Path(out['root'])
            self.assertIs(out['git'], True)
            self.assertEqual(git(root, 'log', '--format=%an <%ae>').strip(), 'Sovereign <sovereign@localhost>')
            self.assertEqual(git(root, 'config', '--local', 'user.name').strip(), 'Sovereign')
        self.assertEqual(config.read_text(), before)

    def test_configured_identity_is_left_alone(self):
        config = self.base / 'gitconfig'; config.write_text('[user]\n\tname = Owner\n\temail = owner@example.test\n')
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_NOSYSTEM': '1'}):
            for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
                os.environ.pop(key, None)
            root = Path(m.create(self.base / 'Owned', ROOT)['root'])
            self.assertEqual(git(root, 'log', '--format=%an <%ae>').strip(), 'Owner <owner@example.test>')
            local = subprocess.run(['git', 'config', '--local', '--get', 'user.name'], cwd=root, capture_output=True)
        self.assertNotEqual(local.returncode, 0)

    def test_no_git_still_creates_the_archive_and_says_so(self):
        empty = self.base / 'empty-bin'; empty.mkdir()
        with mock.patch.dict(os.environ, {'PATH': str(empty)}):
            out = m.create(self.base / 'Plain', ROOT)
        root = m.archive_root(out['root'])
        self.assertIs(out['git'], False)
        self.assertEqual(out['git_message'], 'git was not found; the archive has no history yet.')
        self.assertFalse((root / '.git').exists())
        self.assertIn('repos/', (root / '.gitignore').read_text())
        self.assertTrue((root / 'CLAUDE.md').is_file())

    def test_app_engine_reports_missing_git(self):
        empty = self.base / 'empty-bin'; empty.mkdir()
        r = subprocess.run([sys.executable, str(ROOT / 'bin/sov-local')], input=json.dumps({'action': 'create', 'root': str(self.base / 'Via app')}),
                           text=True, capture_output=True, env={'HOME': str(self.base), 'PATH': str(empty)})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIs(out['git'], False); self.assertIn('no history yet', out['git_message'])

    def run_sov_init(self, target, path):
        return subprocess.run(['/bin/bash', str(ROOT / 'bin/sov-init'), str(target), 'CLI Archive'], capture_output=True, text=True,
                              env={'HOME': str(self.base), 'PATH': path, 'SOV_PYTHON': sys.executable})

    def test_sov_init_shares_the_same_first_commit(self):
        target = self.base / 'cli'
        r = self.run_sov_init(target, os.environ['PATH'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Archive 'CLI Archive' created", r.stdout)
        self.assertEqual(git(target, 'log', '--format=%s').splitlines(), ['new instance: CLI Archive (from Sovereign)'])
        self.assertEqual((target / '.gitignore').read_text(), m.GITIGNORE)
        tracked = set(git(target, 'ls-files').splitlines())
        self.assertTrue({'CLAUDE.md', '.gitignore', '.obsidian/templates/note.md', 'workstreams/.gitkeep'} <= tracked)
        self.assertFalse(any(p.startswith(('archive/', 'repos/')) for p in tracked))
        self.assertNotIn('{{SOVEREIGN_NAME}}', (target / 'CLAUDE.md').read_text())

    def test_sov_init_leaves_an_existing_repository_alone(self):
        target = self.base / 'existing'; target.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=target, check=True)
        (target / 'mine.txt').write_text('owner work')
        r = self.run_sov_init(target, os.environ['PATH'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('is already a git repository; left as is.', r.stderr)
        self.assertEqual(subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=target, capture_output=True).returncode, 128)
        self.assertNotEqual(subprocess.run(['git', 'config', '--local', 'user.name'], cwd=target, capture_output=True).returncode, 0)
        self.assertFalse((target / '.gitignore').exists())
        self.assertIn('mine.txt', git(target, 'status', '--porcelain'))

    def test_linked_target_makes_no_repository_elsewhere(self):
        elsewhere = self.base / 'elsewhere'; elsewhere.mkdir()
        link = self.base / 'linked'; link.symlink_to(elsewhere)
        out = m.init_repository(link, 'Linked')
        self.assertIs(out['git'], False); self.assertIn('links to another folder', out['git_message'])
        self.assertEqual(list(elsewhere.iterdir()), [])
        r = self.run_sov_init(link, os.environ['PATH'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('links to another folder', r.stderr)
        self.assertFalse((elsewhere / '.git').exists())

    def test_find_git_mirrors_the_git_guard_order(self):
        guard = (ROOT / 'bin/git-guard/git').read_text()
        first = re.search(r'xcode-select -p[^\n]*then exec (\S+) ', guard).group(1)
        others = tuple(re.search(r'for g in ([^;]+); do', guard).group(1).split())
        self.assertEqual((first, others), (m.TOOLS_GIT, m.OTHER_GITS))

    def test_sov_init_without_git_still_scaffolds(self):
        target = self.base / 'cli-plain'
        r = self.run_sov_init(target, str(tools_without_git(self.base)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('no history yet', r.stderr)
        self.assertFalse((target / '.git').exists())
        self.assertTrue((target / 'CLAUDE.md').is_file() and (target / '.gitignore').is_file())


if __name__=='__main__':unittest.main()
