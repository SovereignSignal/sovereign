import json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import test_contribution_intake as fixtures
import unittest
from sovereign_intake import collector,client
from sovereign_intake.common import IntakeError,git
from sovereign_intake.evidence import projection
from unittest.mock import patch

class Evidence(unittest.TestCase):
 tearDown=fixtures.Intake.tearDown
 run_client=fixtures.Intake.run_client
 import_items=fixtures.Intake.import_items
 files=fixtures.Intake.files
 def setUp(self):
  fixtures.Intake.setUp(self);self.text='A rule with $25 budget, 2026 revision abc1234, and an exception.\n'+'Unicode evidence λ🦀 with a reason.\n'*700
  (self.source/'evidence.md').write_text(self.text)
  self.config.update(evidence_root=str(self.source),evidence_selectors=[dict(id='proof',path='evidence.md',title='Evidence',kind='markdown')])
  self.hubcfg['sources'].update({f'proof-p{i:02d}':{'path':'evidence.md','exporter_version':'2'} for i in range(1,33)})
 def parts(self):return [i for i in collector.assess(self.config)['items'] if i['exporter_version']=='2']
 def test_exact_unicode_roundtrip(self):
  parts=self.parts();t=''.join(i['body'].split('<!-- retained-source-begin -->\n',1)[1].rsplit('\n<!-- retained-source-end -->',1)[0] for i in parts)
  self.assertEqual(t,self.text);self.assertTrue(all(len(i['body'].encode())<=12288 for i in parts));self.run_client();self.import_items()
 def test_v2_requires_versioned_hub_approval(self):
  self.hubcfg['sources'].update({f'proof-p{i:02d}':'evidence.md' for i in range(1,33)})
  self.run_client()
  with self.assertRaises(IntakeError):self.import_items()
 def test_redaction_preserves_rule(self):
  (self.source/'evidence.md').write_text('Budget $25; example '+ 'ghp_'+'A'*32+'\nNever remove the owner approval.\n')
  t=self.parts()[0]['body'];self.assertNotIn('ghp_',t);self.assertIn('$25',t);self.assertIn('Never remove the owner approval.',t);self.assertIn('redacted',t)
 def test_missing_symlink_and_oversize_fail(self):
  f=self.source/'evidence.md';f.unlink();self.assertFalse(collector.assess(self.config)['ok']);f.symlink_to(self.source/'method.md');self.assertFalse(collector.assess(self.config)['ok']);f.unlink();f.write_text('x'*256001);self.assertFalse(collector.assess(self.config)['ok'])
 def test_unknown_document_visible(self):
  self.config['evidence_watch_roots']=['docs'];(self.source/'docs').mkdir();(self.source/'docs/new.md').write_text('New source')
  x=collector.assess(self.config);self.assertFalse(x['ok']);self.assertEqual(x['observations'][-1]['reason'],'new_sources_require_discovery')
 def test_series_stable_blocks_and_schema(self):
  rows=[dict(timestamp=f'2026-08-{i%28+1:02d}T00:00:00Z',status='blocked',error='boundary failed',plan={'private':'not retained'}) for i in range(21)]
  a=projection(('\n'.join(map(json.dumps,rows))+'\n').encode(),'maintenance-history');rows.append(rows[-1]);b=projection(('\n'.join(map(json.dumps,rows))+'\n').encode(),'maintenance-history')
  self.assertEqual(a[0],b[0]);self.assertNotIn('private',a[0][2]);self.assertIn('boundary failed',a[0][2])
  with self.assertRaises(IntakeError):projection(b'{"unexpected":1}\n','maintenance-history')
 def test_health_projection_no_details(self):
  raw=json.dumps({'timestamp':'2026-09-17','sent':True,'checks':[{'name':'gateway','status':'ok','detail':'private diagnostic'}]}).encode()
  result=projection(raw,'health-history')[0][2];self.assertNotIn('private diagnostic',result);self.assertIn('gateway',result)
 def test_v2_retry_and_replay(self):
  real=client.git
  def fail(repo,*a,**kw):
   if a[0]=='push':raise IntakeError('push_failed')
   return real(repo,*a,**kw)
  with patch.object(client,'git',fail),self.assertRaises(IntakeError):self.run_client()
  head=git(self.config['spool'],'rev-parse','HEAD').stdout;self.run_client();self.assertEqual(head,git(self.config['spool'],'rev-parse','HEAD').stdout);self.import_items();before={p.name:p.read_bytes() for p in self.lane.glob('*.md')};self.run_client();self.import_items();self.assertEqual(before,{p.name:p.read_bytes() for p in self.lane.glob('*.md')})
