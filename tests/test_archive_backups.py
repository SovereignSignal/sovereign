import hashlib
import errno
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local
from sovereign_hub import backups as b
from sovereign_hub import core


class ArchiveBackups(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='sov-backups-',dir='/private/tmp')
        self.base=Path(self.tmp.name).resolve();self.home=self.base/'home';self.home.mkdir()
        self.archive=self.base/'archive';brain_local.create(self.archive,ROOT)
        self.folder=self.base/'destination';self.folder.mkdir()
        self.key=self.home/'recovery.key';self.restore=self.base/'restored'
        self.engine=self.base/'engine';(self.engine/'bin').mkdir(parents=True)
        (self.engine/'bin/sov').write_text('#!/bin/sh\nexit 0\n')
        self.runtime=self.base/'runtime';(self.runtime/'bin').mkdir(parents=True)
        (self.runtime/'bin/python3').write_text('fixture-runtime')
        self.environment=patch.dict(os.environ,HOME=str(self.home),SOV_STATE_DIR=str(self.home/'state'),BRAIN_ROOT='',SOVS_VAULT='',BRAIN_HUB='',SOVEREIGN_HUB='',SOVEREIGN_ROOT='',SOVEREIGN_VAULT='')
        self.environment.start()
        self.root_patch=patch.object(b,'roots',lambda ctx:[('archive',ctx['root'],{'repos','.obsidian'}),('engine',self.engine,set()),('runtime',self.runtime,set())]);self.root_patch.start()
        self.extra_patch=patch.object(b,'extra_files',lambda ctx:[]);self.extra_patch.start()
        self.note=self.archive/'knowledge/concepts/decision.md';self.note.write_text('A trusted decision.\n')
    def tearDown(self):
        self.extra_patch.stop();self.root_patch.stop();self.environment.stop();self.tmp.cleanup()
    def request(self,action,apply=False,**fields):
        req=dict(protocol=1,root=str(self.archive),action=action,**fields)
        preview=b.operate(req)
        if apply:return b.operate(dict(req,apply=True,token=preview['token']))
        return preview
    def configure(self):
        return self.request('configure',True,folder=str(self.folder),key=str(self.key))
    def backup(self):
        self.configure();return self.request('backup',True)
    def test_preview_zero_write_and_unreviewed_apply_refused(self):
        self.request('configure',folder=str(self.folder),key=str(self.key))
        self.assertFalse(self.key.exists());self.assertFalse((self.home/'state').exists())
        with self.assertRaisesRegex(ValueError,'Preview|preview'):
            b.operate(dict(protocol=1,root=str(self.archive),action='configure',folder=str(self.folder),key=str(self.key),apply=True))
    def test_roundtrip_preserves_governance_without_live_configuration_changes(self):
        lane=self.archive/'raw/workspaces/curator';lane.mkdir(parents=True)
        (lane/'decisions.log').write_text('owner approved decision\n');(lane/'gears.json').write_text('{"entity":"ask-first"}')
        self.configure();cfg=(self.home/'state').rglob('config.json');before={str(p):p.read_bytes() for p in cfg}
        saved=self.request('backup',True);self.assertTrue(saved['integrity_verified'])
        self.assertFalse(saved['restore_tested'])
        r=self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        self.assertEqual(r['state'],'restored');self.assertTrue(r['activation_required']);self.assertFalse(r['scheduled'])
        self.assertEqual((self.restore/'archive/knowledge/concepts/decision.md').read_bytes(),self.note.read_bytes())
        self.assertEqual((self.restore/'archive/raw/workspaces/curator/decisions.log').read_bytes(),(lane/'decisions.log').read_bytes())
        for p,raw in before.items():self.assertEqual(Path(p).read_bytes(),raw)
        self.assertFalse((self.home/'.brain-root').exists());self.assertFalse((self.home/'Library/LaunchAgents').exists())
        with self.assertRaises(ValueError):self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
    def test_fresh_computer_restore_needs_no_destination_config(self):
        saved=self.backup();other=self.base/'fresh-home';other.mkdir()
        with patch.dict(os.environ,HOME=str(other),SOV_STATE_DIR=str(other/'state')):
            r=self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
            self.assertEqual(r['state'],'restored');self.assertFalse((other/'.brain-root').exists())
    def test_disconnected_destination_cannot_fall_back_to_source_disk(self):
        self.configure();self.folder.rename(self.base/'disconnected');self.folder.mkdir()
        with self.assertRaisesRegex(ValueError,'disconnected|changed'):self.request('backup',True)
        self.assertEqual(list(self.folder.iterdir()),[])
        self.assertFalse(b.operate(dict(protocol=1,action='status',root=str(self.archive)))['destinations'][0]['available'])
    def test_key_outside_archive_and_backup_and_wrong_key(self):
        for key in (self.folder/'key',self.archive/'key'):
            with self.assertRaises(ValueError):self.request('configure',folder=str(self.folder),key=str(key))
        saved=self.backup();wrong=self.home/'wrong.key';wrong.write_bytes(os.urandom(32));wrong.chmod(0o600)
        with self.assertRaises(subprocess.CalledProcessError):self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(wrong))
        self.assertFalse(self.restore.exists())
    def test_tamper_truncation_and_trailing_bytes_rejected(self):
        saved=self.backup();path=Path(saved['backup']);raw=path.read_bytes()
        for bad in (raw[:-1],raw+b'x',raw[:100]+bytes([raw[100]^1])+raw[101:]):
            path.write_bytes(bad)
            with self.assertRaises(subprocess.CalledProcessError):self.request('restore',True,backup=str(path),destination=str(self.restore),key=str(self.key))
            self.assertFalse(self.restore.exists())
        path.write_bytes(raw)
    def test_full_destination_keeps_previous_success(self):
        saved=self.backup();ctx=b.context(str(self.archive));receipt=(ctx['store']/'last-success.json').read_bytes()
        with patch.object(b.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(1,1,0)):
            with self.assertRaisesRegex(ValueError,'Insufficient'):self.request('backup',True)
        self.assertEqual((ctx['store']/'last-success.json').read_bytes(),receipt)
        self.assertEqual(b.status(ctx)['destinations'][0]['last_attempt']['state'],'failed')
        self.assertTrue(Path(saved['backup']).exists())
    def test_changed_source_fails_without_publishing(self):
        self.configure();original=b.inventory;calls=[0]
        def changing(ctx):
            calls[0]+=1
            if calls[0] in (5,7):self.note.write_text('changed during collection '+str(calls[0]))
            return original(ctx)
        with patch.object(b,'inventory',side_effect=changing):
            with self.assertRaisesRegex(ValueError,'changed'):self.request('backup',True)
        self.assertEqual(list(self.folder.glob('*.sovbackup')),[])
    def test_source_contention_retries_once_and_saves_consistent_new_content(self):
        self.configure(); original=b.inventory; calls=[0]
        def changing(ctx):
            calls[0]+=1
            if calls[0]==5:self.note.write_text('new consistent content')
            return original(ctx)
        with patch.object(b,'inventory',side_effect=changing):saved=self.request('backup',True)
        self.assertEqual(saved['attempts'],2)
        self.assertEqual(len(list(self.folder.glob('*.sovbackup'))),1)
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        self.assertEqual((self.restore/'archive/knowledge/concepts/decision.md').read_text(),'new consistent content')
    def test_storage_error_is_not_retried(self):
        self.configure()
        with patch.object(b,'make_backup',side_effect=OSError('disk disconnected')) as make:
            with self.assertRaises(OSError):self.request('backup',True)
        self.assertEqual(make.call_count,1)
    def test_reconnect_after_restart_preserves_history_and_refuses_other_destination(self):
        saved=self.backup(); ctx=b.context(str(self.archive)); before=b.receipt(ctx,'last-success.json')
        moved=self.base/'remounted';self.folder.rename(moved)
        # Simulate a newly launched app: only persisted configuration is available.
        self.assertFalse(self.request('status')['destinations'][0]['available'])
        wrong=self.base/'wrong';wrong.mkdir()
        with self.assertRaisesRegex(ValueError,'different backup'):self.request('reconnect',True,folder=str(wrong))
        plan=self.request('reconnect',folder=str(moved))
        self.assertEqual(b.configuration(ctx)['folder'],str(self.folder))
        self.request('reconnect',True,folder=str(moved))
        self.assertEqual(b.receipt(ctx,'last-success.json'),before)
        self.assertEqual(b.configuration(ctx)['archive_id'],saved['archive_id'])
        self.assertTrue(self.request('status')['destinations'][0]['latest_present'])
        self.request('verify',True,backup=str(moved/Path(saved['backup']).name))
    def test_reconnect_preview_rejects_changed_identity(self):
        self.configure();plan=self.request('reconnect',folder=str(self.folder))
        (self.folder/'.sovereign-backup-destination.json').write_text('{"version":1,"id":"'+'a'*32+'"}')
        with self.assertRaises(ValueError):
            b.operate(dict(protocol=1,root=str(self.archive),action='reconnect',folder=str(self.folder),apply=True,token=plan['token']))
    def test_status_does_not_transfer_restore_proof_to_new_backup_or_missing_copy(self):
        saved=self.backup()
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        self.assertTrue(self.request('status')['destinations'][0]['latest_restored'])
        latest=self.request('backup',True)
        self.assertFalse(self.request('status')['destinations'][0]['latest_restored'])
        self.assertTrue(self.request('status')['destinations'][0]['latest_present'])
        Path(latest['backup']).unlink()
        self.assertFalse(self.request('status')['destinations'][0]['latest_present'])
    def test_symlink_source_and_key_refused(self):
        self.configure();(self.archive/'linked').symlink_to(self.key)
        with self.assertRaises(ValueError):self.request('backup',True)
        (self.archive/'linked').unlink();link=self.home/'linked-key';link.symlink_to(self.key)
        with self.assertRaises((ValueError,OSError)):self.request('configure',folder=str(self.folder),key=str(link))
    def test_path_traversal_and_symlink_in_restore_refused(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('archive/linked',tarfile.SYMTYPE),('/abs',tarfile.REGTYPE),('manifest.json/child',tarfile.REGTYPE)]:
            tarpath=self.base/'bad.tar'
            with tarfile.open(tarpath,'w') as tar:
                item=tarfile.TarInfo(name);item.type=kind;tar.addfile(item)
            with self.assertRaises(ValueError):b.inspect_tar(tarpath)
    def test_preview_binds_destination_and_key(self):
        plan=self.request('configure',folder=str(self.folder),key=str(self.key))
        self.key.write_bytes(os.urandom(32));self.key.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'changed'):
            b.operate(dict(protocol=1,root=str(self.archive),action='configure',folder=str(self.folder),key=str(self.key),token=plan['token'],apply=True))
    def test_git_restores_head_but_disables_hooks_and_pushes(self):
        def git(*args):return subprocess.run(['git','-C',str(self.archive),*args],check=True,capture_output=True,text=True).stdout.strip()
        git('init','-q');git('config','user.name','Backup fixture');git('config','user.email','backup@example.invalid')
        git('add','.');git('commit','-qm','Fixture');head=git('rev-parse','HEAD');git('remote','add','origin','https://example.invalid/fixture')
        before=(self.archive/'.git/config').read_bytes();saved=self.backup()
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        result=subprocess.run(['git','-C',str(self.restore/'archive'),'rev-parse','HEAD'],check=True,capture_output=True,text=True)
        self.assertEqual(result.stdout.strip(),head);self.assertEqual((self.archive/'.git/config').read_bytes(),before)
        config=(self.restore/'archive/.git/config').read_text();self.assertIn('disabled://restore-needs-activation',config);self.assertIn('/dev/null',config)
    def test_client_routes_to_authority_and_never_uses_mirror(self):
        (self.home/'.brain-root').write_text(str(self.archive));(self.home/'.brain-hub').write_text('authority:/archive')
        state=self.home/'state';state.mkdir();(state/'connectors.json').write_text(json.dumps({'machine':{'role':'client','mode':'read-and-contribute'}}))
        response=subprocess.CompletedProcess([],0,json.dumps({'protocol':1,'host':'authority','destinations':[]}), '')
        with patch.object(b.subprocess,'run',return_value=response) as run:
            r=self.request('status');self.assertTrue(r['remote'])
            args,kwargs=run.call_args
            self.assertIn('authority',args[0]);self.assertEqual(json.loads(kwargs['input'])['root'],'/archive')
        with patch.object(b.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','old command')):
            with self.assertRaisesRegex(ValueError,'No local fallback'):self.request('backup',True)
        self.assertFalse((self.archive/'backups').exists())
    def spellings(self,path):
        # APFS ignores case and Unicode form, and /System/Volumes/Data firmlinks the data
        # volume, so one folder answers to several spellings. Keep those this disk honours.
        found=[v for v in (str(path).replace('/archive','/ARCHIVE'),'/System/Volumes/Data'+str(path)) if os.path.exists(v) and os.path.samefile(v,path)]
        if not found:self.skipTest('this volume spells each folder one way')
        return found
    def test_inside_archive_guards_judge_the_folder_not_its_spelling(self):
        saved=self.backup()
        for inside in self.spellings(self.archive/'workstreams'):
            with self.assertRaisesRegex(ValueError,'outside the archive'):self.request('configure',folder=str(self.folder),key=inside+'/sovereign-recovery.key')
            with self.assertRaisesRegex(ValueError,'separate backup folder'):self.request('configure',folder=inside,key=str(self.key))
            with self.assertRaisesRegex(ValueError,'Restore outside'):self.request('restore',backup=saved['backup'],destination=inside+'/restored',key=str(self.key))
        self.assertFalse((self.archive/'workstreams/sovereign-recovery.key').exists())
    def test_client_and_hub_know_their_archive_however_the_pointer_spells_it(self):
        named=self.base/'Café';brain_local.create(named,ROOT);decomposed=str(self.base/'Café')
        if not os.path.samefile(decomposed,named):self.skipTest('this volume keeps Unicode forms apart')
        state=self.home/'state';state.mkdir();hub=self.home/'.brain-hub';response=subprocess.CompletedProcess([],0,json.dumps({'protocol':1,'host':'authority','destinations':[]}),'')
        for pointer,root in [(decomposed,named)]+[(v,self.archive) for v in self.spellings(self.archive)]:
            (self.home/'.brain-root').write_text(pointer);hub.write_text('authority:/archive')
            (state/'connectors.json').write_text(json.dumps({'machine':{'role':'client','mode':'read-and-contribute'}}))
            with patch.object(b.subprocess,'run',return_value=response):
                self.assertTrue(b.operate(dict(protocol=1,root=str(root),action='status'))['remote'],pointer)
            hub.unlink();(state/'connectors.json').write_text(json.dumps({'machine':{'role':'hub'}}))
            self.assertEqual(b.operate(dict(protocol=1,root=str(root),action='status'),serve=True)['root'],str(root))
    def test_serve_refuses_wrong_authority_and_mixed_protocol(self):
        with self.assertRaisesRegex(ValueError,'authority'):b.operate(dict(protocol=1,root=str(self.archive),action='status'),serve=True)
        with self.assertRaisesRegex(ValueError,'Upgrade'):b.operate(dict(protocol=99,root=str(self.archive),action='status'))
    def test_source_larger_than_old_file_limit(self):
        self.configure();large=self.archive/'raw/large.md'
        with large.open('wb') as f:f.truncate(512*1024*1024)
        plan=self.request('backup');self.assertGreater(plan['source_bytes'],128*1024*1024)
        saved=self.request('backup',True)
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        self.assertEqual((self.restore/'archive/raw/large.md').stat().st_size,512*1024*1024)

    def test_reordered_and_cross_stream_frames_are_rejected(self):
        self.configure();plain=self.base/'plain';plain.write_bytes(b'a'*(5*1024*1024))
        first=self.base/'first';second=self.base/'second';b.crypt('seal',self.key,plain,first);b.crypt('seal',self.key,plain,second)
        def frames(raw):
            out=[];pos=24
            while pos<len(raw):
                length=int.from_bytes(raw[pos:pos+8],'big');out.append(raw[pos:pos+8+length]);pos+=8+length
            return out
        raw=first.read_bytes();a=frames(raw);other=frames(second.read_bytes());bad=self.base/'bad';out=self.base/'opened'
        for items in ([a[1],a[0],a[2]],[other[0],a[1],a[2]],[a[0],a[0],a[2]]):
            bad.write_bytes(raw[:24]+b''.join(items))
            with self.assertRaises(subprocess.CalledProcessError):b.crypt('open',self.key,bad,out)
            self.assertFalse(out.exists())

    def test_completed_backup_publication_cannot_replace_existing_file(self):
        source=self.base/'ready';source.write_bytes(b'new')
        destination=self.base/'existing';destination.write_bytes(b'previous')
        with self.assertRaises(FileExistsError):b.publish(source,destination)
        self.assertEqual(destination.read_bytes(),b'previous');self.assertEqual(source.read_bytes(),b'new')

    @staticmethod
    def unsupported_rename(*args):
        b.ctypes.set_errno(errno.ENOTSUP)
        return -1

    def test_smb_publication_roundtrip_without_exclusive_rename(self):
        with patch.object(b.ctypes,'CDLL') as library,patch.object(os,'link',side_effect=OSError(errno.ENOTSUP,'No hard links on SMB')):
            library.return_value.renamex_np.side_effect=self.unsupported_rename
            saved=self.backup()
        self.assertTrue(saved['integrity_verified'])
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        self.assertEqual((self.restore/'archive/knowledge/concepts/decision.md').read_bytes(),self.note.read_bytes())

    def test_smb_publication_cannot_replace_file_or_symlink(self):
        source=self.base/'ready';source.write_bytes(b'new')
        destination=self.base/'existing';destination.write_bytes(b'previous')
        alias=self.base/'alias';alias.symlink_to(destination)
        with patch.object(b.ctypes,'CDLL') as library:
            library.return_value.renamex_np.side_effect=self.unsupported_rename
            for target in (destination,alias):
                with self.assertRaises(FileExistsError):b.publish(source,target)
        self.assertEqual(destination.read_bytes(),b'previous')
        self.assertTrue(alias.is_symlink())

    def test_smb_partial_write_preserves_previous_success(self):
        self.backup();ctx=b.context(str(self.archive))
        previous=(ctx['store']/'last-success.json').read_bytes()
        files=set(self.folder.iterdir())
        def interrupted(source,output,length):
            output.write(b'partial ciphertext')
            raise OSError(errno.ENOSPC,'Storage filled during write')
        with patch.object(b.ctypes,'CDLL') as library,patch.object(b.shutil,'copyfileobj',side_effect=interrupted):
            library.return_value.renamex_np.side_effect=self.unsupported_rename
            with self.assertRaises(OSError):self.request('backup',True)
        self.assertEqual((ctx['store']/'last-success.json').read_bytes(),previous)
        self.assertEqual(set(self.folder.iterdir()),files)
        self.assertEqual(json.loads((ctx['store']/'last-attempt.json').read_text())['state'],'failed')

    def test_smb_publication_checks_saved_bytes(self):
        source=self.base/'ready';source.write_bytes(b'validated ciphertext')
        destination=self.base/'completed'
        def corrupted(input_file,output,length):output.write(b'corrupt transfer')
        with patch.object(b.ctypes,'CDLL') as library,patch.object(b.shutil,'copyfileobj',side_effect=corrupted):
            library.return_value.renamex_np.side_effect=self.unsupported_rename
            with self.assertRaisesRegex(ValueError,'differs'):b.publish(source,destination)
        self.assertFalse(destination.exists())
        self.assertEqual(source.read_bytes(),b'validated ciphertext')

    def test_ssh_template_discovers_app_runtime_without_inherited_environment(self):
        app=self.home/'Applications/Sovereign.app';runtime=app/'Contents/Resources/runtime'
        shutil.copytree(self.runtime,runtime)
        env={k:v for k,v in os.environ.items() if k!='SOV_PYTHON_RUNTIME'}
        with patch.dict(os.environ,env,clear=True),patch.object(core,'python_runtime',side_effect=ValueError('No adjacent runtime')):
            self.assertEqual(b.recovery_runtime(),runtime)

    def test_internal_file_directory_and_broken_links_roundtrip_without_following(self):
        (self.archive/'note-link').symlink_to(self.note)
        (self.archive/'directory-link').symlink_to('knowledge')
        (self.archive/'broken-link').symlink_to('missing-historical-file')
        saved=self.backup()
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        archive=self.restore/'archive'
        self.assertEqual((archive/'note-link').read_bytes(),self.note.read_bytes())
        self.assertEqual((archive/'note-link').resolve(),archive/'knowledge/concepts/decision.md')
        self.assertEqual((archive/'directory-link').resolve(),archive/'knowledge')
        self.assertTrue((archive/'broken-link').is_symlink());self.assertFalse((archive/'broken-link').exists())

    def test_manifest_cannot_create_escaping_or_traversed_links(self):
        saved=self.backup();plain=self.base/'plain.tar';b.crypt('open',self.key,Path(saved['backup']),plain)
        for links in ({'archive/link':'outside'},{'archive/link':'archive/../outside'},
                      {'archive/link':'archive/knowledge','archive/second':'archive/link/concepts'},
                      {'archive/knowledge':'archive/raw'}):
            bad=self.base/'bad-links.tar'
            with tarfile.open(plain) as src,tarfile.open(bad,'w') as dst:
                for member in src:
                    raw=src.extractfile(member).read()
                    if member.name=='manifest.json':
                        metadata=json.loads(raw);metadata['links']=links;raw=json.dumps(metadata).encode();member.size=len(raw)
                    dst.addfile(member,io.BytesIO(raw))
            with self.assertRaises(ValueError):b.inspect_tar(bad)

    def test_template_state_and_checkpoints_restored_as_inactive_evidence(self):
        self.extra_patch.stop()
        state=self.home/'state';state.mkdir();(self.home/'.brain-root').write_text(str(self.archive))
        data={'hub.json':{'vault':str(self.archive),'lanes':['fixture']},'connectors.json':{'machine':{'role':'hub'}},'intake-fixture.json':{'cursor':'123'}}
        for name,value in data.items():(state/name).write_text(json.dumps(value))
        before={name:(state/name).read_bytes() for name in data};saved=self.backup()
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        for name,raw in before.items():self.assertEqual((state/name).read_bytes(),raw)
        self.assertEqual((self.restore/'state/intake-fixture.json').read_bytes(),before['intake-fixture.json'])
        self.assertEqual(json.loads((self.restore/'state/hub.json').read_text())['vault'],str(self.restore/'archive'))
        self.assertFalse((self.home/'Library/LaunchAgents').exists())

    def test_managed_hub_restores_with_rebased_inactive_launcher(self):
        self.root_patch.stop();self.extra_patch.stop()
        destination=self.base/'managed-hub'
        core.install(core.install_plan(self.archive,destination,'fixture-local'),True)
        (self.home/'.sovereign-hub').write_text(str(destination/'config.json'))
        cfg=(destination/'config.json').read_bytes();saved=self.backup()
        self.request('restore',True,backup=saved['backup'],destination=str(self.restore),key=str(self.key))
        restored=json.loads((self.restore/'hub/config.json').read_text())
        self.assertEqual(restored['archive'],str(self.restore/'archive'))
        self.assertIsNone(restored['recovery_key']);self.assertEqual((destination/'config.json').read_bytes(),cfg)
        self.assertFalse((self.restore/'hub/receipts/activation.json').exists())
        self.assertFalse((self.home/'Library/LaunchAgents').exists())
        cp=subprocess.run([str(self.restore/'hub/bin/sov'),'hub','status','--config',str(self.restore/'hub/config.json')],capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stderr+cp.stdout)

if __name__=='__main__':unittest.main()
