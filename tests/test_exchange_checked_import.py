import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_lane_delivery import LaneFixture, ROOT


class ExchangeCheckedImport(LaneFixture, unittest.TestCase):
    def exchange(self):
        self.remote_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.remote_tmp.cleanup)
        remote = Path(self.remote_tmp.name) / 'exchange.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        self.git('remote', 'add', 'exchange', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-q', 'exchange', 'main', 'lane/fixture')
        home = Path(self.remote_tmp.name) / 'home'
        (home / 'Library/Logs').mkdir(parents=True)
        env = dict(os.environ, HOME=str(home), SOVS_VAULT=str(self.p),
                   SOV_HUB_EXCHANGE='exchange', SOV_TEMPLATE=str(ROOT))
        subprocess.run(['bash', str(ROOT/'bin/hub/exchange-sync')], env=env,
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return (home/'Library/Logs/brain-exchange-sync.log').read_text()

    def test_criss_cross_accepts_and_preserves_unrelated_draft(self):
        self.write('knowledge/card.md', 'main advances\n'); a=self.commit('A')
        self.git('checkout','-q','lane/fixture')
        self.write('raw/workspaces/fixture/a.md','capture\n'); b=self.commit('B')
        self.git('merge','--no-ff','-qm','lane catches up',a)
        self.git('checkout','-q','main'); self.git('merge','--no-ff','-qm','hub ingests',b)
        self.git('checkout','-q','lane/fixture')
        self.write('raw/workspaces/fixture/b.md','next\n'); head=self.commit('next capture')
        self.git('checkout','-q','main')
        self.write('knowledge/card.md','owner draft\n')
        log=self.exchange()
        self.assertIn('in: merged lane/fixture', log)
        self.git('merge-base','--is-ancestor',head,'main')
        self.assertEqual((self.p/'knowledge/card.md').read_text(),'owner draft\n')
        self.assertEqual(self.git('rev-parse','main'),self.git('rev-parse','exchange/main'))

    def test_canonical_push_is_logged_under_the_remote_it_pushes(self):
        # sov-status keys the exchange record by this label and the console looks it up by
        # remote name; a label that is not the remote leaves the canonical copy unwatched.
        log = self.exchange()
        self.assertIn('out: vault -> origin ok', log)
        self.assertNotIn('-> gitea', log)

    def test_outside_edit_refused(self):
        before=self.git('rev-parse','main')
        self.git('checkout','-q','lane/fixture')
        self.write('knowledge/card.md','unauthorized\n'); self.commit('outside')
        self.git('checkout','-q','main')
        self.assertIn('IMPORT FAIL lane/fixture',self.exchange())
        self.assertEqual(self.git('rev-parse','main'),before)

    def test_owner_contract_edit_refused(self):
        before=self.git('rev-parse','main')
        self.git('checkout','-q','lane/fixture')
        self.write('raw/workspaces/fixture/LANE.md','changed'); self.commit('contract')
        self.git('checkout','-q','main')
        self.assertIn('IMPORT FAIL lane/fixture',self.exchange())
        self.assertEqual(self.git('rev-parse','main'),before)
