import json, os, subprocess, sys, tempfile, uuid
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]/'lib'))
import brain_local
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
evidence=parser.parse_args().evidence;evidence.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='sovereign-diag-') as directory:
 p=Path(directory);cmd=p/'status';payload=('x'*131072+'z'*450+'\npassword=shortsecret\n'+'sk-'+('aB3'*30)+'\nFINAL_DIAGNOSTIC café\n')
 data=p/'stderr';data.write_text(payload)
 cmd.write_text('#!/bin/sh\ncat '+str(data)+' >&2\nprintf invalid-json\nexit 3\n');cmd.chmod(0o700)
 # The pending delivery comes first; the failure carries its sentence and detail in _status.
 js='''const original=window.sovDeliver;window.sovDeliver=(kind,payload)=>{const s=kind==='status'&&payload.request===777&&payload._status;if(s&&!s.pending&&s.error){const d=s.detail||'',checks={generic:s.error.startsWith('System status could not be read (exit 3).')&&!s.error.includes('FINAL_DIAGNOSTIC'),bounded:new TextEncoder().encode(d).length<=400,tail:d.endsWith('FINAL_DIAGNOSTIC café\\n'),redacted:d.includes('[redacted'),noSecret:!d.includes('shortsecret')&&!d.includes('aB3')};window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'diagnostics-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})})}return original(kind,payload)};window.webkit.messageHandlers.sov.postMessage({cmd:'status',request:777});'''
 # A disposable archive, preference suite and window size: the run never opens or writes the owner's.
 archive=p/'QA Archive';brain_local.create(archive,root.parents[1]);suite='com.sovereign.qa.diagnostics.'+uuid.uuid4().hex
 env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(cmd),SOV_QA_JS=js,SOV_SNAPSHOT=str(evidence/'diagnostics.png'),SOV_SNAPSHOT_DELAY='7',SOV_WINDOW='900x600',SOV_APPEARANCE='dark')
 try:result=subprocess.run([str(root/'build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(archive.resolve())],env=env,capture_output=True,text=True,timeout=40)
 finally:subprocess.run(['defaults','delete',suite],capture_output=True)
 assert 'shortsecret' not in result.stderr and 'aB3' not in result.stderr
 (evidence/'diagnostics.log').write_text(result.stderr)
 marker='client error in diagnostics-qa: ';rows=[json.loads(l.split(marker)[1]) for l in result.stderr.splitlines() if marker in l];assert result.returncode==0 and len(rows)==1
 assert not rows[0]['failures'],rows
 (evidence/'diagnostics.json').write_text(json.dumps(rows[0],indent=2)+'\n');print(rows[0])
