"""Explanations must follow the observed failure and clear when it resolves."""
import ast
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class Transparency(unittest.TestCase):
 def setUp(self):
  loader=importlib.machinery.SourceFileLoader('status_transparency',str(ROOT/'bin/sov-status'))
  self.m=importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name,loader));loader.exec_module(self.m)
 def complete(self,row):
  self.assertNotIn('legacy',row)
  for key in ('text','why','action','verify'):self.assertTrue(row.get(key),key)
 def test_host_recovery_and_unknown_are_distinct(self):
  h={'host':'worker','net':{'online':False,'via':'port 22 probe'}}
  row=self.m.fleet_needs({'hosts':[h]})[0];self.complete(row);self.assertIn('1 second',row['why'])
  for state in (True,None):
   h['net']['online']=state;self.assertEqual(self.m.fleet_needs({'hosts':[h]}),[])
 def test_tailscale_failure_never_claims_ssh_authentication(self):
  row=self.m.fleet_needs({'hosts':[{'host':'worker','net':{'online':False,'via':'tailscale'}}]})[0]
  self.assertIn('offline',row['why']);self.assertNotIn('re-check',row['why'])
 def test_acceptance_explains_old_missing_and_failed_reports_then_clears(self):
  for state,reason in [(None,None),('unknown',None),('unknown','No exchange remote is configured on the hub.')]:
   lane={'lane':'writer','delivery':state,'acceptance_reason':reason};rows=self.m.contribution_issues({'lanes':[lane]});self.complete(rows[0])
   if reason:self.assertEqual(rows[0]['why'],reason)
   self.assertEqual(lane['acceptance_issue'],rows[0])
  for state in ('accepted','waiting'):self.assertEqual(self.m.contribution_issues({'lanes':[{'lane':'writer','delivery':state}]}),[])
 def test_existing_needs_kinds_have_guidance_and_unknown_kinds_are_flagged(self):
  # Extract constant producer kinds so adding a text-only producer fails this contract.
  tree=ast.parse((ROOT/'bin/sov-status').read_text());kinds=set()
  for node in ast.walk(tree):
   if isinstance(node,ast.Dict):
    for key,value in zip(node.keys,node.values):
     if isinstance(key,ast.Constant) and key.value=='kind' and isinstance(value,ast.Constant) and isinstance(value.value,str):kinds.add(value.value)
  known={'configuration','client-intake','hub','gate','harness','mirror-missing','lane-refused','lane-timeout','lane-silent','runner-standing-down','runner-stalled','relay','xcode-license','job','not-connected'}
  for kind in kinds-{'local VM','host','hypervisor','contribution'}:
   self.assertIn(kind,known,'New needs-you kind needs guidance: '+kind)
   self.complete(self.m.explain_needs([{'kind':kind,'text':'Reported condition'}])[0])
  self.assertTrue(self.m.explain_needs([{'kind':'future','text':'missing guidance'}])[0]['legacy'])
 def test_explicit_cause_is_preserved(self):
  row={'kind':'job','text':'failed','why':'Exact cause','action':'Exact next step','verify':'Exact confirmation'}
  self.assertEqual(self.m.explain_needs([dict(row)]),[row])
 def test_gate_copy_has_one_decision_surface(self):
  self.assertNotIn('Approve or reject them on Telegram',(ROOT/'bin/sov-status').read_text())
  self.assertIn('Sovereign → Review',self.m.explain_needs([{'kind':'gate','text':'waiting'}])[0]['action'])
if __name__=='__main__':unittest.main()
