#!/usr/bin/env python3
"""Exercise bundled discovery and producer controls with disposable state only."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'));import brain_local
spec=importlib.util.spec_from_file_location('producer_qa',HERE/'test-producers.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
PROBE=r'''
const checks={},check=(n,x)=>{checks[n]=!!x},post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async fn=>{for(let i=0;i<180;i++){if(fn())return;await pause(40)}throw Error('Timed out: '+fn)};
const replies=[],scans=[],deliver=window.sovDeliver;window.sovDeliver=(kind,p)=>{if(kind==='log'&&p.state==='end')replies.push(p);if(kind==='discovery')scans.push(p);deliver(kind,p)};
await wait(()=>document.querySelector('[data-id="gemini-cli"]'));
const row=id=>document.querySelector('[data-id="'+id+'"]'),apply=()=>document.querySelector('#drawer-apply');
check('Local discovery available',row('windsurf')&&row('gemini-cli'));
check('Hermes aliases appear once',row('hermes')&&!row('hermes-desktop'));
check('Cloud service is separate',row('notion')?.textContent.includes('Cloud service'));
check('Leftover config labelled',row('windsurf')?.textContent.includes('Saved configuration found'));
row('gemini-cli').click();check('Unsupported tool cannot connect',!document.querySelector('[data-act="discover-add"]'));
check('Unsupported reason visible',document.querySelector('#insp').textContent.includes('No connector yet'));
const filter=value=>{const e=document.querySelector('#discovery-filter');e.value=value;e.dispatchEvent(new Event('change',{bubbles:true}));};
filter('unsupported');check('Unsupported filter',row('gemini-cli')&&!row('windsurf'));filter('all');
const search=document.querySelector('#discovery-search');search.value='HERmES';search.dispatchEvent(new Event('input',{bubbles:true}));
check('Search retains focus',document.activeElement.id==='discovery-search');check('Search filters tools',row('hermes')&&!row('windsurf'));
document.querySelector('#discovery-search').value='';document.querySelector('#discovery-search').dispatchEvent(new Event('input',{bubbles:true}));
row('windsurf').click();
if(PHASE==='flow'){
 document.querySelector('[data-act="remove-producer"]').click();check('Removal starts as preview',apply().disabled);
 await wait(()=>!apply().disabled);check('Removal has explicit apply',apply().textContent==='Remove producer');
 apply().click();await wait(()=>replies.length===2);await wait(()=>row('windsurf')?.textContent.includes('Removed'));
 document.querySelector('#drawer-close').click();row('windsurf').click();
 document.querySelector('[data-act="discover-add"]').click();await wait(()=>!apply().disabled);
 check('Reconnect has separate preview',apply().textContent==='Add producer');apply().click();await wait(()=>replies.length===4);
 await wait(()=>row('windsurf')?.textContent.includes('Connected'));check('Reconnect status refreshed',true);
 document.querySelector('#drawer-close').click();
}else{
 check('Status failure does not stop discovery',row('gemini-cli'));
 check('Unknown connection cannot mutate',!document.querySelector('[data-act="discover-add"]')&&!document.querySelector('[data-act="remove-producer"]'));
 check('Unknown status is explicit',document.querySelector('#insp').textContent.includes('Refresh the configured archive'));
}
const count=scans.length;document.querySelector('[data-act="scan-tools"]').click();
check('Scan shows progress',document.querySelector('[data-act="scan-tools"]').disabled);
await wait(()=>scans.length>count);check('Scan completes independently',!document.querySelector('[data-act="scan-tools"]').disabled);
window.sovDeliver('discovery',{request:'old-response',tools:[]});check('Old scan reply ignored',row('gemini-cli'));
check('No page overflow',document.documentElement.scrollWidth<=innerWidth);
check('No list overflow',document.querySelector('#rows').scrollWidth<=document.querySelector('#rows').clientWidth);
if(PHASE==='flow'){row('windsurf').click();check('Producer diagnostics accessible',document.querySelector('[data-act="producer-details"]'));document.querySelector('[data-act="producer-details"]').click();check('Producer details opens lane inspector',document.querySelector('#insp').textContent.includes('Read wire'));window.sovView('tools');}
row('windsurf').click();
post({cmd:'clientError',where:'discovery-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path);a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 with tempfile.TemporaryDirectory(prefix='sovereign-discovery-') as tmp:
  base=Path(tmp).resolve();archive=base/'Archive';brain_local.create(archive,ROOT)
  history=archive/'raw/tools/windsurf-qa/retained.md';history.parent.mkdir(parents=True);history.write_text('Owned history.');digest=hashlib.sha256(history.read_bytes()).hexdigest()
  home=base/'home';(home/'.codeium/windsurf').mkdir(parents=True);(home/'Applications/Hermes.app').mkdir(parents=True);(home/'.hermes').mkdir();(home/'.hermes/config.yaml').touch();(home/'bin').mkdir()
  cli=home/'bin/gemini';cli.write_text('#!/bin/sh\ntouch '+str(home/'executed'));cli.chmod(0o700)
  command=base/'producer';command.write_text(fixture.COMMAND);command.chmod(0o700)
  (base/'bin').mkdir()
  for h in ('windsurf','hermes','notion'):
   target=base/'connectors/harness'/h;target.mkdir(parents=True);(target/'harness.json').write_bytes((ROOT/'connectors/harness'/h/'harness.json').read_bytes())
  status=base/'bin/status';status.write_text('#!/bin/sh\nexec /bin/cat '+"'"+str(base/'status.json')+"'\n");status.chmod(0o700)
  for phase in ('flow','offline'):
   data={'generated_at':datetime.now(timezone.utc).isoformat(),'machine':{'host':'qa','vault':str(archive),'connected':True},'hub':{'via':'local','reachable':True,'pending':0},'needs_you':[],
    'harnesses':[{'id':'windsurf','name':'Windsurf','lane':'windsurf-qa','read':'instruction','state':'connected','declared':True,'job_loaded':True,'hook_registered':True,'detected':True}],
    'lanes':[{'lane':'windsurf-qa','host':'qa','producer':'Windsurf','read':'instruction','write':'mirror','vault_age_h':2}],'fleet':{'hosts':[]}}
   if phase=='offline':data={'error':'Fixture status unavailable','machine':{'connected':False}}
   (base/'status.json').write_text(json.dumps(data));(base/'calls.jsonl').write_text('')
   suite='com.sovereign.qa.discovery.'+uuid.uuid4().hex
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(status),SOV_QA_PRODUCER_COMMAND=str(command),SOV_QA_DISCOVERY_HOME=str(home),SOV_APPEARANCE='light' if phase=='flow' else 'dark',SOV_WINDOW='1000x700' if phase=='flow' else '720x460',SOV_SNAPSHOT=str(a.evidence/(phase+'.png')),SOV_SNAPSHOT_DELAY='2',SOV_SNAPSHOT_ANCHOR='operations:view:tools',SOV_QA_JS_AFTER_ANCHOR=PROBE.replace('PHASE',json.dumps(phase)))
   try:
    cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=45)
    (a.evidence/(phase+'.log')).write_text(cp.stderr)
    marker='client error in discovery-qa: ';r=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
    assert cp.returncode==0 and len(r)==1,(phase,cp.stderr);assert not r[0]['failures'],r
    calls=[json.loads(line) for line in (base/'calls.jsonl').read_text().splitlines()]
    assert len(calls)==(4 if phase=='flow' else 0),(phase,calls)
    assert sum('--apply' in c for c in calls)==(2 if phase=='flow' else 0)
    assert hashlib.sha256(history.read_bytes()).hexdigest()==digest
    assert not (home/'executed').exists()
    reports.append(dict(phase=phase,checks=r[0]['checks'],calls=calls));print(phase,len(r[0]['checks']),'checks passed',flush=True)
   finally:subprocess.run(['defaults','delete',suite],capture_output=True)
 (a.evidence/'native-discovery.json').write_text(json.dumps(reports,indent=2)+'\n')
if __name__=='__main__':main()
