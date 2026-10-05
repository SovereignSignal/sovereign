#!/usr/bin/env python3
"""Native corrective-release evidence; only the disposable archive is writable."""
import argparse, json, os, subprocess, tempfile, sys, uuid
from pathlib import Path
from datetime import datetime, timezone
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local

def probe(theme,view,live=False):
 return '''(()=>{const expected=THEME,view=VIEW,live=LIVE;
 const checks={},theme=document.documentElement.dataset.theme;
 const css=getComputedStyle(document.body);
 checks.theme=theme===expected;
 checks.ground=css.backgroundColor===(expected==='dark'?'rgb(0, 6, 15)':'rgb(250, 250, 247)');
 checks.noNotes=!document.getElementById('notes-tab')&&!document.getElementById('editor');
 checks.rail=!!document.querySelector('.shell-rail')&&getComputedStyle(document.querySelector('.shell-rail')).display!=='none';
 checks.noHorizontalOverflow=document.documentElement.scrollWidth<=innerWidth;
 checks.page=['sources','review'].includes(view)?location.pathname.endsWith('/index.html'):location.pathname.endsWith('/local.html');
 const tab={home:'today',system:'sources'}[view]||view;
 checks.selectedTab=document.getElementById(tab+'-tab').getAttribute('aria-pressed')==='true';
 checks.fiveDestinations=[...document.querySelectorAll('.shell-rail [data-nav]')].map(b=>b.dataset.nav).join()==='today,review,sources,library,backups,settings';
 checks.oneFrame=!!document.querySelector('header.top h1')&&!document.getElementById('switch')&&!document.querySelector('.hubpill');
 let count=Number(document.getElementById('review-count').textContent||0),unknown=[];
 if(view==='sources'){
  checks.heading=document.getElementById('vault').textContent==='Sources';
  checks.faces=[...document.querySelectorAll('#controls .seg [data-view]')].map(b=>b.dataset.view).join()==='sources,hosts,system';
 }else if(view==='review'){
  checks.queueCount=document.querySelectorAll('#rows [data-id^="p:"]').length===count;
  checks.reviewHeading=document.getElementById('vault').textContent==='Review';
  checks.sideBySide=!live||count===0||(()=>{const q=document.getElementById('listpane').getBoundingClientRect(),d=document.getElementById('inspector').getBoundingClientRect();return q.right<=d.left+1&&d.width>300})();
  // The selected proposal was checked against the QA archive, so Approve is open.
  checks.gateChecked=live||count===0||document.querySelector('[data-act="gate"][data-verb="approve"]')?.disabled===false;
 }else if(view==='system')checks.systemVisible=!!document.querySelector('.sv');
 else {checks.homeVisible=!document.getElementById('system-home').hidden;
  const rows=[...document.querySelectorAll('.today-needs .today-item')];
  checks.headline=!!document.querySelector('.today-headline h2');
  checks.attentionCount=live||(rows.length===4&&document.querySelector('.today-headline h2').textContent==='4 things need you');
  checks.figures=document.querySelectorAll('.today-tiles .fig-tile').length===4;
  // A lane whose acceptance is unknown is not something that needs the owner.
  unknown=rows.filter(e=>/unknown-producer|acceptance.*(?:unverified|not reported|unknown)|not been verified/.test(e.textContent)).map(e=>e.textContent);
 }
 checks.noUnknownAttention=unknown.length===0;
 if(!live)checks.expectedCount=count===2;
 window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'release-qa',msg:JSON.stringify({view,theme,width:innerWidth,height:innerHeight,count,unknown,checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
})()'''.replace('THEME',json.dumps(theme)).replace('VIEW',json.dumps(view)).replace('LIVE',json.dumps(live))

def gate_home(base,archive,proposals):
 """A disposable HOME for the Review gate check: it points at the QA archive, which holds the fixture's proposals."""
 home=base/'gate-home';home.mkdir();(home/'.brain-root').write_text(str(archive))
 lane=archive/'raw/workspaces/curator/proposals';lane.mkdir(parents=True)
 for p in proposals:(lane/(p['slug']+'.md')).write_text('---\ntype: '+p['type']+'\nsource: owner\ncreated: 2026-01-01\ntitle: '+p['title']+'\n---\n\nReviewed content.\n')
 return home

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--live',action='store_true');args=parser.parse_args()
 args.evidence.mkdir(parents=True,exist_ok=True); reports=[]
 app=HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'
 suite='com.sovereign.qa.release.'+uuid.uuid4().hex   # never the preview's own preferences, live or not
 try:main_runs(args,app,suite,reports)
 finally:subprocess.run(['defaults','delete',suite],capture_output=True);Path.home().joinpath('Library/Preferences',suite+'.plist').unlink(missing_ok=True)

