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
// Bounded by the clock: a background window throttles timers, so a count of polls outlasts the snapshot watchdog and the failure goes unnamed.
const wait=async fn=>{for(const end=Date.now()+10000;Date.now()<end;await pause(50))if(fn())return;throw Error('Timed out: '+fn)};
const text=()=>document.body.textContent;
const caption=()=>document.getElementById('seen')?.title||document.getElementById('vmeta')?.title||'';
const needs=()=>document.querySelector('.today-needs');
const report=()=>post({cmd:'clientError',where:'transparency-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
PROBE=r'''
check('No horizontal overflow',document.documentElement.scrollWidth<=innerWidth);
if(SCENE==='job-output'){
 const folds=()=>[...needs().querySelectorAll('.today-detail')];
 check('Error details start collapsed',folds().length===2&&folds().every(d=>d.hidden));
 check('Both grouped failures are carried',needs().textContent.includes('kit transfer failed')&&needs().textContent.includes('archive push failed'));
 check('Local capture error is carried',needs().textContent.includes('guest archive failed'));
 needs().querySelector('.today-main').click();await pause(50);
 const open=needs().querySelector('.today-detail:not([hidden])');
 check('A detail opens under its row',!!open&&open.getBoundingClientRect().height>0);
 check('Diagnostic output is plain text',!needs().querySelector('img')&&needs().textContent.includes('<img'));
 check('Diagnostics wrap without overflow',document.documentElement.scrollWidth<=innerWidth);
}else if(SCENE.startsWith('recovery')){
 await wait(()=>!caption().includes('refreshing'));
 if(SCENE==='recovery-home'){
  const watching=document.querySelector('.today-waiting');
  check('Cleared blocker is outside attention',watching?.textContent.includes('autocommit')&&!needs()?.textContent.includes('autocommit'));
  check('Nothing waiting on the owner reads as clear',document.querySelector('.today-headline h2').textContent==='All clear');
  check('Waiting gives a clear state and action',watching?.textContent.includes('verifying')&&watching?.textContent.includes('Previous blocker cleared')&&watching?.textContent.includes('Jobs'));
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
 check('Receipt does not claim job is stopped',text().includes('only a completed receipt establishes the outcome'));
}else if(SCENE==='glance'){
 check('Compact menu is active',document.body.classList.contains('glance'));
 check('Menu keeps status rows without troubleshooting paragraphs',document.querySelector('.g-row.need')&&!document.querySelector('.issue-details'));
 check('Full console remains available',!!document.getElementById('g-console'));
}else if(SCENE==='concise-mixed'){
 const group=[...document.querySelectorAll('.today-item')].find(r=>r.textContent.includes('2 sources'));
 check('Mixed tools and hosts stay one row on Today',location.pathname.endsWith('/local.html')&&!!group&&document.querySelectorAll('.today-needs .today-item').length===1);
 check('Mixed group retains both destination types',group.textContent.includes('local-tool')&&group.textContent.includes('remote-tool on remote'));
 check('A mixed group lands on Sources',group.querySelector('.today-go').textContent.includes('Sources'));
}else if(SCENE==='concise-backups'){
 check('View backups opens Backups',location.pathname.endsWith('/index.html')&&document.querySelector('[data-view="backups"][aria-pressed="true"]'));
}else if(SCENE==='concise'){
 const rows=[...needs().querySelectorAll('.today-row')],folds=[...needs().querySelectorAll('.today-detail')];
 check('Three concise attention rows',rows.length===3&&needs().getBoundingClientRect().height<160);
 check('No diagnostic paragraphs shown by default',folds.length===2&&folds.every(d=>d.hidden));
 check('Short statuses and named actions',rows.some(r=>r.textContent.includes('autocommit')&&r.textContent.includes('failed')&&r.textContent.includes('Jobs'))&&rows.some(r=>r.textContent.includes('9 proposals')&&r.textContent.includes('Review'))&&rows.some(r=>r.textContent.includes('6 devices')&&r.textContent.includes('no backup')&&r.textContent.includes('Backups')));
 const item=()=>[...needs().querySelectorAll('.today-item')].find(r=>r.textContent.includes('autocommit'));
 item().querySelector('.today-main').click();await pause(50);
 const fold=item().querySelector('.today-detail');
 check('Details expand to observed result and guidance',!fold.hidden&&fold.textContent.includes('exited 1')&&fold.querySelector('p').getBoundingClientRect().height>0);
 check('Copy guidance is available only in details',fold.querySelector('button')?.textContent==='Copy next step');
 item().querySelector('.today-main').click();await pause(50);check('Details collapse again',item().querySelector('.today-detail').hidden);
}else if(SCENE==='first-load'){
 check('First load states native budget',caption().includes('up to 6 seconds'));
 check('No false empty environment',!text().includes('0 devices')&&!text().includes('No matching connector environment'));
 await wait(()=>text().includes('worker'));
 check('Slow first result renders',true);
 check('Elapsed status time shown',caption().includes('Status took'));
}else if(SCENE==='home'){
 check('Attention is first',document.getElementById('system-home').querySelector('.plain-list')===needs());
 check('Attention is above the figures',needs().getBoundingClientRect().top<document.querySelector('.today-tiles').getBoundingClientRect().top);
 check('Troubleshooting is collapsed by default',[...needs().querySelectorAll('.today-detail')].every(d=>d.hidden));
 needs().querySelector('.today-main').click();await pause(50);
 const disclosure=needs().querySelector('.today-detail:not([hidden])');
 check('Details open on request',!!disclosure&&disclosure.querySelector('p').getBoundingClientRect().height>0);
 for(const term of ['Tailscale SSH','within its 1 second','Refresh;'])check('Retains guidance '+term,needs().textContent.includes(term));
 check('Unknown contribution is not attention',!needs().textContent.includes('Hub acceptance is unknown')&&!needs().textContent.includes('older-service'));
 check('Link is an anchor',needs().querySelector('a')?.href==='https://example.com/recheck');
 check('Copy step is available',[...needs().querySelectorAll('button')].some(b=>b.textContent==='Copy next step'));
 check('Source text cannot inject HTML',!needs().querySelector('img'));
 const link=needs().querySelector('a');check('Link keyboard reachable',link.tabIndex===0);
 window.sovView('system');
 check('System has observed devices',text().includes('2 devices'));
 window.sovRefresh();await pause(150);
 check('Pending keeps devices',text().includes('2 devices')&&caption().includes('refreshing'));
 await wait(()=>!caption().includes('refreshing'));
 check('Failed refresh keeps devices',text().includes('2 devices')&&caption().includes('refresh failed'));
 check('Failed refresh gives next step',text().includes('Check the connection in Sources'));
 window.sovRefresh();await pause(150);check('Retry keeps devices',text().includes('2 devices'));
 await wait(()=>caption().includes('refresh failed'));
 check('Timeout names budget and probe',text().includes('status probe did not finish within 4 seconds'));
 check('Timeout retains last devices',text().includes('2 devices'));
 window.sovRefresh();await wait(()=>!caption().includes('refreshing'));
 check('Recovery clears failure',text().includes('2 devices')&&!caption().includes('refresh failed'));
}else if(SCENE==='to-operations'){
 check('Sources document loaded',location.pathname.endsWith('/index.html')&&document.getElementById('sources-tab').getAttribute('aria-pressed')==='true');
 check('Cached data survives document swap',text().includes('worker')&&caption().includes('refreshing'));
 await wait(()=>!caption().includes('refreshing'));
 check('New document receives in-flight result',!caption().includes('refresh failed')&&text().includes('worker'));
}else if(SCENE==='to-home'){
 check('Home document loaded',location.pathname.endsWith('/local.html'));
 check('Map route restored',document.getElementById('sources-tab').getAttribute('aria-pressed')==='true'&&!!document.querySelector('.sv'));
 check('Environment survives return navigation',text().includes('2 devices')&&caption().includes('refreshing'));
 await wait(()=>!caption().includes('refreshing'));
 check('Returning page receives pending result',text().includes('2 devices'));
}
report();
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path);p.add_argument('--scenes',nargs='*');a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);results=[]
 cases=[('job-output','light','720x460'),('job-output','dark','1200x800'),('recovery-home','dark','900x600'),('recovery-retry','light','720x460'),('recovery-cancel','dark','900x600'),('first-load','dark','900x600'),('home','dark','1200x800'),('home','light','720x460'),('to-operations','dark','900x600'),('to-home','light','900x600'),('hub-jobs','dark','900x600'),('hub-jobs','light','720x460')]+[('concise',theme,size) for theme in ('dark','light') for size in ('1200x800','720x460')]+[('concise-backups','light','900x600'),('concise-mixed','dark','900x600'),('glance','dark','420x600'),('glance','light','420x600')]
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
   if scene=='job-output':
    data['needs_you']=[{'kind':'job','text':'Capture last exited 0; recent error output remains.','why':'Skipped sources do not verify recovery.','action':'Verify a new capture.','verify':'Capture the available guest.','failure_output':'guest archive failed'}]
    data['fleet']={'hosts':[]};data['backups']={};data['hub']['pending']=0
    data['hub']['jobs']={j:{'ts':data['generated_at'],'exit':1,'health':{'why':'Captured output is shown below.','action':'Inspect the failed destination.','verify':'A new run succeeds.','failure_output':output}} for j,output in [('kit','kit transfer failed <img src=x onerror=alert(1)>'),('autocommit','archive push failed')]}
   if scene=='hub-jobs':data['hub']['jobs']={'autocommit':{'ts':data['generated_at'],'exit':1,'source':'hub-runner','schedule':'04:30 daily','cadence_s':86400},'nightly':{'ts':None,'exit':None,'source':'hub-runner','schedule':'06:00 daily','cadence_s':86400}}
   (base/'status.json').write_text(json.dumps(data));(base/'count').write_text('0')
   command=base/'status'
   # A single process fixture, so timeout cleanup can be checked by PID.
   behavior="time.sleep(4)" if scene=='first-load' else "\nif n==2: time.sleep(1); sys.exit(7)\nif n==3: time.sleep(9)" if scene=='home' else "\nif n==2: time.sleep(4)"
   command.write_text('#!'+sys.executable+'\nimport os,json,time,sys\nfrom pathlib import Path\nb=Path(__file__).parent\nn=int((b/"count").read_text())+1\n(b/"count").write_text(str(n))\n(b/"pid").write_text(str(os.getpid()))\n'+behavior+'\nprint((b/"status.json").read_text())\n');command.chmod(0o700)
   anchor='operations:view:jobs' if scene in ('hub-jobs','recovery-retry','recovery-cancel') else 'operations:view:hosts' if scene=='to-operations' else 'home:view:system' if scene=='to-home' else ''
   before="window.sovView('system');" if scene=='first-load' else "document.getElementById('sources-tab').click();" if scene=='to-home' else "window.sovRefresh();" if scene=='to-operations' else 'void 0'
   if scene=='concise-backups':before="(async()=>{for(let n=0;n<100;n++){const b=[...document.querySelectorAll('.today-needs .today-item')].find(b=>b.textContent.includes('no backup'));if(b){b.querySelector('.today-go').click();return}await new Promise(r=>setTimeout(r,50))}})();"
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
