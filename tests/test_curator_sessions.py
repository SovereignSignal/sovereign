"""Session captures are always screened and never ride a gear.

Runs the real curator against a temp vault and a loopback model. The judge
promotes every source as a high-confidence new concept, gears.json grants high
new concepts, and CURATOR_SCREEN is empty, so a non-session source lands on its
own while a capture under raw/tools/<lane>/sessions/ is screened anyway and
stays in proposals/ for the owner.
"""
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
SESSION = 'raw/tools/claude-code-h/sessions/x.md'
MEMORY = 'raw/tools/claude-code-h/memory/y.md'
HOLD = 'session capture: new input class, ask-first until it earns its own record'


class SessionCaptures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.vault = self.home/'vault'
        (self.vault/'knowledge/concepts').mkdir(parents=True)
        self.lane = self.vault/'raw/workspaces/test'
        self.proposals = self.lane/'proposals'
        self.proposals.mkdir(parents=True)
        (self.lane/'gears.json').write_text(json.dumps(
            {'rules': {'concept': {'auto_approve_confidence': ['high']}}}))
        self.screen_reply = 'flagged'   # 'flagged', 'clean' or 'down'
        self.reject_class = None
        self.shared_slug = None          # every source drafts this slug when set
        self.screens, self.judged, self.merges = [], [], []
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                system = payload['messages'][0]['content']
                text = payload['messages'][-1]['content']
                if system.startswith('You are a security boundary classifier'):
                    test.screens.append(text)
                    if test.screen_reply == 'down':
                        self.send_response(500); self.end_headers(); return
                    result = {'decision': test.screen_reply, 'reason': 'synthetic screen'}
                elif text.startswith('UPDATE TASK'):
                    test.merges.append(text)
                    result = {'body': 'A durable idea, merged.', 'title': 'Merged', 'why': 'Both matter'}
                else:
                    m = re.search(r'SOURCE: (\S+)', text)
                    src = m.group(1) if m else '?'
                    test.judged.append(src)
                    stem = Path(src).stem
                    result = {'promote': True, 'slug': test.shared_slug or 'topic-' + stem,
                              'type': 'concept',
                              'title': 'Topic ' + stem, 'confidence': 'high', 'update_of': None,
                              'auto_reject_class': test.reject_class,
                              'body': 'A durable idea from ' + stem + '.', 'reason': 'Useful'}
                raw = json.dumps({'choices': [{'message': {'content': json.dumps(result)}}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(raw)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def place(self, rel, age=0):
        path = self.vault/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\ntype: capture\nsource: test\n---\n# Note\nA durable idea.\n')
        stamp = time.time() + 10 - age
        os.utime(path, (stamp, stamp))
        return path

    def run_curator(self):
        env = dict(os.environ, HOME=str(self.home), SOVS_VAULT=str(self.vault),
                   CURATOR_LANE='test', CURATOR_SCREEN='', CURATOR_JUDGE_PARALLEL='1',
                   ARCHIVIST_AUTO_PROMOTE_MAX='12',
                   CURATOR_ENDPOINT='http://127.0.0.1:%d/v1/chat/completions' % self.server.server_port)
        for key in ('CURATOR_INCLUDE', 'CURATOR_EXCLUDE', 'SOV_PROGRESS_JOB', 'SOV_PROGRESS_RUN',
                    'CURATOR_PROVIDER', 'CURATOR_BACKEND', 'CURATOR_MODEL', 'CURATOR_SCREEN_MODEL',
                    'ARCHIVIST_AUTO_REJECT_MAX', 'CURATOR_AUTOREJECT'):
            env.pop(key, None)
        run = subprocess.run([sys.executable, str(ROOT/'bin/curator-run'), '--max', '10'],
                             env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run

    def meta(self):
        return json.loads((self.proposals/'.meta.json').read_text())

    def rows(self):
        return [json.loads(s) for s in (self.lane/'judgments.jsonl').read_text().splitlines()]

    def status(self):
        return json.loads((self.lane/'status.json').read_text())

    def test_flagged_session_capture_is_screened_and_held(self):
        self.place(SESSION)
        run = self.run_curator()
        self.assertEqual(len(self.screens), 1)
        self.assertIn('[SCREENED]', run.stdout)
        self.assertTrue((self.proposals/'topic-x.md').exists())
        self.assertEqual(list((self.vault/'knowledge/concepts').glob('*.md')), [])
        meta = self.meta()['topic-x']
        self.assertEqual(meta['input_class'], 'session')
        self.assertTrue(meta['screen_flagged'])
        row = [r for r in self.rows() if r['source'] == SESSION][0]
        self.assertEqual(row['input_class'], 'session')
        self.assertTrue(row['screen_flagged'])
        self.assertEqual(self.status()['auto_promoted'], 0)

    def test_unreachable_screener_flags_the_session_capture(self):
        self.screen_reply = 'down'
        self.place(SESSION)
        self.run_curator()
        meta = self.meta()['topic-x']
        self.assertTrue(meta['screen_flagged'])
        self.assertIn('screener unavailable', meta['screen_reason'])
        self.assertEqual(self.status()['auto_promoted'], 0)

    def test_clean_session_capture_stays_pending_while_other_source_lands(self):
        self.screen_reply = 'clean'
        self.place(SESSION)
        self.place(MEMORY)
        self.run_curator()
        self.assertEqual(sorted(self.judged), sorted([MEMORY, SESSION]))
        # only the session capture is screened; CURATOR_SCREEN is still off for the rest
        self.assertEqual(len(self.screens), 1)
        self.assertIn('A durable idea', self.screens[0])
        self.assertTrue((self.proposals/'topic-x.md').exists())
        self.assertFalse((self.proposals/'topic-y.md').exists())
        self.assertTrue((self.vault/'knowledge/concepts/topic-y.md').exists())
        self.assertFalse((self.vault/'knowledge/concepts/topic-x.md').exists())
        meta = self.meta()
        self.assertEqual(meta['topic-x']['input_class'], 'session')
        self.assertFalse(meta['topic-x']['screen_flagged'])
        rows = {r['source']: r for r in self.rows()}
        self.assertEqual(rows[SESSION]['input_class'], 'session')
        self.assertNotIn('input_class', rows[MEMORY])
        self.assertEqual(self.status()['auto_promoted'], 1)
        self.assertIn(HOLD, (self.lane/'INBOX.md').read_text())

    def test_session_capture_never_rides_the_auto_reject_policy(self):
        self.screen_reply = 'clean'
        self.reject_class = 'news-no-engagement'
        (self.lane/'auto-reject.md').write_text('- `news-no-engagement`: always dropped\n')
        (self.lane/'gears.json').write_text(json.dumps({'rules': {}}))
        self.place(SESSION)
        self.place(MEMORY)
        self.run_curator()
        self.assertTrue((self.proposals/'topic-x.md').exists())
        self.assertFalse((self.proposals/'topic-y.md').exists())
        self.assertEqual(self.status()['auto_rejected'], 1)

    def test_session_manifest_is_never_gathered(self):
        self.screen_reply = 'clean'
        manifest = 'raw/tools/claude-code-h/sessions/MANIFEST.md'
        self.place(manifest)
        self.place(SESSION)
        self.run_curator()
        self.assertEqual(self.judged, [SESSION])
        self.assertNotIn(manifest, [r['source'] for r in self.rows()])
        self.assertEqual(self.status()['coverage']['processable'], 1)

    def consolidate(self, session_first):
        # candidates are judged newest first, so the younger file drafts first and
        # the older one consolidates onto it
        self.screen_reply = 'clean'
        self.shared_slug = 'shared-topic'
        self.place(SESSION, age=0 if session_first else 5)
        self.place(MEMORY, age=5 if session_first else 0)
        self.run_curator()
        self.assertEqual(self.judged[:2], [SESSION, MEMORY] if session_first else [MEMORY, SESSION])
        self.assertEqual(len(self.merges), 1)
        self.assertEqual([p.name for p in self.proposals.glob('*.md')], ['shared-topic.md'])
        self.assertEqual(list((self.vault/'knowledge/concepts').glob('*.md')), [])
        meta = self.meta()['shared-topic']
        self.assertEqual(meta['input_class'], 'session')
        self.assertEqual(sorted(r['source'] for r in meta['source_refs']), sorted([MEMORY, SESSION]))
        self.assertEqual(self.status()['auto_promoted'], 0)

    def test_session_draft_then_other_source_stays_session(self):
        self.consolidate(session_first=True)

    def test_other_draft_then_session_source_becomes_session(self):
        self.consolidate(session_first=False)


if __name__ == '__main__':
    unittest.main()
