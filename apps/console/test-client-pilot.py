#!/usr/bin/env python3
"""Native role and intake UI plus the installed offline introduction, using fixtures."""
import argparse,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT/'lib'))
import brain_local
PROBE=r'''
const checks={},check=(k,v)=>checks[k]=!!v,post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
for(let i=0;i<100&&!document.querySelector('.today-headline');i++)await pause(50);
const today=document.getElementById('system-home');
check('A failed intake needs the owner',SCENE==='error'?today.textContent.includes('Worker-QA')&&today.textContent.includes('intake failed')&&today.textContent.includes('Intake needs attention'):true);
check('A healthy intake is not attention',SCENE==='error'?true:!today.textContent.includes('Worker-QA'));
check('Today has no horizontal overflow',document.documentElement.scrollWidth<=innerWidth);
window.sovView('system');
let view=document.querySelector('.sv');
check('Explicit hub label visible',view.textContent.includes('Hub · This device'));
check('Explicit client label visible',view.textContent.includes('Client · Not checked'));
check('Intake relationship appears in map',!!view.querySelector('.sv-world-wire'));
view.querySelector('[data-node="device:Worker-QA"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
check('Client description explains scope',view.textContent.includes('Contributes selected work through a separate intake'));
view.querySelector('[data-pane="inspect"]').click();
view=document.querySelector('.sv');
check('Inspect shows client mode',view.textContent.includes('Contribute only'));
check('Inspect shows receipt evidence',view.textContent.includes('Received by hub'));
check('Import is claimed only when it happened',SCENE==='imported'?view.textContent.includes('Imported into raw'):true);
check('No page overflow in Inspect',document.documentElement.scrollWidth<=innerWidth);
post({cmd:'clientError',where:'client-pilot-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 cases=[('imported','dark','1200x800'),('received','light','720x460'),('error','dark','720x460'),('imported','light','1000x700')]
 for scene,theme,size in cases:
  with tempfile.TemporaryDirectory(prefix='sovereign-client-ui-') as tmp:
   b=Path(tmp);archive=b/'QA Archive';brain_local.create(archive,ROOT);archive=archive.resolve();now=datetime.now(timezone.utc).isoformat();suite='com.sovereign.qa.clients.'+uuid.uuid4().hex
   c={'client_id':'Worker-QA','client_mode':'contribute-only','collected_at':now,'received_at':now,'imported_at':now if scene=='imported' else None,'state':scene,'promotion':'not-evaluated'}
   if scene=='error':c['reason']='git_fetch_failed'
   data={'generated_at':now,'machine':{'host':'Desk-QA','vault':str(archive),'vault_name':'QA Archive','role':'hub','connected':True},'hub':{'reachable':True,'via':'local','hub_host':'Desk-QA','pending':0},'clients':[c],'harnesses':[],'needs_you':[]}
   payload=b/'status.json';payload.write_text(json.dumps(data));command=b/'status';command.write_text('#!/bin/sh\nexec /bin/cat '+"'"+str(payload)+"'\n");command.chmod(0o700)
   name=scene+'-'+theme+'-'+size
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(command),SOV_QA_JS='(async()=>{'+PROBE.replace('SCENE',json.dumps(scene))+'})().catch(e=>window.webkit.messageHandlers.sov.postMessage({cmd:"clientError",where:"client-pilot-qa",msg:JSON.stringify({checks:{},failures:[String(e)]})}));',SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(a.evidence/(name+'.png')),SOV_SNAPSHOT_DELAY='5')
   try:
    cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=30)
    (a.evidence/(name+'.log')).write_text(cp.stderr);marker='client error in client-pilot-qa: ';rows=[json.loads(x.split(marker,1)[1]) for x in cp.stderr.splitlines() if marker in x];assert cp.returncode==0 and len(rows)==1,(name,cp.stderr);v=dict(rows[0],scene=scene,theme=theme,size=size);reports.append(v);assert not v['failures'],v;print(name,len(v['checks']),'checks passed',flush=True)
   finally:
    subprocess.run(['defaults','delete',suite],capture_output=True);Path.home().joinpath('Library/Preferences',suite+'.plist').unlink(missing_ok=True);(a.evidence/'native-clients.json').write_text(json.dumps(reports,indent=2)+'\n')
 with tempfile.TemporaryDirectory(prefix='sovereign-offline-') as tmp:
  b=Path(tmp);state=b/'state';state.mkdir();(state/'connectors.json').write_text(json.dumps({'machine':{'role':'client','mode':'contribute-only'}}));env=dict(os.environ,HOME=str(b),PATH='/nonexistent',SOV_STATE_DIR=str(state));env.pop('BRAIN_ROOT',None)
  helper=HERE/'build/Sovereign.app/Contents/MacOS/sov';cp=subprocess.run([str(helper),'about','--json'],env=env,cwd=tmp,capture_output=True,text=True,check=True);v=json.loads(cp.stdout);assert v['machine']['client_mode']=='contribute-only' and not v['network'] and not v['writes'];(a.evidence/'offline-introduction.json').write_text(cp.stdout);subprocess.run([str(helper)],env=env,cwd=tmp,capture_output=True,text=True,check=True)
 print(sum(len(x['checks']) for x in reports),'native checks and offline bundle entry point passed')
if __name__=='__main__':main()
