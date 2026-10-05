#!/usr/bin/env python3
"""Backup scope persistence and native guards in disposable archives/preferences."""
import argparse
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import brain_local

PROBE = r'''
const checks={},check=(n,v)=>checks[n]=!!v,post=o=>window.webkit.messageHandlers.sov.postMessage(o),pause=ms=>new Promise(r=>setTimeout(r,ms));
// Bounded by the clock: a background window throttles timers, so a count of polls outlasts the snapshot watchdog and the failure goes unnamed.
const wait=async fn=>{for(const end=Date.now()+10000;Date.now()<end;await pause(40))if(fn())return;throw Error('UI state did not arrive: '+fn)};
const button=()=>document.querySelector('[data-act="backup-scope"]');
const row=()=>document.querySelector('.row[data-id="bk:host:worker"]');
const replies=[],deliver=window.sovDeliver;
window.sovDeliver=(kind,payload)=>{if(kind==='backupScope')replies.push(payload);deliver(kind,payload)};
await wait(button);
if(PHASE==='exclude'){
 check('Missing backup initially alerts',row().textContent.includes('not scheduled'));
 for(const changes of [{root:ROOT+'/other'},{host:'unknown'},{vmid:'999'},{node:'node-b'},{required:'false'}]){
  const n=replies.length;post({cmd:'backupScope',root:ROOT,host:'worker',node:'node-a',vmid:'101',required:false,...changes});await wait(()=>replies.length>n);
  check('Native guard '+JSON.stringify(changes),!!replies.at(-1).error);
 }
 check('Local scope explanation visible',document.querySelector('#insp').textContent.includes('Saved for this archive on this Mac'));
 button().click();await wait(()=>button()?.textContent==='Require backup');
 check('Excluded row remains visible and neutral',row().textContent.includes('not required')&&!row().querySelector('.dot.down'));
 check('Backup warning cleared',!/not scheduled|unprotected/.test(row().textContent));
 window.sovRefresh();await pause(500);check('Refresh retains scope',button()?.textContent==='Require backup');
}else if(PHASE==='restore'){
 check('Exclusion survives restart',button().textContent==='Require backup');
 button().click();await wait(()=>button()?.textContent==='Backup not required');
 check('Restore returns missing-backup warning',row().textContent.includes('not scheduled'));
}else if(PHASE==='other-archive'){
 check('Exclusion does not leak to another archive',button().textContent==='Backup not required');
}else if(PHASE==='nas'){
 check('NAS backup renders green',row().textContent.includes('backed up')&&!!row().querySelector('.dot.live'));
 check('NAS destination visible',document.querySelector('#insp').textContent.includes('nas-backup'));
}else if(PHASE==='unknown'){
 check('Unreadable storage remains unknown',row().textContent.includes('unknown')&&!row().querySelector('.dot.live'));
}
check('No horizontal page overflow',document.documentElement.scrollWidth<=innerWidth);
check('Scope button fits drawer',button().getBoundingClientRect().right<=innerWidth);
check('Scope button visible without scrolling',button().getBoundingClientRect().bottom<innerHeight-25);
const rect=button().getBoundingClientRect();check('Scope button can be clicked',button().contains(document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2)));
post({cmd:'clientError',where:'backup-scope-qa',msg:JSON.stringify({checks,failures:Object.keys(checks).filter(k=>!checks[k])})});
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    suite = 'com.sovereign.qa.backups.' + uuid.uuid4().hex
    results = []
    with tempfile.TemporaryDirectory(prefix='sovereign-backup-scope-') as tmp:
        base = Path(tmp)
        archives = [base / 'Archive A', base / 'Archive B']
        for archive in archives:
            brain_local.create(archive, ROOT)
        archives = [a.resolve() for a in archives]
        try:
            for phase, archive, theme, size in [
                ('exclude', archives[0], 'dark', '900x600'),
                ('other-archive', archives[1], 'light', '720x460'),
                ('restore', archives[0], 'light', '900x600'),
                ('nas', archives[0], 'dark', '900x600'),
                ('unknown', archives[0], 'light', '720x460')]:
                host = {'host': 'worker', 'node': 'node-a', 'vmid': '101', 'reachable': True,
                        'scheduled': False, 'jobs': 0, 'inventory_complete': True,
                        'last_dump_age_h': None}
                if phase in ('nas', 'unknown'):
                    host.update(scheduled=True, jobs=1, last_dump_age_h=2,
                                last_backup={'storage': 'nas-backup', 'volid': 'nas-backup:backup/101'},
                                inventory_complete=phase == 'nas')
                data = {'generated_at': datetime.now(timezone.utc).isoformat(),
                        'machine': {'host': 'desk', 'vault': str(archive), 'connected': True},
                        'fleet': {'hosts': [{'host': 'worker', 'net': {'online': True}}]},
                        'backups': {'hosts': [host]}, 'needs_you': []}
                payload = base / 'status.json'
                payload.write_text(json.dumps(data))
                command = base / 'status'
                command.write_text('#!/bin/sh\nexec /bin/cat ' + "'" + str(payload) + "'\n")
                command.chmod(0o700)
                code = PROBE.replace('PHASE', json.dumps(phase)).replace('ROOT', json.dumps(str(archive)))
                env = dict(os.environ, SOV_QA_DEFAULTS_SUITE=suite, SOV_QA_STATUS_COMMAND=str(command),
                           SOV_APPEARANCE=theme, SOV_WINDOW=size,
                           SOV_SNAPSHOT=str(args.evidence / (phase + '.png')), SOV_SNAPSHOT_DELAY='2',
                           SOV_SNAPSHOT_ANCHOR='operations:view:backups+open:bk:host:worker',
                           SOV_QA_JS_AFTER_ANCHOR=code)
                cp = subprocess.run([str(HERE / 'build/Sovereign.app/Contents/MacOS/Sovereign'),
                                     '-sov.archive', str(archive)], env=env, capture_output=True,
                                    text=True, timeout=35)
                (args.evidence / (phase + '.log')).write_text(cp.stderr)
                marker = 'client error in backup-scope-qa: '
                reports = [json.loads(line.split(marker, 1)[1]) for line in cp.stderr.splitlines() if marker in line]
                assert cp.returncode == 0 and len(reports) == 1, (phase, cp.stderr)
                report = dict(reports[0], phase=phase)
                results.append(report)
                assert not report['failures'], report
                saved = plistlib.loads(subprocess.check_output(['defaults', 'export', suite, '-'])).get('sov.backupExclusions', {})
                saved = {str(Path(k).resolve()): v for k, v in saved.items()}
                assert saved.get(str(archives[0]), []) == (['node-a:101'] if phase in ('exclude', 'other-archive') else [])
                assert str(archives[1]) not in saved
                print(phase, len(report['checks']), 'checks passed', flush=True)
        finally:
            subprocess.run(['defaults', 'delete', suite], capture_output=True)
            (args.evidence / 'native-backups.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
