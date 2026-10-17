#!/usr/bin/env python3
"""Native producer controls use disposable status, commands, archive and preferences."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'));import brain_local
PROBE=r'''
const checks={},check=(n,x)=>{checks[n]=!!x},post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
// Bounded by the clock: a background window throttles timers, so a count of polls outlasts the snapshot watchdog and the failure goes unnamed.
const wait=async fn=>{for(const end=Date.now()+10000;Date.now()<end;await pause(40))if(fn())return;throw Error('Timed out: '+fn+'; replies='+JSON.stringify(replies)+'; drawer='+document.querySelector('#drawer-log')?.textContent)};
const replies=[],deliver=window.sovDeliver;window.sovDeliver=(kind,p)=>{if(kind==='log'&&p.state==='end')replies.push(p);deliver(kind,p)};
const apply=()=>document.querySelector('#drawer-apply'),remove=()=>document.querySelector('[data-act="remove-producer"]');
check('Connected source listed once, with its lane',document.querySelector('[data-id="windsurf"]')&&!document.querySelector('[data-id="lane:windsurf-qa"]'));
check('Add entry point',document.querySelector('#controls [data-view="discover"]')?.textContent==='Add');
if(PHASE==='flow'){
 const base={cmd:'producer',action:'remove',harness:'windsurf',root:ROOT_PATH,apply:true};
 post(base);await wait(()=>replies.length===1);check('Apply without review rejected',replies[0].exit!==0);
 post({...base,apply:false,root:'/different/archive'});await wait(()=>replies.length===2);check('Wrong archive rejected',replies[1].exit!==0);
 post({...base,apply:false,harness:'../../elsewhere'});await wait(()=>replies.length===3);check('Invalid producer rejected',replies[2].exit!==0);
 remove().click();check('Apply disabled during preview',apply().disabled);await wait(()=>!apply().disabled);
 check('Explicit removal label',apply().textContent==='Remove producer');apply().click();await wait(()=>replies.length===5);
 await wait(()=>document.querySelector('[data-id="windsurf"]')?.textContent.includes('removed'));
 check('History retained after removal',document.querySelector('[data-section="removed"]')&&document.querySelector('[data-id="windsurf"]')&&document.querySelector('#insp').textContent.includes('history is preserved'));
 document.querySelector('#drawer-close').click();document.querySelector('[data-id="windsurf"]').click();
 document.querySelector('[data-act="connect"]').click();await wait(()=>replies.length===6);
 check('Add has its own review',!apply().disabled&&apply().textContent==='Add producer');apply().click();await wait(()=>replies.length===7);
 await wait(()=>document.querySelector('[data-id="windsurf"]')&&!document.querySelector('[data-id="windsurf"]').textContent.includes('removed'));check('Reconnect visible',!document.querySelector('[data-section="removed"]'));
}else{
 remove().click();await wait(()=>replies.length===1);
 if(PHASE==='failure')check('Failed preview cannot apply',apply().disabled&&replies[0].exit!==0);
 else {check('Preview ready',!apply().disabled);document.querySelector('#drawer-close').click();check('Cancel closes preview',!document.querySelector('#drawer').classList.contains('open'));}
}
check('No page overflow',document.documentElement.scrollWidth<=innerWidth);
post({cmd:'clientError',where:'producer-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
# Fixtures run under this test's own interpreter. /usr/bin/python3 is only an install
# prompt on a Mac without the Command Line Tools, which made the fixture fail there.
assert not any(c.isspace() for c in sys.executable), 'a shebang cannot hold a path with spaces: '+sys.executable
PYTHON='#!'+sys.executable+'\n'
COMMAND=PYTHON+r'''import json,sys,time
from pathlib import Path
base=Path(__file__).parent;args=sys.argv[1:]
with (base/'calls.jsonl').open('a') as out:out.write(json.dumps(args)+'\n')
if (base/'fail').exists():print('Fixture preflight failed');sys.exit(65)
if '--apply' in args:
 p=base/'status.json';d=json.loads(p.read_text());h=d['harnesses'][0];removing=args[0]=='disconnect'
 h.update(state='removed' if removing else 'connected',declared=not removing,job_loaded=not removing,hook_registered=not removing,retired=removing)
 p.write_text(json.dumps(d))
print('History is preserved. '+('Applied.' if '--apply' in args else 'Dry run; no changes.'))
'''
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True,type=Path);args=parser.parse_args();args.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 with tempfile.TemporaryDirectory(prefix='sovereign-producers-') as tmp:
  base=Path(tmp).resolve();archive=base/'Archive';brain_local.create(archive,ROOT)
  history=archive/'raw/tools/windsurf-qa/retained.md';history.parent.mkdir(parents=True);history.write_text('Owned history.');digest=hashlib.sha256(history.read_bytes()).hexdigest()
  command=base/'producer';command.write_text(COMMAND);command.chmod(0o700)
  (base/'bin').mkdir()
  for h in ('windsurf','codex'):
   target=base/'connectors/harness'/h;target.mkdir(parents=True)
   (target/'harness.json').write_bytes((ROOT/'connectors/harness'/h/'harness.json').read_bytes())
  status=base/'bin/status';status.write_text('#!/bin/sh\nexec /bin/cat '+"'"+str(base/'status.json')+"'\n");status.chmod(0o700)
  for phase in ('flow','cancel','failure'):
   data={'generated_at':datetime.now(timezone.utc).isoformat(),'machine':{'host':'qa','vault':str(archive),'connected':True},'hub':{'via':'local','reachable':True,'pending':0},'needs_you':[],
    'harnesses':[{'id':'windsurf','name':'Windsurf','lane':'windsurf-qa','read':'instruction','state':'connected','declared':True,'job_loaded':True,'hook_registered':True,'detected':True}, {'id':'codex','name':'Codex','lane':'codex-qa','read':'hook','state':'not connected','detected':True}],
    'lanes':[{'lane':'windsurf-qa','host':'qa','producer':'Windsurf','read':'instruction','write':'mirror','vault_age_h':2}], 'fleet':{'hosts':[{'host':'qa','net':{'online':True}}]}}
   (base/'status.json').write_text(json.dumps(data));(base/'calls.jsonl').write_text('')
   if phase=='failure':(base/'fail').touch()
   suite='com.sovereign.qa.producers.'+uuid.uuid4().hex
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(status),SOV_QA_PRODUCER_COMMAND=str(command),SOV_APPEARANCE='light',SOV_WINDOW='1000x700' if phase=='flow' else '720x460',SOV_SNAPSHOT=str(args.evidence/(phase+'.png')),SOV_SNAPSHOT_DELAY='2',SOV_SNAPSHOT_ANCHOR='operations:view:sources+open:windsurf',SOV_QA_JS_AFTER_ANCHOR=PROBE.replace('PHASE',json.dumps(phase)).replace('ROOT_PATH',json.dumps(str(archive))))
   try:
    cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=45)
    (args.evidence/(phase+'.log')).write_text(cp.stderr)
    marker='client error in producer-qa: ';r=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
    assert cp.returncode==0 and len(r)==1,(phase,cp.stderr);assert not r[0]['failures'],r
    calls=[json.loads(line) for line in (base/'calls.jsonl').read_text().splitlines()]
    assert len(calls)==(4 if phase=='flow' else 1),(phase,calls)
    assert sum('--apply' in c for c in calls)==(2 if phase=='flow' else 0)
    assert hashlib.sha256(history.read_bytes()).hexdigest()==digest
    reports.append(dict(phase=phase,checks=r[0]['checks'],calls=calls));print(phase,len(r[0]['checks']),'checks passed',flush=True)
   finally:subprocess.run(['defaults','delete',suite],capture_output=True);Path.home().joinpath('Library/Preferences',suite+'.plist').unlink(missing_ok=True)
 (args.evidence/'native-producers.json').write_text(json.dumps(reports,indent=2)+'\n')
if __name__=='__main__':main()
