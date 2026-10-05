#!/usr/bin/env python3
"""Native application integration check. Every capture goes to a disposable archive."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import brain_local

def main():
    app=HERE/'build/Sovereign.app/Contents/MacOS/Sovereign'
    if not app.exists():
        raise SystemExit('Build the app first; see DISTRIBUTION.md.')
    with tempfile.TemporaryDirectory(prefix='sovereign-native-test-') as folder:
        base=Path(folder); archive=base/'QA Archive'
        brain_local.create(archive,ROOT)
        archive=archive.resolve()
        # Never the owner's status command or the preview's own preferences: a stub and a throwaway suite.
        stub={'machine':{'connected':True,'host':'qa'},'hub':{'reachable':False},'needs_you':[],'fleet':{'hosts':[]},'harnesses':[],'archive':{'cards':[]}}
        status=base/'status';status.write_text('#!/bin/sh\ncat <<\'DATA\'\n'+json.dumps(stub)+'\nDATA\n');status.chmod(0o700)
        suite='com.sovereign.qa.home.'+uuid.uuid4().hex
        env=dict(os.environ,SOV_QA_DEFAULTS_SUITE=suite,SOV_QA_STATUS_COMMAND=str(status),SOV_QA_JS=(HERE/'tests/home.js').read_text(),
                 SOV_SNAPSHOT=str(base/'native.png'),SOV_SNAPSHOT_DELAY='18',
                 SOV_WINDOW='900x680',SOV_SNAPSHOT_ANCHOR='',SOV_APPEARANCE=os.environ.get('SOV_APPEARANCE','light'))
        try:
            result=subprocess.run([str(app),'-sov.archive',str(archive)],env=env,
                                  capture_output=True,text=True,timeout=50)
        finally:
            subprocess.run(['defaults','delete',suite],capture_output=True);Path.home().joinpath('Library/Preferences',suite+'.plist').unlink(missing_ok=True)
        if result.returncode:
            raise SystemExit(result.stderr)
        marker='client error in native-qa: '
        line=next((x for x in result.stderr.splitlines() if marker in x),None)
        if line is None:
            raise SystemExit('Native checks did not report a result.\n'+result.stderr)
        report=json.loads(line.split(marker,1)[1])
        if report['failures']:
            raise SystemExit(json.dumps(report,indent=2))
        print('Native home: %d checks passed.' % len(report['checks']))

if __name__=='__main__':main()
