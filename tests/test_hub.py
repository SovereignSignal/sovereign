import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local
from sovereign_hub import core,recovery
from sovereign_intake.common import IntakeError,locked

class Model(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path.startswith('/redirect'):
            self.send_response(307);self.send_header('Location','http://127.0.0.1:'+str(self.server.server_port)+'/unexpected');self.end_headers();return
        if self.path=='/unexpected':self.server.redirect_followed=True
        raw=json.dumps({'data':[{'id':'fixture-local'}]}).encode();self.send_response(200);self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        judgment={'promote':True,'type':'concept','slug':'recovery-drill','title':'Recovery drill','confidence':'high','reason':'A reusable recovery method.','why':'Rebuilds must be demonstrated.','body':'Restore into a separate directory and compare trusted notes and decisions before enabling any jobs. Keep the original Hub stopped before switching authority. A backup without a tested restore is only a candidate recovery source.','injection':False,'flagged':False,'safe':True}
        raw=json.dumps({'choices':[{'message':{'content':json.dumps(judgment)}}]}).encode();self.send_response(200);self.end_headers();self.wfile.write(raw)

class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='sov-hub-test-',dir='/private/tmp');cls.base=Path(cls.tmp.name).resolve();cls.home=cls.base/'home';cls.home.mkdir()
        cls.env=patch.dict(os.environ,HOME=str(cls.home),SOV_PYTHON_RUNTIME=os.environ.get('SOV_PYTHON_RUNTIME',str(ROOT/'apps/console/build/Sovereign.app/Contents/Resources/runtime')));cls.env.start()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Model);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.archive=cls.base/'Archive';brain_local.create(cls.archive,ROOT)
        cls.destination=cls.base/'Hub';cls.plan=core.install_plan(cls.archive,cls.destination,'fixture-local',f'http://127.0.0.1:{cls.server.server_port}/v1/chat/completions')
        core.install(cls.plan,True);cls.config=core.load(cls.destination/'config.json')
        cls.keys=cls.base/'keys';cls.keys.mkdir();cls.key=cls.keys/'recovery.key';recovery.recovery_key(cls.key,True)
        cls.backups=cls.base/'backups';cls.backups.mkdir()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.env.stop();cls.tmp.cleanup()

    def test_01_install_preview_is_zero_write_and_protects_existing_lanes(self):
        new=self.base/'Other';brain_local.create(new,ROOT);dest=self.base/'AnotherHub'
        p=core.install_plan(new,dest,'fixture-local');core.install(p)
        self.assertFalse(dest.exists());self.assertFalse((new/'raw/workspaces/curator').exists())
        with self.assertRaises(ValueError):core.install(self.plan,True)
        self.assertFalse((self.home/'.brain-root').exists());self.assertFalse((self.home/'Library/LaunchAgents').exists())

    def test_02_locality_and_existing_client_are_guarded(self):
        for endpoint,model in [('https://api.example.invalid/v1/chat/completions','local'),('http://127.0.0.1:1/v1/chat/completions','large:cloud'),('http://other.local:11434/v1/chat/completions','local')]:
            with self.assertRaises(ValueError):core.inference_guard(endpoint,model)
        env=core.clean_environment(self.config)
        self.assertEqual(env['ARCHIVIST_AUTO_PROMOTE_MAX'],'0');self.assertEqual(env['CURATOR_SCREEN'],'on')
        self.assertTrue(core.doctor(self.config)['model_available'])

    def test_03_core_loop_and_restore_retain_decisions_context_and_runtime(self):
        lane=self.archive/'raw/workspaces/curator';proposal=lane/'proposals/recovery-drill.md';trusted=self.archive/'knowledge/concepts/recovery-drill.md'
        source=self.archive/'raw/tools/fixture';source.mkdir();(source/'method.md').write_text('---\ntype: capture\nsource: fixture\ncreated: 2026-01-01\n---\n# Recovery method\n'+('Practice restoring the archive to a separate directory. Check the retained decisions and trusted notes. Keep a separate encryption key and activate only one Hub. '*8))
        r=core.run(self.config,'nightly',True);self.assertEqual(r['exit'],0,Path(r['log']).read_text())
        self.assertTrue(proposal.exists());self.assertFalse(trusted.exists())
        self.assertEqual(core.run(self.config,'approve',True,'recovery-drill','Fixture owner approves the method')['exit'],0)
        self.assertTrue(trusted.exists());decisions=(lane/'decisions.log').read_bytes()
        self.assertEqual(core.run(self.config,'audit',True)['exit'],0)
        config=recovery.configure(self.config,self.backups,self.key,True)['config'];self.__class__.config=config
        capsule=self.backups/'roundtrip.sovbackup';r=recovery.snapshot(config,capsule,self.key,True);self.assertTrue(r['encrypted'])
        restored=self.base/'Restored';recovery.restore(capsule,restored,self.key)
        self.assertFalse(restored.exists());recovery.restore(capsule,restored,self.key,True)
        restored_config=core.load(restored/'hub/config.json')
        self.assertEqual((restored/'archive/knowledge/concepts/recovery-drill.md').read_bytes(),trusted.read_bytes())
        self.assertEqual((restored/'archive/raw/workspaces/curator/decisions.log').read_bytes(),decisions)
        self.assertIsNone(restored_config['recovery_key']);self.assertIsNone(restored_config['snapshot_folder'])
        self.assertFalse((restored/'hub/receipts/activation.json').exists())
        cp=subprocess.run([str(restored/'hub/bin/sov'),'hub','status','--config',str(restored/'hub/config.json')],env=dict(os.environ,PATH='/usr/bin:/bin'),capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stderr+cp.stdout)
        cp=subprocess.run([str(restored/'hub/python/bin/python3'),str(restored/'hub/engine/bin/sov-load'),'recovery-drill','--root',str(restored/'archive')],env=dict(os.environ,PATH='/usr/bin:/bin'),capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stderr);self.assertIn('Rebuilds must be demonstrated',cp.stdout)
        self.assertFalse((self.home/'.brain-root').exists())
        # Existing bytes never overwritten, even by a valid capsule.
        with self.assertRaises(ValueError):recovery.restore(capsule,restored,self.key,True)

    def test_04_wrong_key_and_tamper_leave_destination_absent(self):
        capsule=self.backups/'roundtrip.sovbackup';other=self.keys/'wrong';recovery.recovery_key(other,True)
        dest=self.base/'WrongKey'
        with self.assertRaises(subprocess.CalledProcessError):recovery.restore(capsule,dest,other,True)
        self.assertFalse(dest.exists())
        corrupt=self.backups/'corrupt.sovbackup';raw=bytearray(capsule.read_bytes());raw[-1]^=1;corrupt.write_bytes(raw)
        with self.assertRaises(subprocess.CalledProcessError):recovery.restore(corrupt,dest,self.key,True)
        self.assertFalse(dest.exists())

    def test_05_linked_data_and_inflight_job_refuse_snapshot(self):
        link=self.archive/'linked';link.symlink_to(self.key)
        try:
            with self.assertRaises((IntakeError,OSError)):recovery.snapshot(self.config,self.backups/'linked.sovbackup',self.key,True)
        finally:link.unlink()
        with locked(self.destination/'operation.lock'):
            with self.assertRaises(IntakeError):recovery.snapshot(self.config,self.backups/'busy.sovbackup',self.key,True)
        self.assertFalse((self.backups/'linked.sovbackup').exists())

    def test_06_encryption_key_cannot_live_in_archive(self):
        with self.assertRaises(ValueError):recovery.recovery_key(self.archive/'secret',True)
        self.assertFalse((self.archive/'secret').exists())
        with self.assertRaises(ValueError):recovery.configure(self.config,self.keys,self.key,True)
        # A key anywhere under the capsule folder travels with every capsule it opens.
        nested=self.backups/'keys';nested.mkdir();key=nested/'hub.key';recovery.recovery_key(key,True)
        with self.assertRaisesRegex(ValueError,'separately'):recovery.configure(self.config,self.backups,key)
        with self.assertRaisesRegex(ValueError,'separately'):recovery.snapshot(self.config,self.backups/'two.sovbackup',key)

    def test_06b_archive_guards_judge_the_folder_not_its_spelling(self):
        # Case and /System/Volumes/Data firmlinks name one folder many ways on APFS.
        inside=self.archive/'workstreams';found=[Path(v) for v in (str(inside).replace('/Archive/','/aRCHIVE/'),'/System/Volumes/Data'+str(inside)) if os.path.exists(v) and os.path.samefile(v,inside)]
        if not found:self.skipTest('this volume spells each folder one way')
        placed=inside/'placed.key';placed.write_bytes(os.urandom(32));placed.chmod(0o600)
        try:
            for spelled in found:
                with self.assertRaisesRegex(ValueError,'outside both'):recovery.configure(self.config,self.backups,spelled/'placed.key')
                with self.assertRaisesRegex(ValueError,'outside the archive'):recovery.snapshot(self.config,spelled/'inside.sovbackup',self.key)
                with self.assertRaisesRegex(ValueError,'outside the archive'):core.install_plan(self.archive,spelled/'Hub','fixture-local')
        finally:placed.unlink()

    def test_07_unsafe_tar_entries_refused_before_extraction(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('archive/linked',tarfile.SYMTYPE),('/absolute',tarfile.REGTYPE)]:
            buf=io.BytesIO()
            with tarfile.open(fileobj=buf,mode='w') as tar:
                m=tarfile.TarInfo(name);m.type=kind;tar.addfile(m)
            buf.seek(0)
            with tarfile.open(fileobj=buf,mode='r') as tar:
                with self.assertRaises(ValueError):recovery.validated_members(tar)

    def test_08a_linked_write_roots_and_model_redirects_are_refused(self):
        archive=self.base/'LinkedArchive';brain_local.create(archive,ROOT)
        (archive/'raw/workspaces').rmdir();(archive/'raw/workspaces').symlink_to(self.base)
        with self.assertRaises((ValueError,IntakeError)):
            core.install_plan(archive,self.base/'UnsafeHub','fixture-local')
        self.server.redirect_followed=False
        config=dict(self.config,endpoint=f'http://127.0.0.1:{self.server.server_port}/redirect/completions')
        self.assertFalse(core.doctor(config)['model_available'])
        import ast,urllib.request,time
        tree=ast.parse((ROOT/'bin/curator-run').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_post_json')
        scope=dict(os=os,json=json,urllib=__import__('urllib'),time=time)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<model-call>','exec'),scope)
        with patch.dict(os.environ,CURATOR_LOCAL_ONLY='1'):
            with self.assertRaises(ValueError):scope['_post_json'](urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}/redirect'),2)
        self.assertFalse(self.server.redirect_followed)

    def test_08_activation_preview_and_failure_rollback_use_fake_scheduler(self):
        remote=self.home/'.brain-hub';remote.write_text('other:/archive')
        try:
            with self.assertRaises(ValueError):core.activation_plan(self.config)
        finally:remote.unlink()
        self.assertFalse(core.activate(self.config)['applied'])
        with self.assertRaises(ValueError):core.activate(self.config,True,False)
        scheduler=self.base/'fake-launchctl';calls=self.base/'scheduler-calls'
        scheduler.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "'+str(calls)+'"\ncase "$1 $3" in "bootstrap "*audit.plist) exit 1;; esac\nexit 0\n');scheduler.chmod(0o700)
        with patch.dict(os.environ,SOV_LAUNCHCTL=str(scheduler)):
            with self.assertRaises(subprocess.CalledProcessError):core.activate(self.config,True,True)
        self.assertFalse((self.home/'.brain-root').exists())
        self.assertEqual(list((self.home/'Library/LaunchAgents').glob('*.plist')),[])
        self.assertIn('bootout',calls.read_text())

    def test_09_activation_success_uses_fake_scheduler_and_copied_front_door(self):
        scheduler=self.base/'successful-launchctl';scheduler.write_text('#!/bin/sh\nexit 0\n');scheduler.chmod(0o700)
        with patch.dict(os.environ,SOV_LAUNCHCTL=str(scheduler)):
            self.assertTrue(core.activate(self.config,True,True)['applied'])
            with self.assertRaises(ValueError):core.activate(self.config,True,True)
        units=list((self.home/'Library/LaunchAgents').glob('*.plist'));self.assertEqual(len(units),3)
        self.assertEqual((self.home/'.brain-root').read_text().strip(),str(self.archive))
        cp=subprocess.run([str(self.home/'brain-bin/sov'),'hub','status'],capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
        self.assertEqual(json.loads(cp.stdout)['receipts']['activation']['state'],'activated')

    def test_10_git_history_survives_with_pushes_and_hooks_disabled(self):
        def git(root,*args):
            return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
        git(self.archive,'init','-q');git(self.archive,'config','user.name','Sovereign fixture');git(self.archive,'config','user.email','fixture@example.invalid')
        git(self.archive,'add','.');git(self.archive,'commit','-qm','Synthetic recovery fixture')
        git(self.archive,'remote','add','origin','https://example.invalid/fixture.git')
        head=git(self.archive,'rev-parse','HEAD');original=(self.archive/'.git/config').read_bytes()
        capsule=self.backups/'git.sovbackup';recovery.snapshot(self.config,capsule,self.key,True)
        dest=self.base/'GitRestored';recovery.restore(capsule,dest,self.key,True)
        self.assertEqual(git(dest/'archive','rev-parse','HEAD'),head)
        self.assertEqual(git(dest/'archive','config','core.hooksPath'),'/dev/null')
        self.assertEqual(git(dest/'archive','config','remote.origin.pushurl'),'disabled://restored-hub-needs-review')
        self.assertFalse((dest/'hub/receipts/activation.json').exists())
        self.assertEqual((self.archive/'.git/config').read_bytes(),original)

if __name__=='__main__':unittest.main()
