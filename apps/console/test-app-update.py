#!/usr/bin/env python3
"""Exercise detached update completion in the real app with harmless fake updaters."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'lib'))
import brain_local

PROBE = r'''
(async()=>{
const replies=[],checks={},pause=ms=>new Promise(r=>setTimeout(r,ms));
const post=o=>window.webkit.messageHandlers.sov.postMessage(o);
const deliver=window.sovDeliver;
window.sovDeliver=(kind,payload)=>{if(kind==='appUpdateResult')replies.push(payload);deliver(kind,payload)};
async function wait(test){for(let i=0;i<100;i++){if(test())return;await pause(50)}throw Error('Timed out: '+JSON.stringify(replies))}
const update=()=>post({cmd:'appUpdate',template:'/fixture'});
try{
 update();await wait(()=>replies.some(r=>r.state==='started'));
 update();await wait(()=>replies.some(r=>(r.error||'').includes('already')));
 checks['duplicate launch refused']=true;
 await wait(()=>replies.some(r=>(r.error||'').includes(EXPECTED)));
 checks['terminal error delivered']=true;
 checks['error visible']=document.body.innerText.includes(EXPECTED);
 const before=replies.filter(r=>r.state==='started').length;
 update();await wait(()=>replies.filter(r=>r.state==='started').length>before);
 checks['retry allowed after failure']=true;
 await wait(()=>replies.filter(r=>(r.error||'').includes(EXPECTED)).length===2);
}catch(e){checks[e.message]=false}
post({cmd:'clientError',where:'app-update-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
})();
'''

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--evidence', type=Path, required=True)
    args=parser.parse_args(); args.evidence.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='sovereign-update-qa-') as tmp:
        base=Path(tmp); archive=base/'Archive'; brain_local.create(archive,HERE.parents[1])
        status=base/'status'; status.write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"machine":{"host":"fixture","template":"/fixture"},"needs_you":[]}\'\n');status.chmod(0o700)
        for phase, output, code, expected in [('json', '{"error":"Fixture signing failed"}',1,'Fixture signing failed'), ('crash','Unexpected fixture crash',17,'Unexpected fixture crash'), ('empty','',0,'No result was returned')]:
            suite='com.sovereign.qa.update.'+uuid.uuid4().hex
            updater=base/'updater'
            updater.write_text('#!/bin/sh\ncase " $* " in\n*" --preview "*) printf \'%s\\n\' \'{"state":"preview","token":"fixture"}\';;\n*) sleep 1; printf \'%s\\n\' '+"'"+output+"'"+'; exit '+str(code)+';;\nesac\n');updater.chmod(0o700)
            env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(status),SOV_QA_UPDATE_COMMAND=str(updater),SOV_QA_UPDATE_CONFIRM='1',SOV_SNAPSHOT=str(args.evidence/(phase+'.png')),SOV_SNAPSHOT_DELAY='8',SOV_QA_JS=PROBE.replace('EXPECTED',json.dumps(expected)))
            try:
                cp=subprocess.run([str(HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive)],env=env,capture_output=True,text=True,timeout=40)
                (args.evidence/(phase+'.log')).write_text(cp.stderr)
                marker='client error in app-update-qa: '
                reports=[json.loads(line.split(marker,1)[1]) for line in cp.stderr.splitlines() if marker in line]
                assert cp.returncode==0 and len(reports)==1,(phase,cp.stderr)
                report=dict(reports[0],phase=phase);results.append(report)
                assert not report['failures'],report
                print(phase,len(report['checks']),'checks passed',flush=True)
            finally:
                subprocess.run(['defaults','delete',suite],capture_output=True)
    (args.evidence/'results.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':main()
