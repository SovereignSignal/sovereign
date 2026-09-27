#!/usr/bin/env python3
"""Native approval UX against disposable archives and real local curator scripts."""
import argparse,hashlib,importlib.util,json,os,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gate_fixture',HERE/'tests/test_gate_check.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

QA=r'''
const scenario=SCENARIO,fixtureStatus=STATUS,checks={};
const wait=async(test)=>{for(let i=0;i<180;i++){if(test())return;await new Promise(r=>setTimeout(r,50))}throw Error('Timed out waiting for '+scenario+': '+document.querySelector('#insp').textContent.slice(0,1400))};
await wait(()=>document.querySelector('.gate-feedback')&&!document.querySelector('#insp .checking'));
const approve=()=>document.querySelector('[data-act="gate"][data-verb="approve"]');
checks.rail=!!document.querySelector('.shell-rail');checks.noHorizontalOverflow=document.documentElement.scrollWidth<=innerWidth;
checks.flagsRetained=document.querySelector('#insp').textContent.includes('needs-source-review');
if(scenario.startsWith('resolve')){
 const start=()=>document.querySelector('[data-act="gate-resolve"]');
 checks.resolveAvailable=!!start();checks.noPrematureApproval=!document.querySelector('[data-act="gate"][data-verb="resolve"]');
 start().click();checks.preview=!!document.querySelector('#gate-resolution-preview');checks.currentCardOpen=document.querySelector('#gate-comparison').open;
 checks.typeExplained=document.querySelector('#gate-resolution-preview').textContent.includes('Keep the existing classification: concept');
 checks.originalsExplained=document.querySelector('#gate-resolution-preview').textContent.includes('Both originals');
 checks.flagsStillVisible=document.querySelector('#insp').textContent.includes('needs-source-review');checks.safeRendering=!document.querySelector('#insp img');
 document.querySelector('[data-act="gate-cancel-resolution"]').click();checks.cancelRestoresReview=!!start();start().click();
 if(scenario==='resolve-change'){
   fixtureStatus.hub.proposals[0].body='Changed after preview';window.sovDeliver('status',fixtureStatus);
   checks.stalePreviewRemoved=!document.querySelector('#gate-resolution-preview');await wait(()=>!!start());
   checks.newPreviewRequired=!document.querySelector('[data-act="gate"][data-verb="resolve"]');
 }else if(scenario==='resolve-preview'){
   fixtureStatus.hub.proposals[0].age_h+=1;window.sovDeliver('status',fixtureStatus);
   checks.ageRefreshKeepsPreview=!!document.querySelector('#gate-resolution-preview');
   document.querySelector('#gate-resolution-preview').scrollIntoView({block:'start'});
 }else{
   const action=document.querySelector('[data-act="gate"][data-verb="resolve"]');action.click();action.click();
   checks.running=!!document.querySelector('#gate-notice.running');checks.quitProtected=window.sovCanQuit()===false;
   document.getElementById('operations-tab').click();checks.navigationProtected=document.body.classList.contains('review');
   if(scenario==='resolve-quit')window.webkit.messageHandlers.sov.postMessage({cmd:'qaQuit'});
   const expected=scenario==='resolve-fail'?'failed':'approved';await wait(()=>!!document.querySelector('#gate-notice.'+expected));
   checks.result=true;checks.noTerminalDump=!document.querySelector('#drawer.open');
   if(scenario==='resolve-fail'){
    checks.failedResolutionStaysVisible=!!document.querySelector('#insp .failed')&&approve().disabled;
    document.querySelector('[data-act="gate-check"]').click();
    await wait(()=>!!start());checks.failedResolutionCanReviewAgain=true;
   }
 }
}else if(scenario==='conflict'){
 checks.blocked=approve().disabled;checks.explanation=document.querySelector('#insp').textContent.includes('Two card types need reconciling');
 document.querySelector('[data-act="gate-compare"]').click();checks.comparison=document.querySelector('#gate-comparison').open;
 checks.bothCards=document.querySelector('#gate-comparison').textContent.includes('Existing detail');checks.safeRendering=!document.querySelector('#insp img');
 checks.resolutionRequest=!!document.querySelector('[data-act="gate-copy"]');document.querySelector('#inspector').scrollTop=0;
}else if(scenario==='refresh'){
 checks.initialReady=!approve().disabled;
 fixtureStatus.hub.proposals[0].age_h+=1;
 window.sovDeliver('status',fixtureStatus);
 checks.ageRefreshStaysReady=!approve().disabled&&!document.querySelector('#insp .checking');
 fixtureStatus.hub.proposals[0].body='Changed status content';
 window.sovDeliver('status',fixtureStatus);
 checks.changedRefreshChecks=approve().disabled&&!!document.querySelector('#insp .checking');
 await wait(()=>!document.querySelector('#insp .checking'));
 checks.rechecked=!approve().disabled;
}else if(['unavailable','missing','resolution_pending'].includes(scenario)){
 checks.blocked=approve().disabled;checks.checkAgain=!!document.querySelector('[data-act="gate-check"]');checks.expectedState=!!document.querySelector('#insp .'+scenario);
 if(scenario==='resolution_pending'){checks.rejectBlocked=document.querySelector('[data-verb="reject"]').disabled;checks.recoveryRequest=document.querySelector('[data-act="gate-copy"]').textContent==='Copy recovery request';}
}else{
 checks.ready=!approve().disabled;
 if(scenario==='timeout'){
   const original=window.setTimeout;
   window.setTimeout=(fn,ms,...args)=>{if(ms===120000){checks.deadlineScheduled=true;return original(fn,200,...args)}return original(fn,ms,...args)};
 }
 const action=['reject','repeat-reject'].includes(scenario)?document.querySelector('[data-verb="reject"]'):approve();action.click();if(['reject','repeat-reject'].includes(scenario))action.click();else action.click();
 checks.running=!!document.querySelector('#gate-notice.running');checks.quitProtected=window.sovCanQuit()===false;
   document.getElementById('operations-tab').click();checks.navigationProtected=document.body.classList.contains('review');
 if(scenario==='quit')window.webkit.messageHandlers.sov.postMessage({cmd:'qaQuit'});
 const expected=['approve','quit'].includes(scenario)?'approved':['reject','repeat-reject'].includes(scenario)?'rejected':scenario==='timeout'?'uncertain':'failed';
 await wait(()=>document.querySelector('#gate-notice.'+expected));checks.result=true;
 checks.noTerminalDump=!document.querySelector('#drawer.open');
 if(scenario==='quit')checks.survivedNativeQuit=true;
 if(scenario==='timeout'){
   checks.quitReleased=window.sovCanQuit()===true;
   checks.uncertainStaysVisible=!!document.querySelector('#insp .uncertain')&&approve().disabled;
   document.querySelector('[data-act="gate-check"]').click();
   await wait(()=>!!document.querySelector('#insp .busy'));
   checks.retryBlocked=approve().disabled;
   await new Promise(r=>setTimeout(r,2800));
   checks.lateReplyIgnored=!!document.querySelector('#gate-notice.uncertain');
 }

 await new Promise(r=>setTimeout(r,300));
}
window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'gate-qa',msg:JSON.stringify({scenario,width:innerWidth,height:innerHeight,theme:document.documentElement.dataset.theme,checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
if(['quit','timeout','resolve-quit'].includes(scenario))window.webkit.messageHandlers.sov.postMessage({cmd:'qaQuit'});
'''

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--scenarios',nargs='*');a=parser.parse_args();a.evidence.mkdir(parents=True,exist_ok=True);reports=[]
 cases=[(scene,theme,size) for scene in ['conflict','approve'] for theme in ['dark','light'] for size in ['900x600','720x460']]+[(scene,'dark','900x600') for scene in ['reject','repeat-reject','failed','missing','unavailable','refresh','quit','timeout']]
 cases += [(scene,'dark',size) for scene in ['resolve','resolve-preview'] for size in ['900x600','720x460']]+[(scene,'dark','900x600') for scene in ['resolve-change','resolve-fail','resolve-quit']]+[('resolve-preview','light','720x460'),('resolution_pending','dark','720x460')]
 if a.scenarios:cases=[c for c in cases if c[0] in a.scenarios]
 for scene,theme,size in cases:
  t=fixture.GateCheckTests();t.setUp()
  try:
   if scene.startswith('resolve'):
    t.resolution();t.card(t.root/'knowledge/concepts'/(t.slug+'.md'),'concept','Existing detail <img src=x onerror=alert(1)>')
   if scene=='conflict':t.existing('concepts','concept');t.card(t.root/'knowledge/concepts'/(t.slug+'.md'),'concept','Existing detail <img src=x onerror=alert(1)>')
   if scene=='repeat-reject':t.card(t.root/'raw/workspaces/curator/rejected'/(t.slug+'.md'),body='Earlier rejected card')
   command=t.setup_real_gate();home=t.base;(home/'.brain-root').write_text(str(t.root));(home/'.curator-lane').write_text('curator');(home/'brain-bin').mkdir();target=home/'brain-bin/sov'
   code=command.read_text().replace('#!/bin/sh\n','#!/bin/sh\nprintf "%s\\n" "$2" >> "$HOME/gate-calls"\n')
   if scene in ['quit','timeout','resolve-quit']:code=code.replace('#!/bin/sh\n','#!/bin/sh\nsleep 2\n')
   if scene in ['failed','resolve-fail']:code='#!/bin/sh\nprintf "%s\\n" "$2" >> "$HOME/gate-calls"\necho REFUSED: test failure\nexit 1\n'
   target.write_text(code);target.chmod(0o700)
   if scene=='resolution_pending':
    key=hashlib.sha256((str(t.root)+'\0curator\0'+t.slug).encode()).hexdigest();record=home/'.sovereign/gate-locks/resolutions'/(key+'.json');record.parent.mkdir(parents=True);record.write_text(json.dumps({'status':'pending'}))
   if scene=='unavailable':(home/'.brain-root').unlink()
   if scene=='missing':(t.proposals/(t.slug+'.md')).unlink()
   prop={'slug':t.slug,'title':'Example card','type':'entity','body':'Reviewed content','source':'owner','confidence':'high','flags':['needs-source-review'],'words':2,'age_h':1}
   data={'machine':{'connected':True,'host':'test','vault':str(t.root),'vault_name':'Approval QA'},'hub':{'reachable':True,'via':'local','pending':1,'proposals':[prop]},'archive':{'cards':[]},'needs_you':[{'kind':'gate','text':'One proposal to review'}]}
   status=home/'status';status.write_text('#!/usr/bin/python3\nimport json\nfrom pathlib import Path\nd='+repr(data)+'\n'+('' if scene=='missing' else 'if not Path('+repr(str(t.proposals/(t.slug+'.md')))+').exists(): d["hub"].update(proposals=[],pending=0); d["needs_you"]=[]\n')+'print(json.dumps(d))\n');status.chmod(0o700)
   name=scene+'-'+theme+'-'+size;env=dict(os.environ,SOV_QA_GATE_HOME=str(home),SOV_QA_STATUS_COMMAND=str(status),SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(a.evidence/(name+'.png')),SOV_SNAPSHOT_DELAY='5',SOV_SNAPSHOT_ANCHOR='operations:view:review+open:p:'+t.slug,SOV_QA_JS_AFTER_ANCHOR=QA.replace('SCENARIO',json.dumps(scene)).replace('STATUS',json.dumps(data)))
   result=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(t.root)],env=env,capture_output=True,text=True,timeout=40)
   (a.evidence/(name+'.log')).write_text(result.stderr);marker='client error in gate-qa: ';rows=[json.loads(x.split(marker)[1]) for x in result.stderr.splitlines() if marker in x]
   calls=(home/'gate-calls').read_text().splitlines() if (home/'gate-calls').exists() else []
   expected=1 if scene in ['approve','reject','repeat-reject','failed','quit','timeout','resolve','resolve-fail','resolve-quit'] else 0
   assert len(calls)==expected,(name,calls)
   assert result.returncode==0 and len(rows)==1,(name,result.stderr)
   if scene in ['quit','resolve-quit']:assert 'native quit decision: blocked' in result.stderr and 'native quit decision: allowed' in result.stderr,(name,result.stderr)
   if scene=='timeout':assert 'native quit decision: allowed' in result.stderr,(name,result.stderr)
   if scene in ['resolve','resolve-quit']:
    assert not (t.proposals/(t.slug+'.md')).exists()
    assert fixture.gate.read_card(t.root/'knowledge/concepts'/(t.slug+'.md'),t.root)['type']=='concept'
   if scene in ['resolve-preview','resolve-change','resolve-fail']:
    assert fixture.gate.read_card(t.proposals/(t.slug+'.md'),t.root)['type']=='entity'
   report=rows[0];report['command_count']=len(calls);reports.append(report);print(name,report['failures'],flush=True)
   assert not report['failures'],report
  finally:t.tearDown()
 (a.evidence/'native-gate.json').write_text(json.dumps(reports,indent=2)+'\n')
 print('All '+str(len(reports))+' native approval scenarios passed.')
if __name__=='__main__':main()
