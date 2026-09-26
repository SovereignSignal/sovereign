#!/usr/bin/env python3
"""Native end-to-end archive backup QA. All homes, hosts and archives are fixtures."""
import argparse,json,os,subprocess,sys,tempfile,uuid,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local
PROBE=r'''
const checks={},check=(n,v)=>checks[n]=!!v,post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async fn=>{for(let n=0;n<2500;n++){if(fn())return;await pause(40)}throw Error('Timeout: '+fn)};
const replies=[],deliver=window.sovDeliver;window.sovDeliver=(kind,p)=>{if(kind==='archiveBackupResult')replies.push(p);deliver(kind,p)};
await wait(()=>document.querySelector('[data-ab-field="folder"]'));
check('Notes workspace remains removed',!document.getElementById('notes-tab')&&!document.getElementById('editor'));
check('Archive backup navigation selected',document.querySelector('#archive-backups-tab').getAttribute('aria-pressed')==='true');
check('Archive backup independent of infrastructure monitor',document.querySelector('[data-goto-view="backups"]')?.textContent==='Infrastructure copies');
const input=(field,value)=>{const e=document.querySelector('[data-ab-field="'+field+'"]');e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));};
const preview=()=>document.querySelector('#ab-preview'),apply=()=>document.querySelector('#ab-apply');
const rejected=replies.length;post({cmd:'archiveBackup',root:ARCHIVE,action:'configure',folder:FOLDER,key:KEY,apply:true});
await wait(()=>replies.length>rejected);check('Native mutation requires preview',replies.at(-1).error?.includes('Preview'));
input('folder',FOLDER);input('key',KEY);check('Apply starts disabled',apply().disabled);
preview().click();check('Pending operation blocks navigation',!window.sovCanQuit());await wait(()=>!apply().disabled);
check('Preview creates no schedule',replies.at(-1).scheduled===false&&replies.at(-1).applied===false);
if(SCENE==='narrow'){
 check('No horizontal page overflow',document.documentElement.scrollWidth<=innerWidth);
 check('No horizontal form overflow',document.querySelector('#rows').scrollWidth<=document.querySelector('#rows').clientWidth);
}else{
 apply().click();await wait(()=>document.querySelector('.ab-card')&&!window.SovBackups.busy);
 check('Destination saved on correct host',replies.some(r=>r.state==='configured'&&r.applied));
 document.querySelector('[data-ab-action="backup"]').click();preview().click();await wait(()=>!apply().disabled);
 check('Backup preview includes files',replies.at(-1).files>0);apply().click();await wait(()=>replies.some(r=>r.state==='completed')&&!window.SovBackups.busy);
 check('Saved bytes authenticated',replies.find(r=>r.state==='completed')?.integrity_verified===true);
 check('Backup does not claim restore drill',!replies.find(r=>r.state==='completed')?.restore_tested);
 document.querySelector('[data-ab-action="restore"]').click();input('destination',RESTORE);preview().click();await wait(()=>!apply().disabled);apply().click();
 await wait(()=>replies.some(r=>r.state==='restored')&&!window.SovBackups.busy);
 check('Restore stays inactive',replies.find(r=>r.state==='restored')?.activation_required===true&&replies.find(r=>r.state==='restored')?.scheduled===false);
 check('Navigation released',window.sovCanQuit());
 if(SCENE==='remote'){
  check('Authority is visible',document.querySelector('.archive-backups').textContent.includes('fixture-hub'));
  document.querySelector('#ab-refresh').click();await wait(()=>!window.SovBackups.busy);
  check('Unreachable authority shows dated prior receipts',document.querySelector('.ab-card')?.textContent.includes('previously observed receipts')&&document.querySelector('.ab-card h3')?.textContent==='Destination status unavailable');
  check('Unreachable authority cannot fall back to local backup',!document.querySelector('#ab-apply'));
 }
}
post({cmd:'clientError',where:'archive-backups-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''

def tree_hash(root):
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,default=HERE/'build/Sovereign Preview.app');parser.add_argument('--evidence',required=True,type=Path);parser.add_argument('--scene',choices=['local','remote','narrow']);a=parser.parse_args();a.evidence.mkdir(parents=True,exist_ok=True)
 reports=[]
 with tempfile.TemporaryDirectory(prefix='sov-backup-native-',dir='/private/tmp') as tmp:
  base=Path(tmp)
  for scene in ([a.scene] if a.scene else ('local','remote','narrow')):
   folder=base/scene;folder.mkdir();archive=folder/'Archive';brain_local.create(archive,ROOT)
   (archive/'knowledge/concepts/example.md').write_text('Trusted note from the archive authority.\n')
   home=folder/'home';home.mkdir();destination=folder/'Backup';destination.mkdir();key=home/'recovery.key';restore=folder/'Restored'
   status=folder/'status';status.write_text('#!/bin/sh\necho \'{"machine":{"connected":false},"needs_you":[],"hub":{},"fleet":{"hosts":[]}}\'\n');status.chmod(0o700)
   suite='com.sovereign.qa.archive-backups.'+uuid.uuid4().hex
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(status),SOV_QA_HUB_HOME=str(home),SOV_APPEARANCE='dark' if scene=='narrow' else 'light',SOV_WINDOW='720x520' if scene=='narrow' else '1100x800',SOV_SNAPSHOT=str(a.evidence/(scene+'.png')),SOV_SNAPSHOT_DELAY='5',SOV_SNAPSHOT_ANCHOR='',SOV_QA_JS="document.getElementById('archive-backups-tab').click()")
   authoritative=archive
   if scene=='remote':
    hubhome=folder/'hub-home';hubhome.mkdir();hubstate=hubhome/'.local/state/sovereign';hubstate.mkdir(parents=True)
    authoritative=folder/'Authoritative';brain_local.create(authoritative,ROOT);(authoritative/'knowledge/concepts/example.md').write_text('Authoritative fixture content distinct from the client mirror.\n')
    (hubhome/'.brain-root').write_text(str(authoritative));(hubstate/'connectors.json').write_text(json.dumps({'machine':{'role':'hub'}}))
    clientstate=home/'.local/state/sovereign';clientstate.mkdir(parents=True);(clientstate/'connectors.json').write_text(json.dumps({'machine':{'role':'client','mode':'read-and-contribute'}}))
    (home/'.brain-root').write_text(str(archive));(home/'.brain-hub').write_text('fixture-hub:'+str(authoritative))
    key=hubhome/'recovery.key'
    bridge=folder/'fixture-ssh';backend=a.app/'Contents/Resources/backend/bin/sov-backup';runtime=a.app/'Contents/Resources/runtime/bin/python3'
    bridge.write_text('#!'+sys.executable+'\nimport os,sys,subprocess,json\nfrom pathlib import Path\nraw=sys.stdin.read()\nwith open('+repr(str(folder/'requests'))+',"a") as f:f.write(raw+"\\n")\nrequests=Path('+repr(str(folder/'requests'))+').read_text().splitlines()\nif json.loads(raw).get("action")=="status" and sum(json.loads(line).get("action")=="status" for line in requests)>=5:\n print(json.dumps({"protocol":1,"error":"Fixture authority unavailable"}));sys.exit(1)\nenv=dict(os.environ,HOME='+repr(str(hubhome))+')\nenv.pop("SOV_PYTHON_RUNTIME",None)\nr=subprocess.run(['+repr(str(runtime))+',"-I","-B",'+repr(str(backend))+',"--serve"],input=raw,text=True,env=env)\nsys.exit(r.returncode)\n');bridge.chmod(0o700);env['SOV_QA_ARCHIVE_BACKUP_SSH']=str(bridge)
   (authoritative/'example-link').symlink_to('knowledge/concepts/example.md')
   before=tree_hash(archive)
   js=PROBE
   for token,value in [('ARCHIVE',str(archive)),('FOLDER',str(destination)),('KEY',str(key)),('RESTORE',str(restore)),('SCENE',scene)]:js=js.replace(token,json.dumps(value))
   env['SOV_QA_JS_AFTER_ANCHOR']=js
   try:
    cp=subprocess.run([str(a.app/'Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=240)
    (a.evidence/(scene+'.log')).write_text(cp.stderr)
    marker='client error in archive-backups-qa: ';r=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
    assert cp.returncode==0 and len(r)==1,(scene,cp.stderr[-6000:]);assert not r[0]['failures'],r
    assert tree_hash(archive)==before,'Source changed'
    assert not (home/'Library/LaunchAgents').exists()
    if scene!='narrow':
     assert (restore/'archive/knowledge/concepts/example.md').read_bytes()==(authoritative/'knowledge/concepts/example.md').read_bytes()
     assert (restore/'archive/example-link').resolve()==restore/'archive/knowledge/concepts/example.md'
     r[0]['checks']['Internal link stays inside restored archive']=True
     check=subprocess.run([str(restore/'runtime/bin/python3'),'-I','-B',str(restore/'engine/bin/sov-load'),'example','--root',str(restore/'archive')],capture_output=True,text=True)
     assert check.returncode==0 and 'fixture' in check.stdout.lower() if scene=='remote' else check.returncode==0 and 'Trusted note' in check.stdout,(check.stdout,check.stderr)
     r[0]['checks']['Restored engine loads context without installed source']=True
    else:assert not key.exists() and not list(destination.iterdir())
    reports.append(dict(scene=scene,checks=r[0]['checks']));print(scene,len(r[0]['checks']),'checks passed',flush=True)
   finally:subprocess.run(['defaults','delete',suite],capture_output=True)
 (a.evidence/'native-archive-backups.json').write_text(json.dumps(reports,indent=2)+'\n')
if __name__=='__main__':main()
