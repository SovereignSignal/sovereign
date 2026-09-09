import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('gate_check', HERE/'gate_check.py'); gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)

class GateCheckTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.root=self.base/'archive';self.root.mkdir();self.lane='curator';self.proposals=self.root/'raw/workspaces/curator/proposals';self.proposals.mkdir(parents=True);(self.root/'knowledge').mkdir();self.slug='example-card';self.card(self.proposals/(self.slug+'.md'))
  self.lock_patch=patch.object(gate,'lock_path',return_value=self.base/'gate.lock');self.lock_patch.start()
 def tearDown(self):self.lock_patch.stop();self.tmp.cleanup()
 def card(self,path,kind='entity',body='Reviewed content',source='owner'):
  path.parent.mkdir(parents=True,exist_ok=True);path.write_text('---\ntype: '+kind+'\nsource: '+source+'\ncreated: 2026-01-01\ntitle: Example\n---\n\n'+body+'\n');return path
 def check(self):return gate.check(self.root,self.lane,self.slug)
 def existing(self,folder='entities',kind='entity'):return self.card(self.root/'knowledge'/folder/(self.slug+'.md'),kind,'Existing detail')
 def fake(self,script):
  p=self.base/'command';p.write_text('#!/bin/sh\n'+script+'\n');p.chmod(0o700);return p
 def execute(self,command,verb='approve',fingerprint=None):return gate.execute(self.root,self.lane,self.slug,verb,fingerprint or self.check()['fingerprint'],command)
 def test_new_card_ready(self):self.assertEqual(self.check()['state'],'ready')
 def test_type_conflict_preserves_both_cards(self):
  a=self.existing();b=self.existing('concepts','concept');before=(a.read_bytes(),b.read_bytes());c=self.check();self.assertEqual(c['state'],'type_conflict');self.assertEqual(len(c['existing']),2);self.assertEqual((a.read_bytes(),b.read_bytes()),before)
 def test_same_folder_needs_declared_update(self):
  self.existing();self.assertEqual(self.check()['state'],'update_conflict');(self.proposals/'.meta.json').write_text(json.dumps({self.slug:{'update_of':self.slug}}));self.assertEqual(self.check()['state'],'ready')
 def test_different_update_target_does_not_authorize_overwrite(self):
  self.existing();(self.proposals/'.meta.json').write_text(json.dumps({self.slug:{'update_of':'other'}}));self.assertEqual(self.check()['state'],'update_conflict')
 def test_changed_card_cannot_execute(self):
  token=self.check()['fingerprint'];self.card(self.proposals/(self.slug+'.md'),body='Edited after review');self.assertEqual(self.execute(self.base/'never-run',fingerprint=token)['state'],'changed')
 def test_changed_existing_card_invalidates_review(self):
  self.existing();token=self.check()['fingerprint'];self.existing('concepts','concept');self.assertEqual(self.execute(self.base/'never-run',fingerprint=token)['state'],'changed')
 def test_missing_and_invalid(self):
  self.card(self.proposals/(self.slug+'.md'),source='');self.assertEqual(self.check()['state'],'invalid');(self.proposals/(self.slug+'.md')).unlink();self.assertEqual(self.check()['state'],'missing')
 def test_conflict_never_executes(self):
  self.existing('concepts','concept');self.assertEqual(self.execute(self.base/'never-run')['state'],'type_conflict')
 def test_symlink_is_refused(self):
  p=self.proposals/(self.slug+'.md');p.unlink();target=self.base/'outside';target.write_text('secret');p.symlink_to(target)
  with self.assertRaises(ValueError):self.check()
 def test_reject_missing_fingerprint(self):self.assertEqual(gate.execute(self.root,self.lane,self.slug,'approve','',self.base/'never-run')['state'],'changed')
 def test_nonzero_command_is_failure(self):self.assertEqual(self.execute(self.fake('echo REFUSED; exit 1'))['state'],'failed')
 def test_exit_zero_without_state_change_is_not_success(self):self.assertEqual(self.execute(self.fake('echo success; exit 0'))['state'],'failed')
 def test_missing_executable_is_unavailable(self):self.assertEqual(self.execute(self.base/'missing')['state'],'unavailable')
 def test_timeout_is_uncertain(self):
  with patch.object(gate,'run_gate',side_effect=subprocess.TimeoutExpired('gate',60)):
   self.assertEqual(self.execute(self.base/'unused')['state'],'uncertain')
 def test_audit_proposal(self):
  p=self.proposals/(self.slug+'.md');(self.proposals/'audit').mkdir();p.rename(self.proposals/'audit'/p.name);self.assertIn('/audit/',self.check()['proposal']['path'])
 def test_metadata_changes_invalidate_review(self):
  token=self.check()['fingerprint'];(self.proposals/'.meta.json').write_text(json.dumps({self.slug:{'screen_flagged':True,'screen_reason':'Needs source review'}}))
  self.assertEqual(self.execute(self.base/'never-run',fingerprint=token)['state'],'changed');self.assertIn('Needs source review',self.check()['review_notes'][0])
 def test_delimiter_in_title_is_not_frontmatter_end(self):
  p=self.proposals/(self.slug+'.md');p.write_text(p.read_text().replace('title: Example','title: Example---title'));self.assertEqual(self.check()['proposal']['body'],'Reviewed content')
 def test_unexpected_disappearance_is_uncertain(self):
  self.assertEqual(self.execute(self.fake('rm "$SOVS_VAULT/raw/workspaces/curator/proposals/example-card.md"; exit 1'))['state'],'uncertain')
 def test_second_decision_cannot_run_while_lock_is_held(self):
  with (self.base/'gate.lock').open('a') as held:
   gate.fcntl.flock(held,gate.fcntl.LOCK_EX|gate.fcntl.LOCK_NB)
   self.assertTrue(gate.operation_busy(self.root));self.assertEqual(self.execute(self.base/'never-run')['state'],'busy')
  self.assertFalse(gate.operation_busy(self.root))
 def test_command_inherits_lock(self):
  command=self.fake('test -e /dev/fd/"$LOCK_FD"')
  with (self.base/'gate.lock').open('a') as held:
   result=gate.run_gate([str(command)],dict(os.environ,LOCK_FD=str(held.fileno())),held.fileno());self.assertEqual(result.returncode,0)
 def test_surviving_command_keeps_lock_after_parent_closes_it(self):
  held=(self.base/'gate.lock').open('a');gate.fcntl.flock(held,gate.fcntl.LOCK_EX|gate.fcntl.LOCK_NB)
  child=subprocess.Popen(['/bin/sleep','5'],pass_fds=(held.fileno(),))
  try:
   held.close();self.assertTrue(gate.operation_busy(self.root))
  finally:child.terminate();child.wait()
  self.assertFalse(gate.operation_busy(self.root))
 def test_timeout_terminates_the_command_group(self):
  original=gate.subprocess.Popen
  def short_timeout(*args,**kwargs):
   process=original(*args,**kwargs);communicate=process.communicate
   process.communicate=lambda timeout=None:communicate(timeout=.05 if timeout==60 else timeout)
   return process
  with (self.base/'gate.lock').open('a') as held, patch.object(gate.subprocess,'Popen',side_effect=short_timeout):
   with self.assertRaises(subprocess.TimeoutExpired):gate.run_gate(['/bin/sh','-c','sleep 5'],dict(os.environ),held.fileno())
 def setup_real_gate(self):
  repo=HERE.parents[1];command=self.base/'real-gate';command.write_text('#!/bin/sh\ncase "$2" in\napprove) exec /bin/bash "'+str(repo/'bin/curator-approve.sh')+'" "$3" "$4";;\nreject) exec /bin/bash "'+str(repo/'bin/curator-reject.sh')+'" "$3" "$4";;\nesac\n');command.chmod(0o700)
  def git(*args):subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True)
  git('init','-q');git('config','user.name','Gate QA');git('config','user.email','gate-qa@example.invalid');git('add','.');git('commit','-qm','Initial test archive')
  bare=self.base/'origin.git';subprocess.run(['git','init','--bare','-q',str(bare)],check=True);git('remote','add','origin',str(bare));git('push','-qu','origin','HEAD');return command
 def test_real_approval_and_sync(self):self.assertEqual(self.execute(self.setup_real_gate())['state'],'approved');self.assertFalse((self.proposals/(self.slug+'.md')).exists())
 def test_real_rejection(self):self.assertEqual(self.execute(self.setup_real_gate(),'reject')['state'],'rejected')
 def test_repeat_rejection_verifies_stamped_destination(self):
  old=self.card(self.root/'raw/workspaces/curator/rejected'/(self.slug+'.md'),body='Earlier rejection')
  command=self.setup_real_gate()
  self.assertEqual(self.execute(command,'reject')['state'],'rejected')
  self.assertIn('Earlier rejection',old.read_text())
  self.assertEqual(len(list(old.parent.glob(self.slug+'--rejected-*.md'))),1)
 def test_repeat_rejection_with_push_failure_reports_sync_pending(self):
  self.card(self.root/'raw/workspaces/curator/rejected'/(self.slug+'.md'),body='Earlier rejection')
  command=self.setup_real_gate();hook=self.base/'origin.git/hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
  self.assertEqual(self.execute(command,'reject')['state'],'sync_pending')
 def test_old_matching_rejection_is_not_proof_of_success(self):
  self.card(self.root/'raw/workspaces/curator/rejected'/(self.slug+'.md'))
  self.card(self.root/'raw/workspaces/curator/rejected'/(self.slug+'--rejected-20260101-000000.md'))
  command=self.fake('rm "$SOVS_VAULT/raw/workspaces/curator/proposals/example-card.md"; exit 0')
  self.assertEqual(self.execute(command,'reject')['state'],'uncertain')
 def test_new_wrong_content_rejection_is_not_success(self):
  command=self.fake('mkdir -p "$SOVS_VAULT/raw/workspaces/curator/rejected"; echo wrong > "$SOVS_VAULT/raw/workspaces/curator/rejected/example-card--rejected-20260101-000000.md"; rm "$SOVS_VAULT/raw/workspaces/curator/proposals/example-card.md"')
  self.assertEqual(self.execute(command,'reject')['state'],'uncertain')
 def test_new_symlink_rejection_is_not_success(self):
  outside=self.card(self.base/'outside.md')
  command=self.fake('mkdir -p "$SOVS_VAULT/raw/workspaces/curator/rejected"; ln -s "'+str(outside)+'" "$SOVS_VAULT/raw/workspaces/curator/rejected/example-card.md"; rm "$SOVS_VAULT/raw/workspaces/curator/proposals/example-card.md"')
  self.assertEqual(self.execute(command,'reject')['state'],'uncertain')
 def test_push_failure_is_saved_but_not_synced(self):
  command=self.setup_real_gate();hook=self.base/'origin.git/hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
  self.assertEqual(self.execute(command)['state'],'sync_pending')

 def resolution(self):
  old=self.existing('concepts','concept')
  (self.proposals/'.meta.json').write_text(json.dumps({self.slug:{'update_of':self.slug,'screen_flagged':True,'screen_reason':'Check source'}}))
  return old,self.proposals/(self.slug+'.md')
 def test_resolve_preserves_type_and_originals_through_real_gate(self):
  old,prop=self.resolution(); originals=(old.read_bytes(),prop.read_bytes());command=self.setup_real_gate()
  result=self.execute(command,'resolve');self.assertEqual(result['state'],'approved')
  self.assertFalse(prop.exists());self.assertEqual(gate.read_card(old,self.root)['type'],'concept');self.assertEqual(gate.read_card(old,self.root)['body'],'Reviewed content')
  record=json.loads(gate.resolution_record(self.root,self.lane,self.slug).read_text());self.assertEqual(record['status'],'completed');backup=Path(record['originals'])
  self.assertEqual((backup/'existing.md').read_bytes(),originals[0]);self.assertEqual((backup/'proposal.md').read_bytes(),originals[1])
  self.assertTrue(json.loads((self.proposals/'.meta.json').read_text())[self.slug]['screen_flagged'])
 def test_resolve_failure_restores_original_without_touching_trusted_card(self):
  old,prop=self.resolution();originals=(old.read_bytes(),prop.read_bytes())
  result=self.execute(self.fake('echo REFUSED; exit 1'),'resolve');self.assertEqual(result['state'],'failed');self.assertEqual((old.read_bytes(),prop.read_bytes()),originals);self.assertEqual(self.check()['state'],'type_conflict')
 def test_resolve_timeout_blocks_retries_and_preserves_backups(self):
  old,prop=self.resolution()
  with patch.object(gate,'run_gate',side_effect=subprocess.TimeoutExpired('gate',60)):
   self.assertEqual(self.execute(self.base/'unused','resolve')['state'],'resolution_pending')
  self.assertEqual(self.check()['state'],'resolution_pending')
  self.assertEqual(gate.execute(self.root,self.lane,self.slug,'approve','a'*64,self.base/'unused')['state'],'changed')
  record=json.loads(gate.resolution_record(self.root,self.lane,self.slug).read_text());self.assertTrue((Path(record['originals'])/'proposal.md').exists());self.assertIn('Existing detail',old.read_text())
 def test_resolve_changed_proposal_is_refused(self):
  old,prop=self.resolution();token=self.check()['fingerprint'];prop.write_text(prop.read_text()+'Changed')
  self.assertEqual(self.execute(self.base/'unused','resolve',token)['state'],'changed');self.assertIn('Changed',prop.read_text())
 def test_resolve_multiple_existing_cards_is_refused(self):
  old,prop=self.resolution();self.existing();self.assertFalse(gate.can_resolve(self.check()));self.assertEqual(self.execute(self.base/'unused','resolve')['state'],'type_conflict')
 def test_resolve_requires_declared_same_card_update(self):
  self.existing('concepts','concept');self.assertEqual(self.execute(self.base/'unused','resolve')['state'],'type_conflict')
 def test_resolve_symlink_existing_refused(self):
  old,prop=self.resolution();old.unlink();old.symlink_to(self.card(self.base/'outside','concept'))
  with self.assertRaises(ValueError):self.check()
 def test_resolve_type_folder_mismatch_refused(self):
  self.resolution();self.existing('concepts','entity');self.assertFalse(gate.can_resolve(self.check()))
 def test_resolve_keeps_body_delimiters_and_title_delimiters(self):
  old,prop=self.resolution();prop.write_text(prop.read_text().replace('title: Example','title: An---example')+'\n---\nBody delimiter')
  original=gate.read_card(prop,self.root);self.assertEqual(self.execute(self.setup_real_gate(),'resolve')['state'],'approved');landed=gate.read_card(old,self.root);self.assertEqual(landed['body'],original['body']);self.assertEqual(landed['title'],original['title'])
 def test_resolve_duplicate_type_labels_refused(self):
  old,prop=self.resolution();prop.write_text(prop.read_text().replace('type: entity','type: concept\ntype: entity'))
  self.assertEqual(self.execute(self.base/'unused','resolve')['state'],'invalid')
 def test_resolve_push_failure_retains_applied_result(self):
  old,prop=self.resolution();command=self.setup_real_gate();hook=self.base/'origin.git/hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
  self.assertEqual(self.execute(command,'resolve')['state'],'sync_pending');self.assertFalse(prop.exists());self.assertEqual(self.check()['state'],'missing')
 def test_resolve_rechecks_metadata_before_approval(self):
  old,prop=self.resolution();original=gate.atomic_write;calls=[]
  def change(path,data):
   original(path,data)
   if path==prop and b'type: concept' in data:
    (self.proposals/'.meta.json').write_text(json.dumps({self.slug:{'update_of':self.slug,'screen_flagged':True,'screen_reason':'Changed after preview'}}))
  with patch.object(gate,'atomic_write',side_effect=change),patch.object(gate,'run_gate',side_effect=lambda *a:calls.append(a)):
   result=self.execute(self.base/'unused','resolve')
  self.assertEqual(result['state'],'changed');self.assertFalse(calls);self.assertEqual(gate.read_card(prop,self.root)['type'],'entity')
 def test_resolve_unsupported_verb_does_not_execute(self):
  self.assertEqual(self.execute(self.base/'unused','retire')['state'],'invalid')

if __name__=='__main__':unittest.main()