def main_runs(args,app,suite,reports):
 with tempfile.TemporaryDirectory(prefix='sovereign-release-') as folder:
  base=Path(folder);archive=base/'QA Archive';brain_local.create(archive,ROOT);archive=archive.resolve()
  brain_local.capture(archive,'A useful decision','Local notes remain portable Markdown.')
  fixture={'version':'QA','generated_at':datetime.now(timezone.utc).isoformat(),'machine':{'connected':True,'host':'studio','vault':str(archive),'vault_name':'QA archive','hub_pointer':'hub:/archive'},'hub':{'reachable':True,'pending':2,'proposals':[{'slug':'first','title':'A useful decision','type':'concept'},{'slug':'second','title':'Keep this finding','type':'entity'}]},'needs_you':[{'kind':'gate','text':'2 proposals ready for review'}],'jobs':[{'label':'collection-test','last_exit':1}],'fleet':{'hosts':[{'host':'studio','net':{'online':True}},{'host':'worker','net':{'online':False}}]},'archive':{'cards':[]},'harnesses':[], 'backups':{'lanes':[{'lane':'unknown-producer'},{'lane':'waiting-producer','delivery':'waiting'},{'lane':'accepted-producer','delivery':'accepted','pushed':datetime.now(timezone.utc).isoformat()}]}}
  gate=gate_home(base,archive,fixture['hub']['proposals'])
  command=base/'status';command.write_text('#!/bin/sh\ncat <<\'STATUS\'\n'+json.dumps(fixture)+'\nSTATUS\n');command.chmod(0o700)
  cases=[('dark','900x600','home','sources')] if args.live else [(theme,size,first,second) for theme in ['dark','light'] for size in ['900x600','720x460'] for first,second in [('home','review'),('system','sources')]]
  for theme,size,first,second in cases:
   name=('live-' if args.live else '')+theme+'-'+size
   snap=args.evidence/(name+'-'+first+'.png')
   env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(snap),SOV_SNAPSHOT_DELAY='7',SOV_SNAPSHOT_ANCHOR='operations:view:'+second,SOV_QA_JS='window.sovView('+json.dumps(first)+');setTimeout(()=>{'+probe(theme,first,args.live)+'},1500);',SOV_QA_JS_AFTER_ANCHOR="for(let n=0;n<100&&(/checking/.test(document.getElementById('vmeta')?.textContent||'')||document.querySelector('.rv-check.checking'));n++)await new Promise(r=>setTimeout(r,50));"+probe(theme,second,args.live))
   # The gate check reads HOME's pointer unless these name an archive; keep it on the QA one.
   if not args.live:env.update(SOV_QA_STATUS_COMMAND=str(command),SOV_QA_GATE_HOME=str(gate));env.pop('BRAIN_ROOT',None);env.pop('SOVS_VAULT',None)
   # CLI defaults override the archive for this process without persisting preferences.
   result=subprocess.run([str(app),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=45)
   (args.evidence/(name+'-'+first+'.log')).write_text(result.stderr)
   extra=snap.with_name(snap.stem+'-bottom.png')
   if extra.exists():extra.rename(args.evidence/(name+'-'+second+'.png'))
   marker='client error in release-qa: '
   rows=[json.loads(line.split(marker,1)[1]) for line in result.stderr.splitlines() if marker in line]
   reports.extend(rows)
   print(name,first,second,'exit',result.returncode,'checks',len(rows),flush=True)
   if result.returncode or len(rows)!=2:raise RuntimeError('Snapshot run failed; inspect evidence log: '+str(snap))
  output=args.evidence/('live-verification.json' if args.live else 'native-matrix.json');output.write_text(json.dumps(reports,indent=2)+'\n')
  failures=[r for r in reports if r['failures']]
  if failures:raise SystemExit(json.dumps(failures,indent=2))
  print(str(output)+': all '+str(len(reports))+' native views passed')
if __name__=='__main__':main()
