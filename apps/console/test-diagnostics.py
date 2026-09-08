import json, os, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
evidence=parser.parse_args().evidence;evidence.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='sovereign-diag-') as directory:
 p=Path(directory);cmd=p/'status';payload=('x'*131072+'z'*450+'\npassword=shortsecret\n'+'sk-'+('aB3'*30)+'\nFINAL_DIAGNOSTIC café\n')
 data=p/'stderr';data.write_text(payload)
 cmd.write_text('#!/bin/sh\ncat '+str(data)+' >&2\nprintf invalid-json\nexit 3\n');cmd.chmod(0o700)
 js='''const original=window.sovDeliver;window.sovDeliver=(kind,payload)=>{if(kind==='status'&&payload.request===777){const checks={generic:payload.error==='System status could not be read. Retry or inspect Operations.',bounded:new TextEncoder().encode(payload.detail).length<=400,tail:payload.detail.endsWith('FINAL_DIAGNOSTIC café\\n'),redacted:payload.detail.includes('[redacted'),noSecret:!payload.detail.includes('shortsecret')&&!payload.detail.includes('aB3')};window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'diagnostics-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})})}return original(kind,payload)};window.webkit.messageHandlers.sov.postMessage({cmd:'status',request:777});'''
 env=dict(os.environ,SOV_QA_STATUS_COMMAND=str(cmd),SOV_QA_JS=js,SOV_SNAPSHOT=str(evidence/'diagnostics.png'),SOV_SNAPSHOT_DELAY='7',SOV_APPEARANCE='dark')
 result=subprocess.run([str(root/'build/Sovereign.app/Contents/MacOS/Sovereign')],env=env,capture_output=True,text=True,timeout=40)
 assert 'shortsecret' not in result.stderr and 'aB3' not in result.stderr
 (evidence/'diagnostics.log').write_text(result.stderr)
 marker='client error in diagnostics-qa: ';rows=[json.loads(l.split(marker)[1]) for l in result.stderr.splitlines() if marker in l];assert result.returncode==0 and len(rows)==1
 assert not rows[0]['failures'],rows
 (evidence/'diagnostics.json').write_text(json.dumps(rows[0],indent=2)+'\n');print(rows[0])
