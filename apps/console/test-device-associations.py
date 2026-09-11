#!/usr/bin/env python3
"""Exercise real native preference writes in an isolated suite and disposable archives."""
import argparse, hashlib, json, os, plistlib, subprocess, sys, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local

PROBE=r'''
const checks={},check=(name,ok)=>{checks[name]=!!ok},post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async fn=>{for(let i=0;i<100;i++){if(fn())return;await pause(40)}throw Error('UI state did not arrive')};
const button=()=>document.querySelector('[data-act="device-disassociate"]');
const restore=()=>document.querySelector('[data-act="device-restore"]');
const replies=[],deliver=window.sovDeliver;
window.sovDeliver=(kind,payload)=>{if(kind==='deviceAssociation')replies.push(payload);deliver(kind,payload)};
if(PHASE==='disassociate'){
 await wait(button);check('Offline device can be disassociated',!!button());
 for(const [host,root] of [['Desk-QA',ROOT],['Hub-QA',ROOT],['unknown-device',ROOT],['retired-worker',ROOT+'/other']]){
  const n=replies.length;post({cmd:'deviceAssociation',host,root,associated:false});await wait(()=>replies.length>n);
  check('Native guard '+host+' '+root,replies.at(-1).error);
 }
 button().click();check('Confirmation explains local scope',document.querySelector('#device-dialog').textContent.includes('Saved for this archive on this Mac'));
 check('Cancel initially focused',document.activeElement.id==='device-cancel');
 document.querySelector('#device-cancel').click();check('Cancel keeps device active',!!button()&&!document.querySelector('#device-dialog').open);
 button().click();document.querySelector('#device-confirm').click();await wait(restore);
 check('Disassociated group visible',document.querySelector('#rows').textContent.includes('Disassociated devices'));
 check('Inactive device has neutral row',!document.querySelector('.row[data-id="retired-worker"] .dot.down'));
 check('Offline alert removed',!document.querySelector('#vtext').textContent.includes('retired-worker'));
 check('Restore action available',!!restore());
 window.sovRefresh();await pause(350);check('Refresh preserves disassociation',!!restore());
}else if(PHASE==='restore'){
 await wait(restore);check('Disassociation survives app restart',!!restore());restore().click();await wait(button);
 check('Restore returns device to active list',!document.querySelector('#rows').textContent.includes('Disassociated devices'));
 check('Offline warning returns after restore',document.querySelector('#vtext').textContent.includes('retired-worker'));
}else if(PHASE==='other-archive'){
 await wait(button);check('Choice does not leak into another archive',!!button()&&!restore());
}else if(PHASE==='dialog'){
 await wait(button);button().click();check('Dialog opens',document.querySelector('#device-dialog').open);
 check('Dialog fits narrow window',document.querySelector('#device-dialog').getBoundingClientRect().right<=innerWidth);
 check('Dialog has opaque themed background',getComputedStyle(document.querySelector('#device-dialog')).backgroundColor!=='rgba(0, 0, 0, 0)');
}
check('No horizontal page overflow',document.documentElement.scrollWidth<=innerWidth);
post({cmd:'clientError',where:'device-association-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''

def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);args=p.parse_args();args.evidence.mkdir(parents=True,exist_ok=True)
 suite='com.sovereign.qa.devices.'+uuid.uuid4().hex;results=[]
 with tempfile.TemporaryDirectory(prefix='sovereign-devices-') as tmp:
  base=Path(tmp);archives=[base/'Archive A',base/'Archive B']
  for archive in archives:brain_local.create(archive,ROOT)
  archives=[a.resolve() for a in archives]
  history=archives[0]/'raw/tools/manual/retained.md';history.parent.mkdir(parents=True,exist_ok=True);history.write_text('Historical work remains owned.\n');digest=hashlib.sha256(history.read_bytes()).hexdigest()
  try:
   for phase,archive,theme,size in [('disassociate',archives[0],'dark','1000x700'),('other-archive',archives[1],'light','1000x700'),('restore',archives[0],'light','1000x700'),('dialog',archives[0],'light','720x460')]:
    data={'generated_at':datetime.now(timezone.utc).isoformat(),'machine':{'host':'Desk-QA','vault':str(archive),'vault_name':archive.name,'connected':True,'hub_pointer':'Hub-QA:/hub'},'hub':{'reachable':True,'via':'ssh Hub-QA','hub_host':'Hub-QA','pending':0},'harnesses':[],'lanes':[],
      'fleet':{'hosts':[{'host':'Desk-QA','net':{'online':True}},{'host':'Hub-QA','net':{'online':True}},{'host':'retired-worker','net':{'online':False},'lanes':[{'lane':'retired-history'}],'meta':{'kind':'Powered-off VM'}}]},
      'needs_you':[{'kind':'host','host':'retired-worker','text':'This device cannot currently reach retired-worker.'}]}
    payload=base/'status.json';payload.write_text(json.dumps(data));command=base/'status';command.write_text('#!/bin/sh\nexec /bin/cat '+"'"+str(payload)+"'\n");command.chmod(0o700)
    code=PROBE.replace('PHASE',json.dumps(phase)).replace('ROOT',json.dumps(str(archive)))
    env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(command),SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(args.evidence/(phase+'.png')),SOV_SNAPSHOT_DELAY='2',SOV_SNAPSHOT_ANCHOR='operations:view:hosts+open:retired-worker',SOV_QA_JS_AFTER_ANCHOR=code)
    cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=30)
    (args.evidence/(phase+'.log')).write_text(cp.stderr);marker='client error in device-association-qa: ';reports=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
    assert cp.returncode==0 and len(reports)==1,(phase,cp.stderr)
    report=dict(reports[0],phase=phase);results.append(report);assert not report['failures'],report
    saved=plistlib.loads(subprocess.check_output(['defaults','export',suite,'-'])).get('sov.deviceAssociations',{})
    (args.evidence/(phase+'-preferences.json')).write_text(json.dumps({'saved':saved,'root':str(archives[0])},indent=2))
    saved={str(Path(k).resolve()):v for k,v in saved.items()}
    assert saved.get(str(archives[0]),[])==(['retired-worker'] if phase in ('disassociate','other-archive') else []),(phase,saved,str(archives[0]))
    assert str(archives[1]) not in saved
    assert hashlib.sha256(history.read_bytes()).hexdigest()==digest
    print(phase,len(report['checks']),'checks passed',flush=True)
  finally:
   subprocess.run(['defaults','delete',suite],capture_output=True)
   (args.evidence/'native-devices.json').write_text(json.dumps(results,indent=2)+'\n')
 print('Native persistence, restore, scope and unchanged history verified.')

if __name__=='__main__':main()
