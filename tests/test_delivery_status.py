import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import tests.test_lane_delivery as lanes
ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('status_delivery',str(ROOT/'bin/brain-status'))
spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class DeliveryStatus(unittest.TestCase):
    setUp = lanes.LaneDelivery.setUp
    git = lanes.LaneDelivery.git
    write = lanes.LaneDelivery.write
    commit = lanes.LaneDelivery.commit
    # Use the same real temporary git graph, including the owner contract.
    def status(self):
        home=self.p/'test-home';home.mkdir(exist_ok=True);(home/'.brain-keep').write_text('exchange')
        r=subprocess.run([sys.executable,'-',str(self.p)],input=m.HUB_SCRIPT,env=dict(os.environ,HOME=str(home)),text=True,capture_output=True,check=True)
        return json.loads(r.stdout)['backups']['lanes'][0]
    def test_push_is_waiting_until_source_commit_is_included(self):
        self.git('checkout','-q','lane/fixture');self.write('raw/workspaces/fixture/note.md','capture');head=self.commit('capture');self.git('checkout','-q','main')
        self.git('update-ref','refs/remotes/exchange/lane/fixture',head)
        self.assertEqual(self.status()['delivery'],'waiting')
        self.git('merge','--no-ff','-qm','accept','lane/fixture')
        result=self.status();self.assertEqual(result['delivery'],'accepted');self.assertEqual(result['source_head'],head);self.assertIn('observed_at',result)
    def test_absent_ref_is_unknown(self):self.assertEqual(self.status()['delivery'],'unknown')

if __name__=='__main__':unittest.main()
