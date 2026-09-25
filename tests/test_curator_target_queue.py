"""Run the real curator against synthetic evidence and a loopback model."""
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TargetQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.vault = self.home/'vault'
        self.knowledge = self.vault/'knowledge/entities/existing-card.md'
        self.knowledge.parent.mkdir(parents=True)
        self.knowledge.write_text('---\ntype: entity\nsource: owner\ncreated: 2020-01-01\n---\n# Existing\nCanonical baseline.\n')
        self.lane = self.vault/'raw/workspaces/test'
        self.proposals = self.lane/'proposals'
        self.proposals.mkdir(parents=True)
        self.requests = []
        self.fail_merge = None
        self.fresh = False
        self.screen = False
        self.kind = 'entity'
        self.concurrent_draft = False
        self.source_time = time.time()+10
        test = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                text = payload['messages'][-1]['content']
                test.requests.append(text)
                match = re.search(r'(?:NEW )?SOURCE: .*?/([ab])\.md', text)
                letter = match.group(1) if match else '?'
                if match is None:
                    result = {'decision':'flagged' if 'Useful evidence a.' in text else 'clean', 'reason':'synthetic screen'}
                elif text.startswith('UPDATE TASK'):
                    if test.concurrent_draft:
                        (test.proposals/'existing-card.md').write_text('Owner draft arrived during the model call')
                    body = 'Canonical baseline. Evidence A.'
                    if letter == 'b':
                        body += ' Evidence B.'
                    result = {'body':body, 'title':'Merged example', 'why':'Both sources matter'}
                    if test.fail_merge == letter: result = {}
                else:
                    result = {'promote':True, 'slug':'new-topic' if test.fresh else 'offered-'+letter,
                              'type':test.kind, 'title':'Example', 'confidence':'high',
                              'update_of':None if test.fresh else 'existing-card',
                              'body':'Evidence '+letter.upper()+'.', 'reason':'Useful'}
                raw = json.dumps({'choices':[{'message':{'content':json.dumps(result)}}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(raw)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def source(self, letter):
        path = self.vault/'raw/tools/test'/(letter+'.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\ntype: capture\nsource: test\n---\n# Evidence '+letter+'\nUseful evidence '+letter+'.\n')
        stamp = self.source_time-(ord(letter)-ord('a'))
        os.utime(path,(stamp,stamp))
        return path

    def run_curator(self):
        env = dict(os.environ, HOME=str(self.home), SOVS_VAULT=str(self.vault),
                   CURATOR_LANE='test', CURATOR_SCREEN='on' if self.screen else '', CURATOR_JUDGE_PARALLEL='1',
                   CURATOR_ENDPOINT='http://127.0.0.1:%d/v1/chat/completions'%self.server.server_port)
        for key in ('CURATOR_INCLUDE','CURATOR_EXCLUDE','SOV_PROGRESS_JOB','SOV_PROGRESS_RUN'):
            env.pop(key,None)
        return subprocess.run([sys.executable,str(ROOT/'bin/curator-run'),'--max','10'],
                              env=env,text=True,capture_output=True,timeout=20)

    def test_alias_updates_merge_once_under_target_and_preserve_evidence(self):
        self.source('a'); self.source('b')
        before = self.knowledge.read_bytes()
        run = self.run_curator(); self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual([p.name for p in self.proposals.glob('*.md')],['existing-card.md'])
        card = (self.proposals/'existing-card.md').read_text()
        self.assertIn('Evidence A.',card); self.assertIn('Evidence B.',card)
        merges = [s for s in self.requests if s.startswith('UPDATE TASK')]
        self.assertEqual(len(merges),2)
        self.assertIn('Unapproved draft',merges[1]); self.assertIn('Evidence A.',merges[1])
        meta = json.loads((self.proposals/'.meta.json').read_text())['existing-card']
        self.assertEqual(meta['update_of'],'existing-card')
        self.assertEqual(len(meta['source_refs']),2)
        self.assertTrue(meta['needs_owner_review'])
        self.assertEqual(self.knowledge.read_bytes(),before)

    def test_second_run_preserves_owner_visible_draft_and_retries_new_evidence(self):
        self.source('a'); self.assertEqual(self.run_curator().returncode,0)
        card = self.proposals/'existing-card.md'; before=card.read_bytes()
        b=self.source('b'); self.requests.clear()
        run=self.run_curator(); self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(card.read_bytes(),before)
        hashes=json.loads((self.lane/'.content-hashes.json').read_text())
        self.assertNotIn(str(b.relative_to(self.vault)),hashes)
        self.assertLess(float((self.lane/'.last-run').read_text()), b.stat().st_mtime)
        self.assertFalse(any(s.startswith('UPDATE TASK') for s in self.requests))
        rows=[json.loads(s) for s in (self.lane/'judgments.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['deferred_target'],'existing-card')
        card.unlink()
        self.assertEqual(self.run_curator().returncode,0)
        self.assertIn('Evidence B.',card.read_text())

    def test_legacy_alias_and_audit_queue_also_reserve_target(self):
        self.source('a')
        for audit in (False,True):
            with self.subTest(audit=audit):
                folder=self.proposals/'audit' if audit else self.proposals
                folder.mkdir(exist_ok=True)
                slug='existing-card' if audit else 'old-alias'
                old=folder/(slug+'.md');old.write_text('Preserve owner draft')
                (self.proposals/'.meta.json').write_text(json.dumps({slug:{'update_of':'existing-card'}}))
                run=self.run_curator();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                self.assertEqual(old.read_text(),'Preserve owner draft')
                self.assertFalse((self.proposals/'existing-card.md').exists())
                old.unlink()

    def test_failed_merge_never_lands_standalone_draft_or_consumes_source(self):
        self.source('a');self.fail_merge='a'
        run=self.run_curator();self.assertNotEqual(run.returncode,0)
        self.assertEqual(list(self.proposals.glob('*.md')),[])
        self.assertEqual(json.loads((self.lane/'.content-hashes.json').read_text()),{})

    def test_later_failed_merge_keeps_first_draft_and_second_source_retryable(self):
        self.source('a');b=self.source('b');self.fail_merge='b'
        run=self.run_curator();self.assertEqual(json.loads((self.lane/'status.json').read_text())['errors'],1)
        self.assertIn('Evidence A.',(self.proposals/'existing-card.md').read_text())
        self.assertNotIn(str(b.relative_to(self.vault)),json.loads((self.lane/'.content-hashes.json').read_text()))

    def test_same_named_new_proposals_are_combined_without_claiming_existing_card(self):
        self.fresh=True;self.source('a');self.source('b')
        run=self.run_curator();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual([p.name for p in self.proposals.glob('*.md')],['new-topic.md'])
        meta=json.loads((self.proposals/'.meta.json').read_text())['new-topic']
        self.assertIsNone(meta['update_of']);self.assertEqual(len(meta['source_refs']),2)

    def test_consolidation_cannot_clear_an_earlier_screen_flag(self):
        self.screen=True;self.source('a');self.source('b')
        run=self.run_curator();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        meta=json.loads((self.proposals/'.meta.json').read_text())['existing-card']
        self.assertTrue(meta['screen_flagged'])
        self.assertIn('synthetic screen',meta['screen_reason'])

    def test_combined_draft_stays_for_owner_even_with_auto_update_grant(self):
        self.kind='concept'
        target=self.vault/'knowledge/concepts/existing-card.md';target.parent.mkdir(parents=True)
        target.write_text(self.knowledge.read_text().replace('type: entity','type: concept'))
        self.knowledge.unlink();self.knowledge=target
        (self.lane/'gears.json').write_text(json.dumps({'rules':{'concept':{'auto_approve_update_confidence':['high']}}}))
        before=target.read_bytes();self.source('a');self.source('b')
        run=self.run_curator();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(target.read_bytes(),before)
        self.assertTrue((self.proposals/'existing-card.md').exists())
        status=json.loads((self.lane/'status.json').read_text())
        self.assertEqual(status['auto_promoted'],0);self.assertEqual(status['auto_promote_failures'],0)

    def test_newly_arrived_owner_draft_is_never_overwritten(self):
        self.source('a');self.concurrent_draft=True
        run=self.run_curator();self.assertNotEqual(run.returncode,0)
        self.assertEqual((self.proposals/'existing-card.md').read_text(),'Owner draft arrived during the model call')
        self.assertEqual(list(self.proposals.glob('.proposal-*')),[])


if __name__=='__main__': unittest.main()
