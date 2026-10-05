#!/usr/bin/env python3
"""Native appearance and Operations coverage; fixtures and a separate defaults suite only."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
sys.path.insert(0,str(REPO/'lib'));import brain_local
spec=importlib.util.spec_from_file_location('gate_fixture',HERE/'tests/test_gate_check.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
COMMON=r'''
const checks={},pause=ms=>new Promise(r=>setTimeout(r,ms));
// Bounded by the clock: a background window throttles timers, so a count of polls outlasts the snapshot watchdog and the failure goes unnamed.
const wait=async fn=>{for(const end=Date.now()+10000;Date.now()<end;await pause(50))if(fn())return;throw Error('Timed out: '+fn)};
const post=o=>window.webkit.messageHandlers.sov.postMessage(o);
const check=(name,ok)=>{checks[name]=!!ok};
const change=async value=>{post({cmd:'appearance',value});await wait(()=>document.documentElement.dataset.theme===value);await pause(80)};
const report=()=>post({cmd:'clientError',where:'appearance-qa',msg:JSON.stringify({scene:SCENE,theme:document.documentElement.dataset.theme,width:innerWidth,checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''
HOME=r'''
await wait(()=>!document.getElementById('system-home').hidden);
check('fresh install follows System',!document.documentElement.dataset.theme || ['dark','light'].includes(document.documentElement.dataset.theme));
post({cmd:'qaAppearance',openGlance:true});
const home=document.getElementById('system-home');
for(const theme of ['light','dark']){await change(theme);check(theme+' Home DOM preserved',home===document.getElementById('system-home'));post({cmd:'qaAppearance'});await pause(350)}
post({cmd:'appearance',value:'invalid'});await pause(150);check('invalid appearance ignored',document.documentElement.dataset.theme==='dark');
post({cmd:'appearance',value:'system'});await pause(200);post({cmd:'qaAppearance'});await pause(350);
for(const theme of ['light','dark']){post({cmd:'qaAppearance',systemTheme:theme});await wait(()=>document.documentElement.dataset.theme===theme);check('System observes '+theme,true)}
await change('light');report();
'''
PERSIST=r'''
await wait(()=>typeof window.sovView==='function');check('Light persisted across relaunch',document.documentElement.dataset.theme==='light');
const inherited=window.sovDeliver;window.sovDeliver=(kind,data)=>{if(kind==='settings')check('saved preference read on launch',data.appearance==='light');inherited(kind,data)};
post({cmd:'settings'});await pause(300);report();
'''
OPS=r'''
await wait(()=>window.sovSnapshotReady());
const errors=[];window.addEventListener('error',e=>errors.push(String(e.message)));
const countError=()=>/^(?:console|script) error/i.test(document.getElementById('listcount').textContent);
// Inject the historical defect into this disposable page to prove the assertion catches it.
const saved=SovStatus.shortLabel;SovStatus.shortLabel=undefined;window.sovView('settings');document.querySelector('[data-goto-view="jobs"]').click()
check('regression detector catches missing Hub helper',countError());SovStatus.shortLabel=saved;
for(const theme of ['dark','light']){await change(theme);for(const view of ['sources','hosts','archive','discover','jobs','backups','recovery']){
 window.sovView(view);await pause(60);check(theme+' '+view+' renders without script error',!countError());
 if(view==='jobs')check(theme+' Hub renders nested runner lanes',document.getElementById('rows').textContent.includes('Lanes inside'));
}}
check('no unexpected errors',errors.length===0);
window.sovView('settings');await pause(300);const select=document.getElementById('s-appearance');check('Settings exposes System Dark Light',select&&[...select.options].map(o=>o.value).join(',')==='system,dark,light');
const refresh=document.getElementById('s-refresh');refresh.value='300';
select.value='dark';select.dispatchEvent(new Event('change',{bubbles:true}));await wait(()=>document.documentElement.dataset.theme==='dark');
check('Appearance preserves other unsaved settings',refresh===document.getElementById('s-refresh')&&refresh.value==='300');
await change('light');check('menu or native changes synchronize setting',select.value==='light');report();
'''
SYSTEM=r'''
await wait(()=>!document.getElementById('system-home').hidden);window.sovView('system');
const home=document.getElementById('system-home');
for(const theme of ['dark','light']){
 await change(theme);const tab=name=>home.querySelector('[data-pane="'+name+'"]');tab('world').click();
 const node=home.querySelector('[data-node="tool:reader"]');node.dispatchEvent(new MouseEvent('click',{bubbles:true}));
 check(theme+' selected node',home.querySelector('[data-node="tool:reader"]').getAttribute('aria-pressed')==='true');
 const fill=getComputedStyle(home.querySelector('.sv-block-top')).fill;
 check(theme+' map palette',fill===(theme==='light'?'rgb(245, 247, 247)':'rgb(32, 59, 78)'));
 tab('flow').click();const svg=home.querySelector('.sv-trace svg'),trace=home.querySelector('.sv-trace'),floor=Math.max(trace.clientWidth,Math.round(svg.viewBox.baseVal.width*.82));
 // The route fills its pane but never drops below the scale that keeps labels legible; a narrower pane scrolls.
 check(theme+' full route fits or scrolls at a legible scale',Math.abs(svg.getBoundingClientRect().width-floor)<=1&&trace.scrollWidth<=floor+1);
 check(theme+' route endpoints within the route',[...svg.querySelectorAll('.sv-route-station')].every(e=>{const r=e.getBoundingClientRect(),b=trace.getBoundingClientRect();return r.left>=b.left&&r.right<=b.left+trace.scrollWidth+1}));
 check(theme+' no page overflow',document.documentElement.scrollWidth<=innerWidth);
 tab('inspect').click();check(theme+' selection survives panes',home.querySelector('.sv-inspect-detail').dataset.selection==='tool:reader');tab('learn').click();
}
document.querySelector('[data-pane="world"]').click();report();
'''
GATE=r'''
await wait(()=>document.querySelector('[data-act="gate-resolve"]'));document.querySelector('[data-act="gate-resolve"]').click();
const preview=document.getElementById('gate-resolution-preview'),comparison=document.getElementById('gate-comparison');
for(const theme of ['dark','light']){await change(theme);check(theme+' review preview preserved',document.getElementById('gate-resolution-preview')===preview&&comparison===document.getElementById('gate-comparison')&&comparison.textContent.length>0);check(theme+' explicit decision retained',!!document.querySelector('[data-verb="resolve"]'))}
report();
'''

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--scenes',nargs='*');args=parser.parse_args();args.evidence.mkdir(parents=True,exist_ok=True)
 suite='com.sovereign.qa.appearance.'+uuid.uuid4().hex;reports=[]
 app=HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'
 def run(scene,root,command,script,size='900x600',anchor=None,home=None):
  env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(command),SOV_WINDOW=size,SOV_SNAPSHOT=str(args.evidence/(scene+'-'+size+'.png')),SOV_SNAPSHOT_DELAY='7',SOV_SNAPSHOT_ANCHOR='')
  env.pop('SOV_APPEARANCE',None)
  code=COMMON.replace('SCENE',json.dumps(scene))+script
  if anchor:env.update(SOV_SNAPSHOT_ANCHOR=anchor,SOV_QA_JS_AFTER_ANCHOR=code)
  else:env['SOV_QA_JS']='(async()=>{'+code+'})().catch(e=>window.webkit.messageHandlers.sov.postMessage({cmd:"clientError",where:"appearance-qa-failure",msg:String(e.stack||e)}));void 0;'
  # Preserve the draft through all checks and the first screenshot. Clear only
  # this disposable fixture before snapshot shutdown reaches the native quit guard.
  if scene=='navigation':env['SOV_QA_JS']="window.webkit.messageHandlers.sov.postMessage({cmd:'appearance',value:'dark'});void 0;"
  if home:env['SOV_QA_GATE_HOME']=str(home)
  cp=subprocess.run([str(app),'-sov.archive',str(root)],env=env,text=True,capture_output=True,timeout=50)
  (args.evidence/(scene+'-'+size+'.log')).write_text(cp.stderr)
  marker='client error in appearance-qa: ';rows=[json.loads(s.split(marker,1)[1]) for s in cp.stderr.splitlines() if marker in s]
  assert cp.returncode==0 and len(rows)==1,(scene,cp.stderr)
  reports.extend(rows);assert not rows[0]['failures'],rows[0]
  if scene=='draft':
   assert 'appearance native: ' in cp.stderr and 'saved=system inherited=true' in cp.stderr,cp.stderr
   assert 'appearance glance: dark' in cp.stderr and 'appearance glance: light' in cp.stderr,cp.stderr
  print(scene,size,len(rows[0]['checks']),'checks passed',flush=True)
 try:
  with tempfile.TemporaryDirectory(prefix='sovereign-appearance-') as tmp:
   base=Path(tmp);root=base/'Appearance QA';brain_local.create(root,REPO);root=root.resolve();brain_local.capture(root,'Existing note','Keep local content.')
   data={'machine':{'connected':True,'host':'QA Desk','vault':str(root),'vault_name':'Appearance QA'},'hub':{'reachable':True,'hub_host':'QA Hub','pending':0},'archive':{'cards':[]},'jobs':[{'label':'com.sov.connector.runner','last_exit':0},{'label':'collection','kick':'com.sov.connector.runner','last_exit':0}],'harnesses':[{'id':'reader','name':'QA Reader','state':'connected','hook_registered':True,'read':'hook','trusted':True,'lane':'reader','lane_dir':str(root/'raw/tools/reader')}],'fleet':{'hosts':[{'host':'QA Desk','net':{'online':True}}]},'needs_you':[]}
   command=base/'status';command.write_text('#!/bin/sh\ncat <<\'DATA\'\n'+json.dumps(data)+'\nDATA\n');command.chmod(0o700)
   for scene,script,anchor in [('home',HOME,None),('persist',PERSIST,None),('navigation',"check('new document uses current theme',document.documentElement.dataset.theme==='dark');report();",'operations:view:sources'),('operations',OPS,'operations:view:jobs'),('system',SYSTEM,None)]:
    if args.scenes and scene not in args.scenes:continue
    for size in (['900x600','720x460'] if scene in ['operations','system'] else ['900x600']):run(scene,root,command,script,size,anchor)
  if not args.scenes or 'gate' in args.scenes:
   t=fixture.GateCheckTests();t.setUp()
   try:
    t.resolution();t.existing('concepts','concept');command=t.setup_real_gate();home=t.base;(home/'.brain-root').write_text(str(t.root));(home/'.curator-lane').write_text('curator');(home/'brain-bin').mkdir();(home/'brain-bin/sov').write_bytes(command.read_bytes());(home/'brain-bin/sov').chmod(0o700)
    data={'machine':{'connected':True,'host':'QA','vault':str(t.root)},'hub':{'reachable':True,'via':'local','pending':1,'proposals':[{'slug':t.slug,'title':'Example','type':'entity','body':'Reviewed content','source':'owner','confidence':'high'}]},'archive':{'cards':[]}}
    status=home/'status';status.write_text('#!/bin/sh\ncat <<\'DATA\'\n'+json.dumps(data)+'\nDATA\n');status.chmod(0o700)
    paths=[t.proposals/(t.slug+'.md'),t.root/'knowledge/concepts'/(t.slug+'.md'),t.proposals/'.meta.json'];before=[p.read_bytes() for p in paths]
    run('gate',t.root,status,GATE,anchor='operations:view:review+open:p:'+t.slug,home=home)
    assert before==[p.read_bytes() for p in paths],'Appearance mutated proposal or card'
   finally:t.tearDown()
 finally:
  (args.evidence/'appearance-native.json').write_text(json.dumps(reports,indent=2)+'\n')
  subprocess.run(['defaults','delete',suite],capture_output=True);Path.home().joinpath('Library/Preferences',suite+'.plist').unlink(missing_ok=True)
 print(sum(len(r['checks']) for r in reports),'native checks passed')
if __name__=='__main__':main()
