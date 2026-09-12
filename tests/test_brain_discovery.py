import contextlib, importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_discovery
class Discovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='sovereign-discovery-');self.home=Path(self.tmp.name);self.state=self.home/'state';self.state.mkdir()
  self.env=patch.dict(os.environ,{'HOME':str(self.home),'SOV_STATE_DIR':str(self.state)},clear=False);self.env.start()
  self.old={k:os.environ.pop(k,None) for k in ('BRAIN_ROOT','BRAIN_CORE','BRAIN_HOST','BRAIN_STAGE')}
 def tearDown(self):
  for k,v in self.old.items():
   if v is not None:os.environ[k]=v
  self.env.stop();self.tmp.cleanup()
 def config(self,value): (self.state/'connectors.json').write_text(json.dumps(value))
 def test_offline_intro_has_no_writes_or_probes(self):
  before=list(self.home.rglob('*'))
  with patch('subprocess.run',side_effect=AssertionError('No probes')):value=brain_discovery.describe()
  self.assertEqual(before,list(self.home.rglob('*')));self.assertFalse(value['network']);self.assertFalse(value['writes']);self.assertIsNone(value['machine']['role'])
 def test_explicit_client_role_and_incomplete_migration(self):
  self.config({'machine':{'role':'client','mode':'contribute-only'}});(self.home/'.brain-root').write_text('/private/legacy-brain')
  v=brain_discovery.describe();self.assertEqual(v['machine']['client_mode'],'contribute-only');self.assertIsNone(v['rules']);self.assertTrue(v['warnings']);self.assertEqual(brain_discovery.bootstrap(),'');self.assertFalse(brain_discovery.read_enabled())
 def test_corrupt_configuration_fails_closed(self):
  (self.state/'connectors.json').write_text('{broken')
  self.assertFalse(brain_discovery.read_enabled())
  self.config({'machine':{'role':'hub','mode':'contribute-only'}});self.assertFalse(brain_discovery.read_enabled())
 def test_unconfigured_hooks_are_silent_without_a_receipt(self):
  for tool in ('claude-code','codex','cursor','hermes'):
   result=subprocess.run([sys.executable,str(ROOT/'connectors/harness'/tool/'session-start.py')],input='{}',capture_output=True,text=True,check=True)
   self.assertEqual(json.loads(result.stdout or '{}'),{},tool)
  self.assertFalse((self.home/'raw').exists())
 def test_contribute_only_hooks_ignore_old_private_cache(self):
  self.config({'machine':{'role':'client','mode':'contribute-only'}});(self.home/'.brain-root').write_text('/private/old-vault')
  cache=self.home/'.cache/sovereign/hermes-pack.json';cache.parent.mkdir(parents=True);cache.write_text(json.dumps({'ts':time.time(),'root':'/private/old-vault','pack':{'context':'OLD PRIVATE FIXTURE'}}))
  for tool in ('claude-code','codex','cursor','hermes'):
   result=subprocess.run([sys.executable,str(ROOT/'connectors/harness'/tool/'session-start.py')],input='{}',capture_output=True,text=True,check=True)
   self.assertNotIn('OLD PRIVATE',result.stdout);self.assertNotIn('Sovereign discovery',result.stdout);self.assertEqual(json.loads(result.stdout or "{}"),{})
 def test_status_stops_before_hub_or_brain_probes(self):
  self.config({'machine':{'role':'client','mode':'contribute-only'}});(self.home/'.brain-root').write_text('/private/old-vault')
  loader=importlib.machinery.SourceFileLoader('contribute_status',str(ROOT/'bin/brain-status'));m=importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name,loader));loader.exec_module(m)
  with patch.object(m,'fetch_hub',side_effect=AssertionError('No hub read')),patch.object(m,'frontmatter',side_effect=AssertionError('No brain read')),contextlib.redirect_stdout(io.StringIO()) as output:m.main()
  v=json.loads(output.getvalue());self.assertEqual(v['machine']['client_mode'],'contribute-only');self.assertIsNone(v['hub']['reachable'])
if __name__=='__main__':unittest.main()
