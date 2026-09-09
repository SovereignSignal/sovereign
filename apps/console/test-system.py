#!/usr/bin/env python3
"""Exercise the native System view with a separate operator's disposable archive."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO/'lib'))
import brain_local
with tempfile.TemporaryDirectory(prefix='sovereign-system-test-') as tmp:
 base=Path(tmp); root=base/'Independent QA';brain_local.create(root,REPO);root=root.resolve()
 data={'generated_at':'2026-09-09T00:00:00Z','machine':{'connected':True,'vault':str(root),'vault_name':root.name,'host':'Desk-QA'},'hub':{'reachable':True,'via':'ssh office','hub_host':'Office-QA','pending':1},'fleet':{'hosts':[{'host':'Desk-QA','net':{'online':True}},{'host':'Worker-QA','net':{'online':False}}]},'harnesses':[{'id':'read','name':'QA Reader','state':'connected','hook_registered':True,'read':'hook','trusted':True,'lane':'read-desk','lane_dir':str(root/'raw/tools/read-desk')},{'id':'collect','name':'A custom collector <img src=x>','state':'connected','job_loaded':True,'has_mirror':True,'read':'none','lane':'custom-desk'}],'lanes':[],'needs_you':[]}
 payload=base/'status.json';payload.write_text(json.dumps(data))
 command=base/'status';command.write_text('#!/bin/sh\nexec /bin/cat '+"'"+str(payload).replace("'","'\"'\"'")+"'\n");command.chmod(0o700)
 image=Path(sys.argv[1]) if len(sys.argv)>1 else base/'native.png'
 env=dict(os.environ,SOV_QA_JS=(HERE/'tests/system.js').read_text(),SOV_QA_STATUS_COMMAND=str(command),SOV_SNAPSHOT=str(image),SOV_SNAPSHOT_DELAY='8',SOV_SNAPSHOT_ANCHOR='',SOV_WINDOW=os.environ.get('SOV_WINDOW','1380x900'),SOV_APPEARANCE=os.environ.get('SOV_APPEARANCE','dark'))
 result=subprocess.run([str(REPO/'apps/console/build/Sovereign.app/Contents/MacOS/Sovereign'),'-sov.archive',str(root)],env=env,capture_output=True,text=True,timeout=40)
 marker='client error in system-qa: '
 line=next((x for x in result.stderr.splitlines() if marker in x),None)
 if result.returncode or line is None:raise SystemExit(result.stderr)
 report=json.loads(line.split(marker,1)[1]);print(json.dumps(report,indent=2))
 if report['failures']:raise SystemExit(1)
