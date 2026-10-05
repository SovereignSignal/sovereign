#!/usr/bin/env python3
"""Review navigation and stale-state safety in the real app, disposable archives only."""
import argparse,importlib.util,json,os,subprocess,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gate_fixture',HERE/'tests/test_gate_check.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
COMMON=r'''
const checks={},scene=SCENE,data=STATUS,post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
// Bounded by the clock: a background window throttles timers, so a count of polls outlasts the snapshot watchdog and the failure goes unnamed.
const wait=async fn=>{for(const end=Date.now()+10000;Date.now()<end;await pause(50))if(fn())return;throw Error('Timed out: '+fn)};
const check=(name,value)=>checks[name]=!!value;
const rows=()=>document.querySelectorAll('#rows [data-id^="p:"]');
const button=()=>document.querySelector('[data-act="gate"][data-verb="approve"]');
const deliver=d=>window.sovDeliver('status',d);
const copy=()=>JSON.parse(JSON.stringify(data));
const report=()=>post({cmd:'clientError',where:'review-qa',msg:JSON.stringify({scene,theme:document.documentElement.dataset.theme,width:innerWidth,checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
PROBE=r'''
check('Review primary page',location.pathname.endsWith('/index.html')&&document.body.classList.contains('review'));
check('Review selected',document.getElementById('review-tab').getAttribute('aria-pressed')==='true');
check('Sources still reachable',!!document.getElementById('sources-tab'));
check('Library deselected',document.getElementById('library-tab').getAttribute('aria-pressed')==='false');
check('One frame, no second navigation',!document.getElementById('switch')&&!document.querySelector('#controls .seg'));
check('Queue and proposal side by side',(()=>{const q=document.getElementById('listpane').getBoundingClientRect(),d=document.getElementById('inspector').getBoundingClientRect();return q.right<=d.left+1&&q.width>=180&&d.width>=300})());
check('Title and badge',document.getElementById('vault').textContent==='Review'&&document.getElementById('review-count').textContent==='1');
check('Readable queue',rows().length===1&&rows()[0].textContent.includes('A useful decision'));
check('No horizontal overflow',document.documentElement.scrollWidth<=innerWidth);
await wait(()=>button()&&!button().disabled);
check('Direct decision available',true);
const rect=button().getBoundingClientRect();
check('Decision button visible',rect.width>0&&rect.left>=0&&rect.right<=innerWidth&&rect.top>=0&&rect.bottom<=innerHeight);
check('Inspector exposed to accessibility',document.getElementById('inspector').getAttribute('aria-hidden')!=='true');
if(scene==='speed'){
 const handler=window.webkit.messageHandlers.sov,original=handler.postMessage.bind(handler),requests=[];
 handler.postMessage=m=>{
  if(['status','gate','gateCheck'].includes(m.cmd)){
   requests.push(m);
   if(m.cmd==='gateCheck')setTimeout(()=>window.sovDeliver('gateCheck',{slug:m.slug,request:m.request,state:'ready',fingerprint:'a'.repeat(64)}),0);
  }else original(m);
 };
 const queue=copy();queue.hub.proposals=Array.from({length:45},(_,i)=>({...data.hub.proposals[0],slug:'speed-'+i,title:'Proposal '+i}));queue.hub.pending=45;
 deliver(JSON.parse(JSON.stringify(queue)));rows()[10].click();await wait(()=>button()&&!button().disabled);
 const list=document.getElementById('rows');list.scrollTop=400;
 const survivor=rows()[20],scroll=list.scrollTop;
 const decide=async state=>{
  await wait(()=>button()&&!button().disabled);
  const action=state==='rejected'?document.querySelector('[data-act="gate"][data-verb="reject"]'):button();
  const before=requests.filter(m=>m.cmd==='gate').length;
  action.click();if(state==='rejected')action.click();
  check('Decision sent '+before,requests.filter(m=>m.cmd==='gate').length===before+1);
  const request=requests.filter(m=>m.cmd==='gate').at(-1);
  const start=performance.now();window.sovDeliver('gateResult',{...request,state});
  return {request,ms:performance.now()-start};
 };
 const approved=await decide('approved');
 check('Only completed row removed',rows().length===44&&!list.querySelector('[data-id="p:speed-10"]'));
 check('List nodes and scroll retained',survivor===list.querySelector('[data-id="p:speed-20"]')&&list.scrollTop===scroll);
 check('Next proposal selected',list.querySelector('[aria-selected="true"]').dataset.id==='p:speed-11');
 check('Queue count updated',document.getElementById('review-count').textContent==='44');
 check('No full status request',!requests.some(m=>m.cmd==='status'));
 check('Receipt handled within 100ms',approved.ms<100);
 window.sovDeliver('gateResult',{...approved.request,state:'approved'});
 check('Duplicate reply ignored',rows().length===44);
 await decide('rejected');await decide('sync_pending');
 check('Rapid decisions advance',rows().length===42&&list.querySelector('[aria-selected="true"]').dataset.id==='p:speed-13');
 check('Sync warning visible',!!document.querySelector('#gate-notice.sync_pending'));
 const failed=await decide('failed');
 check('Failure stays selected without retry',rows().length===42&&button().disabled&&!!document.querySelector('#insp .failed'));
 document.querySelector('[data-act="gate-check"]').click();
 await decide('uncertain');
 check('Uncertain result stays blocked',rows().length===42&&button().disabled&&!!document.querySelector('#insp .uncertain'));
 check('Decisions never request status',!requests.some(m=>m.cmd==='status'));
 deliver(JSON.parse(JSON.stringify(queue)));
 check('Older status cannot restore completed rows',rows().length===42&&!list.querySelector('[data-id="p:speed-10"]')&&!list.querySelector('[data-id="p:speed-11"]')&&!list.querySelector('[data-id="p:speed-12"]'));
 const changed=JSON.parse(JSON.stringify(queue));changed.hub.proposals[10].body='A new revision';deliver(changed);
 check('New proposal revision can return',!!list.querySelector('[data-id="p:speed-10"]'));
 const single=copy();single.hub.proposals=[{...data.hub.proposals[0],slug:'last'}];single.hub.pending=1;deliver(single);rows()[0].click();
 await decide('approved');
 check('Final receipt gives empty queue',rows().length===0&&document.getElementById('review-intro').textContent.includes('caught up')&&!button());
 check('Empty queue needs no reload',!requests.some(m=>m.cmd==='status'));
 single.hub.proposals=[{...data.hub.proposals[0],slug:'page-end'}];single.hub.pending=3;deliver(single);rows()[0].click();await decide('rejected');
 check('Exhausted partial queue loads more',requests.filter(m=>m.cmd==='status').length===1&&document.getElementById('review-intro').textContent.includes('waiting to load'));
 handler.postMessage=original;
}
if(scene==='layout'){
 // Reproduce a long proposal after the previous decision left a receipt banner.
 const notice=document.getElementById('gate-notice');notice.hidden=false;notice.className='gate-feedback approved';
 notice.innerHTML='<strong>Previous proposal · Approved</strong><p>The card is now in your trusted archive.</p><button>Refresh queue</button><button>Dismiss</button>';
 const inspector=document.getElementById('inspector');
 check('Approve, Reject and Open source are all present',['Approve','Reject','Open source'].every(label=>[...inspector.querySelectorAll('.acts button')].some(b=>b.textContent.trim()===label)));
 const visibleActions=()=>{
  const bounds=inspector.getBoundingClientRect();
  return [...inspector.querySelectorAll('.acts button')].every(b=>{
   const r=b.getBoundingClientRect();
   return r.width>0&&r.top>=bounds.top&&r.bottom<=Math.min(bounds.bottom,innerHeight)&&r.left>=bounds.left&&r.right<=bounds.right&&
    [r.top+2,r.bottom-2].every(y=>b.contains(document.elementFromPoint(r.left+r.width/2,y)));
  });
 };
 for(const position of [0,.5,1]){
  inspector.scrollTop=(inspector.scrollHeight-inspector.clientHeight)*position;await pause(100);
  check('All actions fully visible and hittable at scroll '+position,visibleActions());
 }
 notice.hidden=true;inspector.scrollTop=0;await pause(100);
 check('Actions remain visible after dismissing receipt',visibleActions());
 notice.hidden=false;await pause(100);
}
if(scene==='states'){
 const receive=window.sovDeliver;let checkedAway=false;window.sovDeliver=(kind,payload)=>{if(kind==='gateCheck')checkedAway=true;receive(kind,payload)};
 document.querySelector('[data-act="gate-check"]').click();document.getElementById('library-tab').click();await wait(()=>checkedAway);window.sovDeliver=receive;document.getElementById('review-tab').click();await wait(()=>button()&&!button().disabled);
 check('Returning during a check stays usable',true);
 const stale=button();
 deliver({error:'Offline fixture'});
 check('Error removes cached decisions',rows().length===0&&!button()&&document.getElementById('review-intro').textContent.includes('unavailable'));
 stale.click();check('Detached action cannot submit',!document.querySelector('#gate-notice.running'));
 window.sovBack();check('History cannot revive a cached proposal',!button());
 document.getElementById('review-tab').click();
 let d=copy();d.machine.vault='/another-archive';deliver(d);
 check('Other archive isolated',rows().length===0&&!button()&&document.getElementById('review-count').textContent==='');
 d=copy();d.hub.reachable=false;deliver(d);
 check('Offline is not empty',rows().length===0&&document.getElementById('review-intro').textContent.includes('unverified'));
 d=copy();delete d.hub.proposals;deliver(d);
 check('Missing list is not empty',rows().length===0&&document.getElementById('review-intro').textContent.includes('not fully reported'));
 d=copy();d.hub.pending=90;deliver(d);
 check('Partial count explained',rows().length===1&&document.getElementById('review-intro').textContent.includes('Showing 1 of 90'));
 d=copy();d.hub.pending=0;d.hub.proposals=[];deliver(d);
 check('Verified empty queue',document.getElementById('review-intro').textContent.includes('caught up')&&!button());
 check('Empty detail gives no impossible instruction',document.getElementById('insp').textContent.includes('No proposal is available to inspect.'));
 deliver({machine:{connected:false}});check('Local only is not empty',document.getElementById('review-intro').textContent.includes('not connected'));
 deliver(copy());document.getElementById('library-tab').click();
 check('Library keeps archive statistics',!!document.querySelector('.dash'));
 check('Library has no second queue',rows().length===0&&!button());
 document.getElementById('review-tab').click();await wait(()=>button()&&!button().disabled);
 check('Recovered queue rechecked',rows().length===1);
 document.getElementById('rows').focus();document.getElementById('rows').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
 check('Keyboard selection',!!document.getElementById('rows').getAttribute('aria-activedescendant'));
}
report();
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path);p.add_argument('--scenes',nargs='*');a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 cases=[('home','dark','1200x800'),('system','light','900x600'),('menu','dark','720x460'),('states','dark','1200x800'),('states','light','720x460'),('speed','dark','1200x800'),('speed','light','720x460')]+[('layout',theme,size) for theme in ('light','dark') for size in ('1210x890','1100x600','1099x600','900x600','720x460')]
 for scene,theme,size in cases:
  if a.scenes and scene not in a.scenes:continue
  t=fixture.GateCheckTests();t.setUp();suite='com.sovereign.qa.review.'+uuid.uuid4().hex
  try:
   command=t.setup_real_gate();home=t.base;(home/'.brain-root').write_text(str(t.root));(home/'.curator-lane').write_text('curator');(home/'brain-bin').mkdir();(home/'brain-bin/sov').write_bytes(command.read_bytes());(home/'brain-bin/sov').chmod(0o700)
   if scene=='layout':t.card(t.proposals/(t.slug+'.md'),body=('A long proposal must keep every decision button reachable while the card and inspector scroll.\n\n'*60))
   prop={'slug':t.slug,'title':'A useful decision','type':'entity','body':'Reviewed content','source':'owner','confidence':'high','age_h':1}
   data={'machine':{'connected':True,'host':'Review QA','vault':str(t.root),'vault_name':'Review QA'},'hub':{'reachable':True,'via':'local','pending':1,'proposals':[prop]},'archive':{'total':1,'by_type':{'concept':1},'cards':[]},'needs_you':[{'kind':'gate','text':'One proposal. Approve on Telegram.'}]}
   if scene=='layout':data['obsidian']={'vault_name':'Review QA'}
   status=home/'status';status.write_text('#!/bin/sh\ncat <<\'DATA\'\n'+json.dumps(data)+'\nDATA\n');status.chmod(0o700)
   before=(t.proposals/(t.slug+'.md')).read_bytes()
   first="document.getElementById('review-tab').click();"
   if scene=='system':first="window.sovView('system');"+first
   if scene=='menu':first="window.webkit.messageHandlers.sov.postMessage({cmd:'showConsole',place:{view:'review'}});"
   name=scene+'-'+theme+'-'+size
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_GATE_HOME=str(home),SOV_QA_STATUS_COMMAND=str(status),SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(a.evidence/(name+'.png')),SOV_SNAPSHOT_DELAY='7',SOV_SNAPSHOT_ANCHOR='',SOV_QA_JS=first,SOV_QA_JS_AFTER_ANCHOR=COMMON.replace('SCENE',json.dumps(scene)).replace('STATUS',json.dumps(data))+PROBE)
   cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(t.root)],env=env,capture_output=True,text=True,timeout=45)
   (a.evidence/(name+'.log')).write_text(cp.stderr);marker='client error in review-qa: ';result=[json.loads(x.split(marker,1)[1]) for x in cp.stderr.splitlines() if marker in x]
   assert cp.returncode==0 and len(result)==1,(scene,cp.stderr)
   reports.extend(result);assert not result[0]['failures'],result[0]
   assert before==(t.proposals/(t.slug+'.md')).read_bytes(),'Read-only workflow wrote proposal'
   print(name,len(result[0]['checks']),'checks passed',flush=True)
  finally:
   t.tearDown();subprocess.run(['defaults','delete',suite],capture_output=True)
   (a.evidence/'review-native.json').write_text(json.dumps(reports,indent=2)+'\n')
 print(sum(len(r['checks']) for r in reports),'Review checks passed')
if __name__=='__main__':main()
