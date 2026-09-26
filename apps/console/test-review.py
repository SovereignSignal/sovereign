#!/usr/bin/env python3
"""Review navigation and stale-state safety in the real app, disposable archives only."""
import argparse,importlib.util,json,os,subprocess,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gate_fixture',HERE/'tests/test_gate_check.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
COMMON=r'''
const checks={},scene=SCENE,data=STATUS,post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async fn=>{for(let i=0;i<150;i++){if(fn())return;await pause(50)}throw Error('Timed out: '+fn)};
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
check('System still reachable',!!document.getElementById('system-tab'));
check('Operations deselected',document.getElementById('operations-tab').getAttribute('aria-pressed')==='false');
check('Operations subtabs hidden',getComputedStyle(document.querySelector('#switch .seg')).display==='none');
check('Title and badge',document.getElementById('vault').textContent==='Review'&&document.getElementById('review-count').textContent==='1');
check('Readable queue',rows().length===1&&rows()[0].textContent.includes('A useful decision'));
check('No horizontal overflow',document.documentElement.scrollWidth<=innerWidth);
await wait(()=>button()&&!button().disabled);
check('Direct decision available',true);
const rect=button().getBoundingClientRect();
check('Decision button visible',rect.width>0&&rect.left>=0&&rect.right<=innerWidth&&rect.top>=0&&rect.bottom<=innerHeight);
check('Inspector exposed to accessibility',document.getElementById('inspector').getAttribute('aria-hidden')!=='true');
if(scene==='layout'){
 // Reproduce a long proposal after the previous decision left a receipt banner.
 const notice=document.getElementById('gate-notice');notice.hidden=false;notice.className='gate-feedback approved';
 notice.innerHTML='<strong>Previous proposal · Approved</strong><p>The card is now in your trusted archive.</p><button>Refresh queue</button><button>Dismiss</button>';
 const inspector=document.getElementById('inspector');
 check('Approve, Reject and Open source are all present',['Approve','Reject','Open source'].every(label=>[...inspector.querySelectorAll('.acts button')].some(b=>b.textContent.trim()===label)));
 const visibleActions=()=>{
  const bounds=inspector.getBoundingClientRect(),footer=document.getElementById('switch').getBoundingClientRect();
  return [...inspector.querySelectorAll('.acts button')].every(b=>{
   const r=b.getBoundingClientRect();
   return r.width>0&&r.top>=bounds.top&&r.bottom<=Math.min(bounds.bottom,footer.top)&&r.left>=bounds.left&&r.right<=bounds.right&&
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
 document.querySelector('[data-act="gate-check"]').click();document.getElementById('operations-tab').click();await wait(()=>checkedAway);window.sovDeliver=receive;document.getElementById('review-tab').click();await wait(()=>button()&&!button().disabled);
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
 deliver(copy());document.getElementById('operations-tab').click();window.sovView('archive');
 check('Operations keeps archive statistics',!!document.querySelector('.dash'));
 check('Operations has no second queue',rows().length===0&&!button());
 document.getElementById('review-tab').click();await wait(()=>button()&&!button().disabled);
 check('Recovered queue rechecked',rows().length===1);
 document.getElementById('rows').focus();document.getElementById('rows').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
 check('Keyboard selection',!!document.getElementById('rows').getAttribute('aria-activedescendant'));
}
report();
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path);p.add_argument('--scenes',nargs='*');a=p.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 cases=[('home','dark','1200x800'),('system','light','900x600'),('menu','dark','720x460'),('states','dark','1200x800'),('states','light','720x460')]+[('layout',theme,size) for theme in ('light','dark') for size in ('1210x890','1100x600','1099x600','900x600','720x460')]
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
   if scene=='system':first="document.getElementById('system-tab').click();"+first
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
