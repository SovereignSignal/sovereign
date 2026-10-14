import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'connectors/harness/_lib/mirror-common.sh'
MIRROR=ROOT/'connectors/harness/claude-code/mirror.sh'

class MirrorFailures(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.home=self.base/'home';self.home.mkdir()
        self.stage=self.base/'stage';self.stage.mkdir()
        self.mem=self.home/'.claude/projects/project/memory';self.mem.mkdir(parents=True)
        self.dest=self.stage/'raw/tools/claude-code-fixture';self.dest.mkdir(parents=True)
        (self.dest/'keep.md').write_text('last good capture')
        self.env=dict(os.environ,HOME=str(self.home),BRAIN_ROOT='',BRAIN_HOST='fixture',BRAIN_LANE='',BRAIN_STAGE=str(self.stage))
    def mirror(self):return subprocess.run(['bash',str(MIRROR)],env=self.env,capture_output=True,text=True)
    def test_failed_sanitizer_preserves_destination_and_does_not_echo_content(self):
        token='gh'+'p_'+'A'*35
        (self.mem/'note.md').write_text(token)
        stub=self.base/'stub';stub.mkdir();red=stub/'python3'
        # The mirror runs the sanitizer on the interpreter sov resolved (SOV_PYTHON), never
        # on whatever python3 is first on PATH, so the failure is injected there.
        self.env['SOV_PYTHON']=str(red)
        red.write_text('#!/bin/sh\necho "private diagnostic" >&2\nexit 1\n');red.chmod(0o755)
        result=self.mirror()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual([p.name for p in self.dest.iterdir()],['keep.md'])
        self.assertNotIn(token,result.stdout+result.stderr)
        self.assertNotIn('private diagnostic',result.stdout+result.stderr)
    def test_link_cannot_copy_or_change_external_file(self):
        external=self.base/'private.md';external.write_text('private')
        (self.mem/'note.md').symlink_to(external)
        (self.mem/'real.md').write_text('ordinary note')
        result=self.mirror();self.assertNotEqual(result.returncode,0)
        self.assertEqual(external.read_text(),'private')
        self.assertEqual([p.name for p in self.dest.iterdir()],['keep.md'])
    def test_publish_retries_push_even_without_new_changes_and_returns_error(self):
        repo=self.base/'repo';repo.mkdir();bare=self.base/'exchange.git'
        def git(*a):return subprocess.run(['git','-C',str(repo),*a],check=True,capture_output=True,text=True).stdout.strip()
        git('init','-qb','lane/fixture');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
        dest=repo/'raw/workspaces/fixture/claude-code';dest.mkdir(parents=True);(dest/'note.md').write_text('capture')
        git('add','-A');git('commit','-qm','capture');git('remote','add','origin',str(bare))
        self.env['BRAIN_ROOT']=str(repo)
        cmd='. '+shlex.quote(str(COMMON))+'; sov_git_publish_locked '+shlex.quote(str(dest))+' capture lane/fixture'
        first=subprocess.run(['bash','-c',cmd],env=self.env,capture_output=True,text=True)
        self.assertNotEqual(first.returncode,0)
        subprocess.run(['git','init','-q','--bare',str(bare)],check=True)
        second=subprocess.run(['bash','-c',cmd],env=self.env,capture_output=True,text=True)
        self.assertEqual(second.returncode,0,second.stderr)
        head=subprocess.check_output(['git','--git-dir',str(bare),'rev-parse','lane/fixture'],text=True).strip()
        self.assertEqual(head,git('rev-parse','HEAD'))
    def test_producer_without_owner_permission_cannot_mirror(self):
        vault=self.base/'vault';lane=vault/'raw/workspaces/fixture';lane.mkdir(parents=True)
        (lane/'LANE.md').write_text('---\nwrite: git-branch\n---\n')
        self.env.update(BRAIN_ROOT=str(vault),BRAIN_LANE='fixture')
        (self.mem/'note.md').write_text('scoped source')
        result=self.mirror();self.assertNotEqual(result.returncode,0)
        self.assertFalse((lane/'claude-code').exists())

if __name__=='__main__':unittest.main()
