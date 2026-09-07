import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
        self.assertFalse((self.root / '.git').exists())
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
        r=subprocess.run([sys.executable,str(ROOT/'bin/brain-local')],input=json.dumps({'action':'list','root':str(self.root)}),text=True,capture_output=True,env={'HOME':str(home),'PATH':'/usr/bin:/bin'})
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['total'],0)
        self.assertEqual(list(home.glob('.brain*')),[])

if __name__=='__main__':unittest.main()
