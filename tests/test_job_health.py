"""A blocked backup becomes watch-only only after an evidence-based recheck."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from sovereign_hub import job_health, job_action, instance, manifest


class Health(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.vault = self.base / 'vault'; self.vault.mkdir()
        self.state = self.base / 'state'; (self.state / 'hub').mkdir(parents=True)
        self.document = self.vault / 'document.md'
        self.document.write_text('A document titled Desk-' + 'a'*32)
        self.output = self.state / 'hub/autocommit.last-output'
        self.output.write_text('=== FILENAME HITS ===\n(none)\n=== CONTENT HITS ===\n--- document.md\n12:sk-a…aa [redacted]\n=== SUMMARY: files with content hits: 1 ===\nvault-autocommit: SECRET SCAN FAILED over 30 staged files — index reset, NOTHING committed.\n')
        self.row = {'last_run': 1700000000, 'last_exit': 1}
        self.spec = dict(manifest.JOBS['autocommit'])
        self.scheduler = patch.object(job_health, 'schedule_loaded', return_value=True); self.scheduler.start(); self.addCleanup(self.scheduler.stop)

    def describe(self, now=1700000100):
        return job_health.describe('autocommit', self.row, self.spec, self.state, ROOT, self.vault, now)

    def test_current_scanner_clears_original_false_positive_without_saving(self):
        before = self.document.read_bytes()
        result = self.describe()
        self.assertEqual(result['state'], 'awaiting_verification')
        self.assertIn('successful backup is still unverified', result['why'])
        self.assertEqual(self.document.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.state.rglob('*')), ['autocommit.last-output', 'hub'])

    def test_real_secret_stays_actionable(self):
        self.document.write_text('key: sk-' + 'b'*32)
        self.assertEqual(self.describe()['state'], 'needs_attention')

    def test_unreadable_flagged_file_stays_actionable(self):
        self.document.write_text('key: sk-' + 'b'*32)
        self.document.chmod(0)
        try:
            self.assertEqual(self.describe()['state'], 'needs_attention')
        finally:
            self.document.chmod(0o600)

    def test_inaccessible_parent_is_not_a_confirmed_deletion(self):
        folder = self.vault/'private'; folder.mkdir()
        self.document.rename(folder/'document.md')
        (folder/'document.md').write_text('key: sk-' + 'b'*32)
        self.output.write_text(self.output.read_text().replace('--- document.md', '--- private/document.md'))
        folder.chmod(0)
        try:
            self.assertEqual(self.describe()['state'], 'needs_attention')
        finally:
            folder.chmod(0o700)

    def test_missed_followup_returns_to_attention(self):
        result = self.describe(now=1700000000+2*86400)
        self.assertEqual(result['state'], 'needs_attention')
        self.assertIn('overdue', result['summary'])

    def test_new_failure_is_not_hidden_by_previous_recheck(self):
        self.assertEqual(self.describe()['state'], 'awaiting_verification')
        self.output.write_text('vault-autocommit: PUSH FAILED to backup')
        self.assertEqual(self.describe()['state'], 'needs_attention')
        self.row['last_exit'] = 0
        self.assertEqual(self.describe()['state'], 'healthy')

    def test_missing_corrupt_or_incomplete_output_stays_actionable(self):
        for value in ('', 'SECRET SCAN FAILED', self.output.read_text().replace('hits: 1', 'hits: 2')):
            self.output.write_text(value)
            self.assertEqual(self.describe()['state'], 'needs_attention')

    def test_paths_outside_vault_and_custom_jobs_cannot_suppress_failure(self):
        self.output.write_text(self.output.read_text().replace('--- document.md', '--- ../outside.md'))
        self.assertEqual(self.describe()['state'], 'needs_attention')
        self.spec['program'] = '/custom/program'
        self.assertNotIn('retry_supported', self.describe())

    def test_unavailable_scheduler_keeps_cleared_blocker_actionable(self):
        with patch.object(job_health, 'schedule_loaded', return_value=False):
            self.assertEqual(self.describe()['state'], 'needs_attention')
            self.assertIn('schedule', self.describe()['summary'])

    def test_scheduler_calendar_is_after_failure_not_sliding_with_refresh(self):
        first = self.describe(); later = self.describe(now=1700003600)
        self.assertEqual(first['verification_deadline'], later['verification_deadline'])


class Retry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve(); self.state = self.home/'state'; self.vault=self.home/'vault'; self.vault.mkdir()
        instance.write(self.state, {'vault':str(self.vault), 'lane':'qa', 'model':'qa', 'endpoint':'http://localhost:1', 'remotes':['archive']})
        self.plist=self.home/'Library/LaunchAgents/com.sovereign.hub.autocommit.plist'; self.plist.parent.mkdir(parents=True)
        self.plist.write_bytes(plistlib.dumps(manifest.render('autocommit',manifest.JOBS['autocommit'],ROOT,sys.executable,self.state,self.home)))
        self.homepatch=patch.dict(os.environ,HOME=str(self.home));self.homepatch.start();self.addCleanup(self.homepatch.stop)
        self.calls=[]
        self.real_run=subprocess.run
        subprocess.run(['git','init','-q',str(self.vault)],check=True)
        subprocess.run(['git','-C',str(self.vault),'remote','add','archive','https://example.invalid/archive.git'],check=True)
        item=plistlib.loads(self.plist.read_bytes())
        self.loaded='gui/%d/com.sovereign.hub.autocommit = {\n'%os.getuid()
        self.loaded+='\tpath = %s\n\tprogram = %s\n'%(self.plist,item['ProgramArguments'][0])
        self.loaded+='\targuments = {\n'+''.join('\t\t%s\n'%a for a in item['ProgramArguments'])+'\t}\n'
        self.loaded+='\tenvironment = {\n'+''.join('\t\t%s => %s\n'%(k,v) for k,v in item['EnvironmentVariables'].items())+'\t}\n'
        self.loaded+='\tevent triggers = {\n\t\tcalendar => {\n\t\t\tstream = com.apple.launchd.calendarinterval\n\t\t\tdescriptor = {\n\t\t\t\t"Minute" => 30\n\t\t\t\t"Hour" => 4\n\t\t\t}\n\t\t}\n\t}\n}\n'

    def ctl(self, args, **kwargs):
        if args[0] != '/bin/launchctl':
            return self.real_run(args,**kwargs)
        self.calls.append(args)
        return subprocess.CompletedProcess(args,0,self.loaded if args[1]=='print' else '', '')

    def retry(self, **kwargs):
        return job_action.retry(str(self.vault),state=self.state,template=ROOT,**kwargs)

    def test_preview_does_not_start_and_confirmed_apply_uses_non_interrupting_scheduler(self):
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            plan=self.retry()
            self.assertEqual([c[1] for c in self.calls],['print'])
            result=self.retry(token=plan['token'],apply=True)
        self.assertEqual(result['state'],'requested')
        self.assertEqual(self.calls[-1][1],'kickstart')
        self.assertNotIn('-k',self.calls[-1])
        self.assertIn('success is not yet verified',result['verification'])

    def test_apply_without_preview_or_changed_receipt_is_refused(self):
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            with self.assertRaises(ValueError):self.retry(apply=True)
            plan=self.retry()
            (self.state/'hub').mkdir();(self.state/'hub/autocommit.last-run').write_text('1700000000')
            with self.assertRaises(ValueError):self.retry(token=plan['token'],apply=True)
        self.assertNotIn('kickstart',[c[1] for c in self.calls])

    def test_running_backup_is_not_interrupted(self):
        self.loaded+='\tpid = 42\n'
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            with self.assertRaisesRegex(ValueError,'already running'):self.retry()

    def test_actual_loaded_identity_and_calendar_must_match(self):
        original=self.loaded
        for before,after in ((str(ROOT/'bin/sov-hub'),str(self.home/'old/bin/sov-hub')),
                             ('SOV_STATE_DIR => '+str(self.state),'SOV_STATE_DIR => '+str(self.home/'other')),
                             ('"Hour" => 4','"Hour" => 5'),
                             ('\tprogram = '+sys.executable,'\tprogram = /usr/bin/false')):
            self.loaded=original.replace(before,after)
            with self.subTest(change=before), patch.object(job_action.subprocess,'run',side_effect=self.ctl):
                with self.assertRaises(ValueError):self.retry()
                self.assertFalse(job_health.schedule_loaded('autocommit',self.state,ROOT))
        self.assertNotIn('kickstart',[c[1] for c in self.calls])

    def test_loaded_schedule_changed_after_preview_cannot_run(self):
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            plan=self.retry()
            self.loaded=self.loaded.replace('"Hour" => 4','"Hour" => 5')
            with self.assertRaises(ValueError):self.retry(token=plan['token'],apply=True)
        self.assertNotIn('kickstart',[c[1] for c in self.calls])

    def test_changed_push_url_rejects_previous_confirmation(self):
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            plan=self.retry()
            self.assertIn('archive (example.invalid)',plan['summary'])
            self.real_run(['git','-C',str(self.vault),'remote','set-url','--push','archive','https://other.invalid/repo.git'],check=True)
            with self.assertRaisesRegex(ValueError,'destinations'):self.retry(token=plan['token'],apply=True)
        self.assertNotIn('kickstart',[c[1] for c in self.calls])

    def test_all_push_urls_and_rewrite_rules_are_bound_without_exposing_credentials(self):
        self.real_run(['git','-C',str(self.vault),'remote','set-url','--add','--push','archive','https://user:password@example.invalid/a.git'],check=True)
        self.real_run(['git','-C',str(self.vault),'remote','set-url','--add','--push','archive','alias:repo.git'],check=True)
        self.real_run(['git','-C',str(self.vault),'config','url.https://backup.invalid/.insteadOf','alias:'],check=True)
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            plan=self.retry()
            self.assertIn('backup.invalid',plan['summary'])
            self.assertNotIn('password',json.dumps(plan))
            self.real_run(['git','-C',str(self.vault),'config','url.https://changed.invalid/.insteadOf','alias:'],check=True)
            self.real_run(['git','-C',str(self.vault),'config','--unset','url.https://backup.invalid/.insteadOf'],check=True)
            with self.assertRaisesRegex(ValueError,'destinations'):self.retry(token=plan['token'],apply=True)
        self.assertNotIn('kickstart',[c[1] for c in self.calls])

    def test_push_instead_of_rewrite_changes_require_a_new_preview(self):
        self.real_run(['git','-C',str(self.vault),'remote','set-url','archive','alias:repo.git'],check=True)
        self.real_run(['git','-C',str(self.vault),'config','url.https://backup.invalid/.pushInsteadOf','alias:'],check=True)
        with patch.object(job_action.subprocess,'run',side_effect=self.ctl):
            plan=self.retry()
            self.assertIn('backup.invalid',plan['summary'])
            self.real_run(['git','-C',str(self.vault),'config','url.https://changed.invalid/.pushInsteadOf','alias:'],check=True)
            self.real_run(['git','-C',str(self.vault),'config','--unset','url.https://backup.invalid/.pushInsteadOf'],check=True)
            with self.assertRaisesRegex(ValueError,'destinations'):self.retry(token=plan['token'],apply=True)
        self.assertNotIn('kickstart',[c[1] for c in self.calls])

    def test_wrong_archive_and_installed_state_are_rejected(self):
        with self.assertRaises(ValueError):job_action.retry(str(self.home/'other'),state=self.state,template=ROOT)
        value=plistlib.loads(self.plist.read_bytes());value['EnvironmentVariables']['SOV_STATE_DIR']=str(self.home/'other');self.plist.write_bytes(plistlib.dumps(value))
        with self.assertRaisesRegex(ValueError,'different hub state'):self.retry()

    def test_changed_hub_cannot_reuse_an_earlier_preview(self):
        (self.home/'.brain-root').write_text(str(self.vault))
        (self.home/'.brain-hub').write_text('hub:/remote/archive')
        with patch.object(job_action.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps({'state':'preview','token':'inner'}),'')):
            preview=job_action.route(str(self.vault))
        (self.home/'.brain-hub').write_text('other:/remote/archive')
        with patch.object(job_action.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'hub changed'):
                job_action.route(str(self.vault),preview['token'],True)
            run.assert_not_called()

    def test_client_routes_only_to_configured_archive(self):
        (self.home/'.brain-root').write_text(str(self.vault))
        (self.home/'.brain-hub').write_text('hub:/remote/archive with spaces')
        with patch.object(job_action.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps({'state':'preview'}),'')) as run:
            result=job_action.route(str(self.vault))
            self.assertEqual(result['hub'],'hub');self.assertIn("'/remote/archive with spaces'",run.call_args[0][0][-1])
            with self.assertRaises(ValueError):job_action.route(str(self.home/'wrong'))


if __name__ == '__main__': unittest.main()
