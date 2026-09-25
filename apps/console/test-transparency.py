#!/usr/bin/env python3
"""Status continuity and failure paths in the native app; fixture commands only."""
import argparse, importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile, uuid
from pathlib import Path
from datetime import datetime, timezone
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local
loader=importlib.machinery.SourceFileLoader('status_fixture',str(ROOT/'bin/sov-status'))
service=importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name,loader));loader.exec_module(service)
COMMON=r'''
const checks={},post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
const check=(name,ok)=>{checks[name]=!!ok};
const wait=async fn=>{for(let n=0;n<160;n++){if(fn())return;await pause(50)}throw Error('Timed out: '+fn)};
const text=()=>document.body.textContent;
const caption=()=>document.querySelector('.home-observation')?.textContent||document.getElementById('vmeta')?.textContent||'';
const report=()=>post({cmd:'clientError',where:'transparency-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
PROBE=r'''
check('No horizontal overflow',document.documentElement.scrollWidth<=innerWidth);
if(SCENE.startsWith('recovery')){
 await wait(()=>!caption().includes('refreshing'));
 if(SCENE==='recovery-home'){
  check('Cleared blocker is outside attention',document.querySelector('.home-waiting')?.textContent.includes('autocommit')&&!document.querySelector('.home-attention')?.textContent.includes('autocommit'));
  check('Waiting gives a clear state and action',document.querySelector('.home-waiting')?.textContent.includes('Previous blocker cleared')&&document.querySelector('.home-waiting')?.textContent.includes('View job'));
 }else{
  await wait(()=>document.querySelector('[data-id="hub:job:autocommit"]'));
  const item=document.querySelector('[data-id="hub:job:autocommit"]');item.click();await pause(100);
  check('Recovery is calm and explicit',item.textContent.includes('Awaiting verification')&&!item.querySelector('.down'));
  check('Failure remains inspectable',document.getElementById('insp').textContent.includes('View failure details'));
  check('Failure text cannot inject HTML',!document.getElementById('insp').querySelector('img'));
  const button=document.querySelector('[data-act="retry-backup"]');check('Backup action available',button&&!button.disabled);
  const bounds=button.getBoundingClientRect();check('Backup action visible without scrolling',bounds.top>=0&&bounds.bottom<innerHeight-30);
  button.click();await wait(()=>!document.querySelector('[data-act="retry-backup"]')?.disabled);
  check('Retry has honest outcome',document.getElementById('insp').textContent.includes(SCENE==='recovery-cancel'?'Cancelled. No backup was started.':'Request accepted; success is not yet verified.'));
 }
}else if(SCENE==='hub-jobs'){
 await wait(()=>document.querySelector('[data-id="hub:job:autocommit"]'));
 const commit=document.querySelector('[data-id="hub:job:autocommit"]'),nightly=document.querySelector('[data-id="hub:job:nightly"]');
 check('Current hub failure is visible',commit.textContent.includes('Needs attention'));
 check('Never completed nightly is unknown',nightly.textContent.toLowerCase().includes('unknown')&&nightly.textContent.includes('No completed run recorded'));
 check('No null exit or retired job shown',!text().includes('exit null')&&!document.querySelector('[data-id="hub:job:vault-autocommit"]'));
 nightly.click();await pause(100);
 check('Drawer names actual schedule',text().includes('06:00 daily'));
 check('Receipt does not claim job is stopped',text().includes('a job may currently be running'));
}else if(SCENE==='glance'){
 check('Compact menu is active',document.body.classList.contains('glance'));
 check('Menu keeps status rows without troubleshooting paragraphs',document.querySelector('.g-row.need')&&!document.querySelector('.issue-details'));
 check('Full console remains available',!!document.getElementById('g-console'));
}else if(SCENE==='concise-mixed'){
 check('Mixed tools and hosts open Operations overview',location.pathname.endsWith('/index.html')&&document.querySelector('.glance-home')&&document.getElementById('operations-tab').getAttribute('aria-pressed')==='true');
 document.querySelector('[data-group="mirror-late"]').click();await pause(50);
 check('Mixed group retains both destination types',document.getElementById('insp').textContent.includes('local-tool')&&document.getElementById('insp').textContent.includes('remote-tool on remote'));
}else if(SCENE==='concise-backups'){
 check('View backups opens Backups',location.pathname.endsWith('/index.html')&&document.querySelector('[data-view="backups"][aria-pressed="true"]'));
}else if(SCENE==='concise'){
 const panel=document.querySelector('.home-attention'),rows=[...panel.querySelectorAll('.home-row')],folds=[...panel.querySelectorAll('details')];
 check('Three concise attention rows',rows.length===3&&panel.getBoundingClientRect().height<320);
 check('No diagnostic paragraphs shown by default',folds.length===2&&folds.every(d=>!d.open&&d.getBoundingClientRect().height<45)&&[...panel.querySelectorAll('details p')].every(p=>{const r=p.getBoundingClientRect();return !p.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))}));
 check('Short statuses and named actions',rows.some(r=>r.textContent.includes('autocommit failed')&&r.textContent.includes('View job'))&&rows.some(r=>r.textContent.includes('9 proposals')&&r.textContent.includes('Review'))&&rows.some(r=>r.textContent.includes('6 machines: no backup recorded')&&r.textContent.includes('View backups')));
 const fold=folds[0];fold.querySelector('summary').click();await pause(50);
 check('Details expand to observed result and guidance',fold.open&&fold.textContent.includes('exited 1')&&fold.querySelector('p').getBoundingClientRect().height>0);
 check('Copy guidance is available only in details',fold.querySelector('button')?.textContent==='Copy next step');
 fold.querySelector('summary').click();check('Details collapse again',!fold.open);
}else if(SCENE==='first-load'){
 check('First load states native budget',caption().includes('up to 6 seconds'));
 check('No false empty environment',!text().includes('0 devices')&&!text().includes('No matching connector environment'));
 await wait(()=>text().includes('worker'));
 check('Slow first result renders',true);
 check('Elapsed status time shown',caption().includes('Status took'));
}else if(SCENE==='home'){
 const attention=document.querySelector('.home-attention'),grid=document.querySelector('.home-grid');
 check('Attention is first in DOM',grid.firstElementChild===attention);
 check('Attention is above receipts',attention.getBoundingClientRect().top<document.querySelector('.home-packs').getBoundingClientRect().top);
 check('Troubleshooting is collapsed by default',[...attention.querySelectorAll('details')].every(d=>!d.open));
 const disclosure=attention.querySelector('details');disclosure.querySelector('summary').click();await pause(50);
 check('Details open on request',disclosure.open&&disclosure.querySelector('p').getBoundingClientRect().height>0);
 for(const term of ['Tailscale SSH','within its 1 second','Refresh;'])check('Retains guidance '+term,attention.textContent.includes(term));
 check('Unknown contribution explained without alarm',document.querySelector('.home-contributions').textContent.includes('Hub acceptance is unknown')&&!attention.textContent.includes('Hub acceptance is unknown'));
 check('Link is an anchor',attention.querySelector('a')?.href==='https://example.com/recheck');
 check('Copy step is available',[...attention.querySelectorAll('button')].some(b=>b.textContent==='Copy next step'));
 check('Source text cannot inject HTML',!attention.querySelector('img'));
 const link=attention.querySelector('a');check('Link keyboard reachable',link.tabIndex===0);
 document.getElementById('system-tab').click();
 check('System has observed devices',text().includes('2 devices'));
 window.sovRefresh();await pause(150);
 check('Pending keeps devices',text().includes('2 devices')&&caption().includes('refreshing'));
 await wait(()=>!caption().includes('refreshing'));
 check('Failed refresh keeps devices',text().includes('2 devices')&&caption().includes('refresh failed'));
 check('Failed refresh gives next step',text().includes('Check the connection in Operations'));
 window.sovRefresh();await pause(150);check('Retry keeps devices',text().includes('2 devices'));
 await wait(()=>caption().includes('refresh failed'));
 check('Timeout names budget and probe',text().includes('status probe did not finish within 4 seconds'));
 check('Timeout retains last devices',text().includes('2 devices'));
 window.sovRefresh();await wait(()=>!caption().includes('refreshing'));
 check('Recovery clears failure',text().includes('2 devices')&&!caption().includes('refresh failed'));
}else if(SCENE==='to-operations'){
 check('Operations document loaded',location.pathname.endsWith('/index.html'));
 check('Cached data survives document swap',text().includes('worker')&&caption().includes('refreshing'));
 const disclosure=document.querySelector('.issue-details');check('Operations details are collapsed',disclosure&&!disclosure.open);
 disclosure.querySelector('summary').click();await pause(50);
 check('Operations retains troubleshooting on demand',disclosure.open&&disclosure.querySelector('p').getBoundingClientRect().height>0&&disclosure.textContent.includes('Refresh;'));
 await wait(()=>!caption().includes('refreshing'));
 check('New document receives in-flight result',!caption().includes('refresh failed')&&text().includes('worker'));
}else if(SCENE==='to-home'){
 check('Home document loaded',location.pathname.endsWith('/local.html'));
 check('System route restored',document.getElementById('system-tab').getAttribute('aria-pressed')==='true');
 check('Environment survives return navigation',text().includes('2 devices')&&caption().includes('refreshing'));
 await wait(()=>!caption().includes('refreshing'));
 check('Returning page receives pending result',text().includes('2 devices'));
}
report();
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path);p.add_argument('--scenes',nargs='*');a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);results=[]
 cases=[('recovery-home','dark','900x600'),('recovery-retry','light','720x460'),('recovery-cancel','dark','900x600'),('first-load','dark','900x600'),('home','dark','1200x800'),('home','light','720x460'),('to-operations','dark','900x600'),('to-home','light','900x600'),('hub-jobs','dark','900x600'),('hub-jobs','light','720x460')]+[('concise',theme,size) for theme in ('dark','light') for size in ('1200x800','720x460')]+[('concise-backups','light','900x600'),('concise-mixed','dark','900x600'),('glance','dark','420x600'),('glance','light','420x600')]
 for scene,theme,size in cases:
  if a.scenes and scene not in a.scenes:continue
  with tempfile.TemporaryDirectory(prefix='sovereign-transparency-') as folder:
   base=Path(folder);archive=base/'QA Archive';brain_local.create(archive,ROOT);archive=archive.resolve();suite='com.sovereign.qa.transparency.'+uuid.uuid4().hex
   fleet={'hosts':[{'host':'studio','net':{'online':True}},{'host':'worker','net':{'online':False,'via':'port 22 probe'}}]}
   backups={'lanes':[{'lane':'older-service'},{'lane':'waiting','delivery':'waiting'}],'hosts':[{'host':'worker','node':'hypervisor','reachable':False,'detail':{'why':'tailscale-check','action':'Run ssh hypervisor and open the link it prints.','url':'https://example.com/recheck'}}]}
   service.contribution_issues(backups)
   needs=service.hypervisor_needs(backups)+service.fleet_needs(fleet)
   needs[0]['why']+=' <img src=x onerror=alert(1)>'
   data={'generated_at':datetime.now(timezone.utc).isoformat(),'machine':{'connected':True,'host':'studio','vault':str(archive),'vault_name':'QA Archive'},'hub':{'reachable':True,'pending':0,'proposals':[]},'fleet':fleet,'backups':backups,'needs_you':needs,'harnesses':[],'archive':{'cards':[]}}
   if scene.startswith('concise'):
    data.update(fleet={'hosts':[]},needs_you=[{'kind':'gate','text':'9 proposals waiting.'}],backups={'hosts':[{'host':'worker-'+str(n),'node':'hypervisor','reachable':True,'inventory_complete':True,'scheduled':True,'last_dump_age_h':None,'jobs':1} for n in range(6)]})
    data['hub'].update(pending=9,proposals=[{'slug':'proposal-'+str(n),'title':'Proposal '+str(n),'type':'concept'} for n in range(9)],jobs={'autocommit':{'ts':data['generated_at'],'exit':1,'cadence_s':86400}})
   if scene=='concise-mixed':
    data.update(needs_you=[],backups={},hub={'reachable':True,'pending':0,'proposals':[]},harnesses=[{'id':'local-tool','name':'local-tool','state':'connected','run_age_h':10,'cadence_s':3600}],fleet={'hosts':[{'host':'remote','net':{'online':True},'harnesses':[{'harness':'remote-tool','run_age_h':10}]}]})
   if scene.startswith('recovery'):
    data.update(fleet={'hosts':[]},needs_you=[],backups={})
    data['hub']['jobs']={'autocommit':{'ts':data['generated_at'],'exit':1,'source':'hub-runner','schedule':'04:30 daily','cadence_s':86400,'health':{'state':'awaiting_verification','summary':'Previous blocker cleared; awaiting backup','checked_at':datetime.now().timestamp(),'verification_deadline':datetime.now().timestamp()+3600,'next_due':datetime.now().timestamp()+2700,'why':'The rejected files now pass. A successful backup is still unverified.','action':'Run backup now, or wait for the scheduled run.','verify':'A new completed run must succeed.','failure_output':'SECRET SCAN FAILED <img src=x onerror=alert(1)>','retry_supported':True}}}
   if scene=='hub-jobs':data['hub']['jobs']={'autocommit':{'ts':data['generated_at'],'exit':1,'source':'hub-runner','schedule':'04:30 daily','cadence_s':86400},'nightly':{'ts':None,'exit':None,'source':'hub-runner','schedule':'06:00 daily','cadence_s':86400}}
   (base/'status.json').write_text(json.dumps(data));(base/'count').write_text('0')
   command=base/'status'
   # A single process fixture, so timeout cleanup can be checked by PID.
   behavior="time.sleep(4)" if scene=='first-load' else "\nif n==2: time.sleep(1); sys.exit(7)\nif n==3: time.sleep(9)" if scene=='home' else "\nif n==2: time.sleep(4)"
   command.write_text('#!'+sys.executable+'\nimport os,json,time,sys\nfrom pathlib import Path\nb=Path(__file__).parent\nn=int((b/"count").read_text())+1\n(b/"count").write_text(str(n))\n(b/"pid").write_text(str(os.getpid()))\n'+behavior+'\nprint((b/"status.json").read_text())\n');command.chmod(0o700)
   anchor='operations:view:jobs' if scene in ('hub-jobs','recovery-retry','recovery-cancel') else 'operations:view:glance' if scene=='to-operations' else 'home:view:system' if scene=='to-home' else ''
   before="document.getElementById('system-tab').click();" if scene=='first-load' else "document.getElementById('operations-tab').click();" if scene=='to-home' else "window.sovRefresh();" if scene=='to-operations' else 'void 0'
   if scene=='concise-backups':before="(async()=>{for(let n=0;n<100;n++){const b=[...document.querySelectorAll('.home-attention .home-row')].find(b=>b.textContent.includes('View backups'));if(b){b.click();return}await new Promise(r=>setTimeout(r,50))}})();"
   if scene=='concise-mixed':before="(async()=>{for(let n=0;n<100;n++){const b=[...document.querySelectorAll('.home-attention .home-row')].find(b=>b.textContent.includes('Open details'));if(b){b.click();return}await new Promise(r=>setTimeout(r,50))}})();"
   name=scene+'-'+theme+'-'+size
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(command),SOV_QA_STATUS_BUDGET='6' if scene!='home' else '4',SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(a.evidence/(name+'.png')),SOV_SNAPSHOT_DELAY='3.2',SOV_SNAPSHOT_ANCHOR=anchor,SOV_QA_JS=before,SOV_QA_JS_AFTER_ANCHOR=COMMON+PROBE.replace('SCENE',json.dumps(scene)))
   if scene.startswith('recovery'):
    backup=base/'backup-fixture';backup.write_text('#!'+sys.executable+'\nimport json,sys\nfrom pathlib import Path\np=Path(__file__).with_suffix(".calls")\nwith p.open("a") as f:f.write("apply" if "--apply" in sys.argv else "preview");f.write("\\n")\nprint(json.dumps({"state":"requested" if "--apply" in sys.argv else "preview","token":"fixture","summary":"Fixture backup","verification":"Request accepted; success is not yet verified."}))\n');backup.chmod(0o700)
    env['SOV_QA_BACKUP_COMMAND']=str(backup);env['SOV_QA_BACKUP_CONFIRM']='1' if scene=='recovery-retry' else '0'
   if scene=='glance':env['SOV_GLANCE']='1'
   try:
    cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=35)
    (a.evidence/(name+'.log')).write_text(cp.stderr);marker='client error in transparency-qa: '
    records=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
    assert cp.returncode==0 and len(records)==1,(name,cp.stderr)
    result=dict(records[0],scene=scene,theme=theme,size=size,invocations=int((base/'count').read_text()));results.append(result)
    assert not result['failures'],result
    if scene in ('recovery-retry','recovery-cancel'):
     assert backup.with_suffix('.calls').read_text().splitlines()==(['preview','apply'] if scene=='recovery-retry' else ['preview'])

    if scene in ('to-home','to-operations'):assert result['invocations']==2,('navigation duplicated a probe',result)
    print(name,len(result['checks']),'checks passed',flush=True)
   finally:
    subprocess.run(['defaults','delete',suite],capture_output=True)
    (a.evidence/'native-transparency.json').write_text(json.dumps(results,indent=2)+'\n')
 print(sum(len(r['checks']) for r in results),'native transparency checks passed')
if __name__=='__main__':main()
