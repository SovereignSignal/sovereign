import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('lane_delivery', str(ROOT / 'bin/brain-merge-lane'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)

class LaneDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'fixture@example.invalid')
        self.write('raw/workspaces/fixture/LANE.md', '---\n# ---- transport ----\nwrite: git-branch\n---\n')
        self.write('knowledge/card.md', 'original\n'); self.commit('seed')
        self.seed = self.git('rev-parse', 'HEAD')
        self.git('branch', 'lane/fixture')
    def git(self, *a):
        return subprocess.check_output(['git', '-C', str(self.p), *a], stderr=subprocess.PIPE, text=True).strip()
    def write(self, path, body):
        p = self.p/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
    def commit(self, msg):
        self.git('add', '-A'); self.git('commit', '-qm', msg); return self.git('rev-parse', 'HEAD')
    def plan(self): return m.plan(self.p, 'lane/fixture', 'fixture')
    def test_preview_and_apply_only_lane(self):
        self.git('checkout', '-q', 'lane/fixture'); self.write('raw/workspaces/fixture/note.md', 'durable note\n'); self.commit('capture')
        self.git('checkout', '-q', 'main'); before=self.git('rev-parse','HEAD')
        r=self.plan(); self.assertEqual(r['changed_files'], 1); self.assertEqual(self.git('rev-parse','HEAD'), before)
        self.assertEqual(self.git('status','--porcelain'), '')
        result=m.apply(self.p,r); self.assertEqual(result['state'],'accepted'); self.assertEqual(self.plan()['state'],'accepted')
    def test_multiple_merge_bases_use_real_result(self):
        # Criss-cross: A and B are independently merged in opposite orders.
        self.write('knowledge/card.md','main advances\n'); a=self.commit('A')
        self.git('checkout','-q','lane/fixture'); self.write('raw/workspaces/fixture/a.md','capture\n'); b=self.commit('B')
        self.git('merge','--no-ff','-qm','lane catches up',a)
        self.git('checkout','-q','main'); self.git('merge','--no-ff','-qm','hub ingests',b)
        self.git('checkout','-q','lane/fixture'); self.write('raw/workspaces/fixture/b.md','next\n'); self.commit('new capture')
        self.git('checkout','-q','main')
        self.assertEqual(len(self.git('merge-base','--all','main','lane/fixture').splitlines()),2)
        self.assertEqual(self.plan()['changed_files'],1)
    def test_outside_edit_refused_even_if_reverted(self):
        self.git('checkout','-q','lane/fixture'); self.write('knowledge/private.md','private\n'); self.commit('outside')
        self.git('rm','knowledge/private.md'); self.commit('revert'); self.git('checkout','-q','main')
        with self.assertRaises(m.Refused): self.plan()
    def test_owner_contract_cannot_change(self):
        self.git('checkout','-q','lane/fixture'); self.write('raw/workspaces/fixture/LANE.md','---\nwrite: git-branch\n---\nchanged'); self.commit('contract'); self.git('checkout','-q','main')
        with self.assertRaises(m.Refused): self.plan()
    def test_credentials_refused_without_echoing(self):
        token='gh'+'p_'+'A'*35
        self.git('checkout','-q','lane/fixture'); self.write('raw/workspaces/fixture/note.md', token); self.commit('capture'); self.git('checkout','-q','main')
        with self.assertRaises(m.Refused) as ex:self.plan()
        self.assertNotIn(token,str(ex.exception));self.assertIn('credential',str(ex.exception))
    def test_symlink_refused(self):
        self.git('checkout','-q','lane/fixture'); (self.p/'raw/workspaces/fixture/link').symlink_to('/etc/passwd');self.commit('link'); self.git('checkout','-q','main')
        with self.assertRaises(m.Refused):self.plan()
    def test_dirty_checkout_is_preserved(self):
        self.git('checkout','-q','lane/fixture');self.write('raw/workspaces/fixture/note.md','note');self.commit('note');self.git('checkout','-q','main');r=self.plan()
        self.write('knowledge/card.md','owner draft')
        with self.assertRaises(m.Refused):m.apply(self.p,r)
        self.assertEqual((self.p/'knowledge/card.md').read_text(),'owner draft')
    def test_conflict_refused(self):
        self.write('raw/workspaces/fixture/note.md','main');self.commit('main')
        self.git('checkout','-q','lane/fixture');self.write('raw/workspaces/fixture/note.md','lane');self.commit('lane');self.git('checkout','-q','main')
        with self.assertRaises(m.Refused):self.plan()
    def test_receipt_records_accepted_source(self):
        r=dict(lane='fixture',source_head=self.seed,state='accepted');m.receipt(self.p,r)
        self.assertEqual(json.loads((self.p/'.git/sovereign-delivery.json').read_text())['lanes']['fixture'],r)

if __name__ == '__main__':unittest.main()
