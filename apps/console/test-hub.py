#!/usr/bin/env python3
"""Run Hub setup controls against temporary archives and HOME. Never activate launchd."""
import argparse,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'));import brain_local
PROBE=r'''
const checks={},check=(n,v)=>{checks[n]=!!v},post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async fn=>{for(let i=0;i<500;i++){if(fn())return;await pause(40)}throw Error('Timed out: '+fn)};
const replies=[],deliver=window.sovDeliver;window.sovDeliver=(kind,p)=>{if(kind==='hubResult')replies.push(p);deliver(kind,p)};
await wait(()=>document.querySelector('[data-goto-view="setup"]'));
check('Setup reachable without connector service',true);document.querySelector('[data-goto-view="setup"]').click();
await wait(()=>document.querySelector('[data-hub-field="destination"]')?.value);
const input=(field,value)=>{const el=document.querySelector('[data-hub-field="'+field+'"]');el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));};
const preview=()=>document.querySelector('#hub-preview'),apply=()=>document.querySelector('#hub-apply');
const req={cmd:'hubOperation',command:'install',root:ARCHIVE,destination:DESTINATION,model:'fixture-local',endpoint:'http://127.0.0.1:11434/v1/chat/completions'};
post({...req,apply:true});await wait(()=>replies.length===1);check('Native apply requires prior preview',replies[0].error?.includes('Preview'));
post({...req,root:ARCHIVE+'-wrong',apply:false});await wait(()=>replies.length===2);check('Different archive refused natively',!!replies[1].error);
input('destination',DESTINATION);input('model','fixture-local');check('Apply initially disabled',apply().disabled);
preview().click();check('Pending operation protects navigation',!window.sovCanQuit());
await wait(()=>!apply().disabled);check('Preview prepares inactive jobs',replies[2].scheduled===false&&replies[2].applied===false);
input('model','changed-local');check('Editing invalidates preview',apply().disabled);
post({...req,model:'changed-local',apply:true});await wait(()=>replies.length===4);check('Changed request refused natively',replies[3].error?.includes('Preview'));
input('model','fixture-local');preview().click();await wait(()=>!apply().disabled);
if(PHASE==='install'){
 apply().click();check('Install shows pending state',preview().disabled);await wait(()=>replies.length===6);
 check('Bundled install completed',replies[5].applied===true&&replies[5].exit===0);check('Installed jobs stay inactive',replies[5].scheduled===false);
 check('Apply reset after completion',apply().disabled);check('Navigation available after completion',window.sovCanQuit());
}else{
 check('Separate apply is visible',apply().textContent==='Prepare Hub');
}
check('Setup page makes no health claim',!document.querySelector('#verdict.show')&&!document.querySelector('main').textContent.includes('All good'));
check('Hub setup sits under Settings',document.getElementById('settings-tab').getAttribute('aria-pressed')==='true'&&document.getElementById('vault').textContent==='Hub setup');
if(PHASE==='preview')document.querySelector('#rows').scrollTop=document.querySelector('#rows').scrollHeight;
check('No page overflow',document.documentElement.scrollWidth<=innerWidth);
check('No list overflow',document.querySelector('#rows').scrollWidth<=document.querySelector('#rows').clientWidth);
post({cmd:'clientError',where:'hub-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path);a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 with tempfile.TemporaryDirectory(prefix='sov-native-hub-',dir='/private/tmp') as tmp:
  base=Path(tmp).resolve()
  for phase in ('install','preview'):
   folder=base/phase;folder.mkdir();archive=folder/'Archive';brain_local.create(archive,ROOT)
   home=folder/'home';home.mkdir();destination=folder/'Hub'
   status=folder/'status';status.write_text('#!/bin/sh\necho \'{"machine":{"connected":false},"needs_you":[],"hub":{},"fleet":{"hosts":[]}}\'\n');status.chmod(0o700)
   suite='com.sovereign.qa.hub.'+uuid.uuid4().hex
   js=PROBE.replace('ARCHIVE',json.dumps(str(archive))).replace('DESTINATION',json.dumps(str(destination))).replace('PHASE',json.dumps(phase))
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(status),SOV_QA_HUB_HOME=str(home),SOV_APPEARANCE='light' if phase=='install' else 'dark',SOV_WINDOW='1000x700' if phase=='install' else '720x460',SOV_SNAPSHOT=str(a.evidence/(phase+'.png')),SOV_SNAPSHOT_DELAY='2',SOV_SNAPSHOT_ANCHOR='operations:view:jobs',SOV_QA_JS_AFTER_ANCHOR=js)
   try:
    cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=60)
    (a.evidence/(phase+'.log')).write_text(cp.stderr)
    marker='client error in hub-qa: ';r=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
    assert cp.returncode==0 and len(r)==1,(phase,cp.stderr);assert not r[0]['failures'],r
    assert destination.exists()==(phase=='install');assert not (home/'Library/LaunchAgents').exists();assert not (home/'.brain-root').exists();assert not (home/'.sovereign-hub').exists()
    if phase=='install':
     config=json.loads((destination/'config.json').read_text());assert config['archive']==str(archive)
     assert (destination/'python/bin/python3').is_file();assert len(list((destination/'jobs').glob('*.plist')))==3
     assert not (destination/'receipts/activation.json').exists()
    reports.append(dict(phase=phase,checks=r[0]['checks'],schedules_created=False));print(phase,len(r[0]['checks']),'checks passed',flush=True)
   finally:subprocess.run(['defaults','delete',suite],capture_output=True)
 (a.evidence/'native-hub.json').write_text(json.dumps(reports,indent=2)+'\n')
if __name__=='__main__':main()
