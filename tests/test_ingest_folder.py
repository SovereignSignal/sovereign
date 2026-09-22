import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile
ROOT=Path(__file__).resolve().parents[1]
def ingest(vault,src,*args,home=None):
 env=dict(os.environ,HOME=str(home or vault.parent),BRAIN_ROOT=str(vault))
 env.pop('BRAIN_LANE',None)
 return subprocess.run([sys.executable,str(ROOT/'bin/sov-ingest'),'folder',str(src),*args],env=env,capture_output=True,text=True)
def fixture(tmp):
 root=Path(tmp);vault=root/'vault';(vault/'knowledge').mkdir(parents=True);(vault/'raw/workspaces').mkdir(parents=True)
 src=root/'src';(src/'sub').mkdir(parents=True);return root,vault,src
def declare(vault,src,root):
 r=ingest(vault,src,'--apply',home=root);assert r.returncode==2,(r.returncode,r.stderr)
 lane=vault/'raw/workspaces'/src.name;lane.mkdir(parents=True,exist_ok=True)
 rule=[l for l in r.stdout.splitlines() if l.startswith('====') and 'LANE.md' in l][0]
 (lane/'LANE.md').write_text(r.stdout.split(rule+'\n')[1])
class IngestFolder(unittest.TestCase):
 def test_an_undeclared_lane_prints_its_declaration_and_refuses(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   (src/'notes.md').write_text('Material that must not land in a lane nobody has declared yet.\n')
   r=ingest(vault,src,'--apply',home=root)
   self.assertEqual(r.returncode,2,r.stdout+r.stderr)
   self.assertFalse((vault/'raw/workspaces/src').exists())
   self.assertIn('lane: src',r.stdout);self.assertIn('LANE.md',r.stdout);self.assertIn('refus',r.stdout.lower())
   # the owner saves what was printed; the same command now proceeds
   declare(vault,src,root)
   r=ingest(vault,src,'--apply',home=root);self.assertEqual(r.returncode,0,r.stderr)
   self.assertEqual(len([p for p in (vault/'raw/workspaces/src').glob('*.md') if p.name!='LANE.md']),1)
   self.assertNotIn('lane_created',r.stdout)
 def test_lands_supported_files_once_and_replays_to_zero(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   (src/'notes.md').write_text('A note about funding architecture, long enough to carry meaning.\n')
   (src/'sub/plain.txt').write_text('Plain text with enough body to be judged as real material.\n')
   (src/'tiny.txt').write_text('no\n')
   (src/'blob.bin').write_bytes(b'\x00\xff'*64)
   lane=vault/'raw/workspaces/src'
   declare(vault,src,root)
   r=ingest(vault,src,'--apply',home=root);self.assertEqual(r.returncode,0,r.stderr)
   self.assertEqual(sorted(p.name for p in lane.glob('*.md') if p.name!='LANE.md').__len__(),2)
   self.assertTrue((lane/'LANE.md').exists())
   again=ingest(vault,src,'--apply',home=root);self.assertEqual(again.returncode,0,again.stderr)
   self.assertEqual(len([p for p in lane.glob('*.md') if p.name!='LANE.md']),2)
   self.assertIn('already-captured',again.stdout)
   # the formats it cannot judge are named, never silently dropped
   self.assertIn('unsupported-extension:.bin',again.stdout)
   self.assertIn('too-small-to-judge',again.stdout)
 def test_a_credential_shaped_filename_stops_the_whole_run(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   (src/'notes.md').write_text('Ordinary material that would otherwise be captured happily.\n')
   (src/'api-credentials.txt').write_text('nothing actually secret in here\n')
   r=ingest(vault,src,'--apply',home=root)
   self.assertNotEqual(r.returncode,0)
   self.assertIn('api-credentials.txt',r.stderr)
   self.assertFalse((vault/'raw/workspaces/src').exists(),'a refused run must write nothing at all')
 def test_a_token_in_a_source_file_lands_redacted(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   token='gh'+'p_'+'A'*35
   (src/'leaky.md').write_text('A note carrying %s inside ordinary prose about grants.\n'%token)
   declare(vault,src,root)
   r=ingest(vault,src,'--apply','--json',home=root);self.assertEqual(r.returncode,0,r.stderr)
   cards=[p for p in (vault/'raw/workspaces/src').glob('*.md') if p.name!='LANE.md']
   self.assertEqual(len(cards),1)
   self.assertNotIn(token,cards[0].read_text())
   self.assertEqual(json.loads(r.stdout)['redactions_total'],1)
 def test_identical_bytes_under_two_paths_are_captured_once(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   body='The very same bytes, filed under two different names entirely.\n'
   (src/'first.md').write_text(body);(src/'sub/second.md').write_text(body)
   declare(vault,src,root)
   r=ingest(vault,src,'--apply',home=root);self.assertEqual(r.returncode,0,r.stderr)
   cards=[p for p in (vault/'raw/workspaces/src').glob('*.md') if p.name!='LANE.md']
   self.assertEqual(len(cards),1,'content dedup, not path dedup')
   self.assertIn('duplicate-within-folder',r.stdout)
 def test_content_the_curator_already_judged_elsewhere_is_skipped(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   import hashlib
   body='Material that already reached the archive through some other pipe entirely.\n'
   (src/'again.md').write_text(body)
   store=vault/'raw/workspaces/archivist';store.mkdir(parents=True)
   digest=hashlib.sha256(body.encode()).hexdigest()
   (store/'.content-hashes.json').write_text(json.dumps({'raw/tools/somewhere/already.md':digest}))
   r=ingest(vault,src,'--json',home=root);self.assertEqual(r.returncode,0,r.stderr)
   plan=json.loads(r.stdout)
   self.assertEqual(plan['would_land'],0)
   self.assertEqual(plan['skipped'].get('already-in-archive'),1)
   self.assertEqual(plan['dedup_store'],'read')
 def test_the_dry_plan_is_the_default_and_writes_nothing(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   (src/'notes.md').write_text('Material that must not be written without an explicit --apply.\n')
   r=ingest(vault,src,home=root);self.assertEqual(r.returncode,0,r.stderr)
   self.assertFalse((vault/'raw/workspaces/src').exists())
   self.assertIn('dry plan',r.stdout)
   self.assertIn('CLAUDE.md Part 2',r.stdout)
 def test_a_folder_inside_the_vault_is_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,vault,src=fixture(tmp)
   inside=vault/'workstreams/somewhere';inside.mkdir(parents=True)
   (inside/'note.md').write_text('Already inside the archive; ingesting would duplicate it.\n')
   r=ingest(vault,inside,'--apply',home=root)
   self.assertNotEqual(r.returncode,0);self.assertIn('inside the vault',r.stderr)
if __name__=='__main__':unittest.main()
