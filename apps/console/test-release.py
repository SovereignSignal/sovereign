#!/usr/bin/env python3
"""Native corrective-release evidence; only the disposable archive is writable."""
import argparse, json, os, subprocess, tempfile, sys
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
 checks.rail=!!document.querySelector('.shell-rail')&&getComputedStyle(document.querySelector('.shell-rail')).display!=='none';
 checks.noHorizontalOverflow=document.documentElement.scrollWidth<=innerWidth;
 checks.page=['operations','review'].includes(view)?location.pathname.endsWith('/index.html'):location.pathname.endsWith('/local.html');
 const isOps=view==='operations';
 checks.selectedTab=document.getElementById((isOps?'operations':view)+'-tab').getAttribute('aria-pressed')==='true';
 let count=Number(document.getElementById('review-count').textContent||0),unknown=[];
 if(isOps){const col=document.querySelector('.glance-home .gcol');checks.glance=!!col;
  checks.attentionCount=!!col&&(live||Number(col.querySelector('.n').textContent)===4);
  unknown=[...(col?.querySelectorAll('.row')||[])].filter(e=>/acceptance.*(?:unverified|not reported|unknown)|not been verified/.test(e.textContent)).map(e=>e.textContent);
 }else if(view==='review'){
  checks.queueCount=document.querySelectorAll('#rows [data-id^="p:"]').length===count;
  checks.reviewHeading=document.getElementById('vault').textContent==='Review';
  checks.noOperationsTabs=getComputedStyle(document.querySelector('#switch .seg')).display==='none';
 }else if(view==='notes')checks.notesVisible=!document.getElementById('workspace').hidden;
 else {checks.homeVisible=!document.getElementById('system-home').hidden;
  const panel=document.querySelector('.home-attention');
  unknown=[...panel.querySelectorAll('.home-row')].filter(e=>/acceptance.*(?:unverified|not reported|unknown)|not been verified/.test(e.textContent)).map(e=>e.textContent);
  if(!live)checks.unknownIdle=!![...document.querySelectorAll('.home-contributions .home-row')].find(e=>e.textContent.includes('Hub acceptance is unknown')&&e.querySelector('.idle'));
 }
 checks.noUnknownAttention=unknown.length===0;
 if(!live)checks.expectedCount=count===2;
 window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'release-qa',msg:JSON.stringify({view,theme,width:innerWidth,height:innerHeight,count,unknown,checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
})()'''.replace('THEME',json.dumps(theme)).replace('VIEW',json.dumps(view)).replace('LIVE',json.dumps(live))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--live',action='store_true');args=parser.parse_args()
 args.evidence.mkdir(parents=True,exist_ok=True); reports=[]
 app=HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'
 with tempfile.TemporaryDirectory(prefix='sovereign-release-') as folder:
  base=Path(folder);archive=base/'QA Archive';brain_local.create(archive,ROOT);archive=archive.resolve()
  brain_local.capture(archive,'A useful decision','Local notes remain portable Markdown.')
  fixture={'version':'QA','generated_at':datetime.now(timezone.utc).isoformat(),'machine':{'connected':True,'host':'studio','vault':str(archive),'vault_name':'QA archive','hub_pointer':'hub:/archive'},'hub':{'reachable':True,'pending':2,'proposals':[{'slug':'first','title':'A useful decision','type':'concept'},{'slug':'second','title':'Keep this finding','type':'entity'}]},'needs_you':[{'kind':'gate','text':'2 proposals ready for review'}],'jobs':[{'label':'collection-test','last_exit':1}],'fleet':{'hosts':[{'host':'studio','net':{'online':True}},{'host':'worker','net':{'online':False}}]},'archive':{'cards':[]},'harnesses':[], 'backups':{'lanes':[{'lane':'unknown-producer'},{'lane':'waiting-producer','delivery':'waiting'},{'lane':'accepted-producer','delivery':'accepted','pushed':datetime.now(timezone.utc).isoformat()}]}}
  command=base/'status';command.write_text('#!/bin/sh\ncat <<\'STATUS\'\n'+json.dumps(fixture)+'\nSTATUS\n');command.chmod(0o700)
  cases=[('dark','900x600','home','operations')] if args.live else [(theme,size,first,second) for theme in ['dark','light'] for size in ['900x600','720x460'] for first,second in [('home','review'),('notes','operations')]]
  for theme,size,first,second in cases:
   name=('live-' if args.live else '')+theme+'-'+size
   snap=args.evidence/(name+'-'+first+'.png')
   env=dict(os.environ,SOV_APPEARANCE=theme,SOV_WINDOW=size,SOV_SNAPSHOT=str(snap),SOV_SNAPSHOT_DELAY='7',SOV_SNAPSHOT_ANCHOR=('operations:view:glance' if second=='operations' else 'operations:view:'+second),SOV_QA_JS='window.sovView('+json.dumps(first)+');setTimeout(()=>{'+probe(theme,first,args.live)+'},1500);',SOV_QA_JS_AFTER_ANCHOR=probe(theme,second,args.live))
   if not args.live:env['SOV_QA_STATUS_COMMAND']=str(command)
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
