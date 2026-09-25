"""Progress is observable without changing job outcomes, model requests or locks."""
import fcntl
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from sovereign_hub import progress


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'
        self.p = progress.Progress.start(self.state, 'nightly')

    def read(self):
        return progress.read(self.state, 'nightly')

    def test_live_stage_count_and_last_progress(self):
        self.p.update('judging', current=3, total=50)
        r = self.read()
        self.assertTrue(r['active'])
        self.assertEqual(r['summary'], 'Judging 3/50')
        self.assertGreaterEqual(r['checked_at'], r['last_progress_at'])
        self.assertNotIn('source', self.p.path.read_text())

    def test_lock_polls_are_observations_not_progress(self):
        self.p.update('waiting_model', holder='sov-audit pid 42 since 2026-01-01 01:00:00')
        first = self.read()
        time.sleep(.01)
        self.p.update('waiting_model', holder='curator-run pid 43 since 2026-01-01 01:00:01', advance=False)
        second = self.read()
        self.assertEqual(first['last_progress_at'], second['last_progress_at'])
        self.assertEqual(first['phase_started_at'], second['phase_started_at'])
        self.assertGreater(second['observed_at'], first['observed_at'])
        self.assertEqual(second['holder']['pid'], 43)

    def test_unknown_lock_text_cannot_leak_into_progress(self):
        self.p.update('waiting_model', holder='private source body or credential')
        self.assertNotIn('private', self.p.path.read_text())
        self.assertNotIn('holder', self.read())

    def test_lock_holder_clears_when_work_starts(self):
        self.p.update('waiting_model', holder='sov-audit pid 42 since 2026-01-01 01:00:00')
        self.p.update('judging', current=1, total=2)
        self.assertNotIn('holder', self.read())

    def test_old_worker_cannot_overwrite_new_run(self):
        newer = progress.Progress.start(self.state, 'nightly')
        newer.update('judging', current=1, total=2)
        self.p.update('completed')
        self.assertEqual(self.read()['run_id'], newer.run_id)
        self.assertEqual(self.read()['phase'], 'judging')

    def test_concurrent_writer_is_skipped_instead_of_blocking(self):
        with progress.locked(self.p.path.with_suffix('.lock')):
            self.p.update('judging', current=1, total=2)
        self.assertEqual(self.read()['phase'], 'starting')

    def test_completed_is_not_live(self):
        self.p.update('completed')
        self.assertFalse(self.read()['active'])

    def test_counts_are_scoped_to_the_phase(self):
        self.p.update('judging', current=3, total=50)
        self.p.update('digest')
        self.assertEqual(self.read()['summary'], 'Preparing the digest')
        self.assertIsNone(self.read()['current'])

    def test_pid_reuse_or_process_exit_is_not_live(self):
        for identity in ('', 'different process start'):
            with patch.object(progress, '_process_start', return_value=identity):
                self.assertFalse(self.read()['active'])

    def test_missing_corrupt_and_invalid_records_are_unknown(self):
        baseline = json.loads(self.p.path.read_text())
        for content in ('broken', '[]', json.dumps(dict(baseline, current='private text')),
                        json.dumps(dict(baseline, observed_at=float('nan'))),
                        json.dumps(dict(baseline, phase_started_at=baseline['started_at'] - 1)),
                        json.dumps(dict(baseline, phase='private prompt'))):
            self.p.path.write_text(content)
            self.assertIsNone(self.read())
        self.p.path.unlink()
        self.assertIsNone(self.read())

    def test_write_failure_does_not_change_work(self):
        with patch.object(progress, 'atomic', side_effect=OSError('disk full')):
            self.p.update('judging', current=1, total=2)
            disabled = progress.Progress.start(self.state, 'nightly')
        self.assertIsNone(disabled.path)
        self.assertEqual(self.read()['phase'], 'starting')

    def test_no_opt_in_or_unrelated_job_writes_nothing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(progress.Progress.from_env().path)
        self.assertIsNone(progress.Progress.start(self.state, 'other').path)


class WorkerIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.vault = self.home / 'vault'
        self.state = self.home / 'state'
        self.lane = self.vault / 'raw/workspaces/test'
        self.lane.mkdir(parents=True)
        source = self.vault / 'raw/tools/test/source.md'
        source.parent.mkdir(parents=True)
        source.write_text('---\ntype: capture\nsource: test\n---\n# Example method\nA durable process for handling examples.\n')
        target = self.vault / 'knowledge/concepts/example-method.md'
        target.parent.mkdir(parents=True)
        target.write_text('---\ntype: concept\nsource: test\ncreated: 2020-01-01\n---\n# Example method\nA durable existing method.\n')
        self.bodies, self.observations = [], []
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.bodies.append(body)
                test.observations.append(progress.read(test.state, test.job))
                if test.job == 'weekly-audit':
                    verdict = {'action': 'keep', 'violates': False, 'disagree': False}
                elif 'UPDATE TASK' in body['messages'][-1]['content']:
                    verdict = {'body': 'A durable existing method with another verified step.', 'why': 'Reusable procedure.'}
                elif len(test.bodies) == 2:
                    verdict = {'decision': 'clean'}
                else:
                    verdict = {'promote': True, 'slug': 'example-method', 'type': 'concept',
                               'update_of': 'example-method', 'confidence': 'high',
                               'body': 'A durable existing method with another verified step.', 'reason': 'Reusable procedure.'}
                out = json.dumps({'choices': [{'message': {'content': json.dumps(verdict)}}]}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(out))); self.end_headers()
                self.wfile.write(out)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def environment(self, job):
        self.job = job
        self.record = progress.Progress.start(self.state, job)
        return dict(os.environ, HOME=str(self.home), SOVS_VAULT=str(self.vault), CURATOR_LANE='test',
                    SOV_STATE_DIR=str(self.state), SOV_PROGRESS_JOB=job, SOV_PROGRESS_RUN=self.record.run_id,
                    CURATOR_MODEL='test-local', CURATOR_AUDIT_MODEL='test-local',
                    CURATOR_ENDPOINT='http://127.0.0.1:%d/v1/chat/completions' % self.server.server_port,
                    CURATOR_SCREEN='on', CURATOR_JUDGE_PARALLEL='1', PYTHONDONTWRITEBYTECODE='1',
                    PYTHONPATH=str(ROOT / 'lib'))

    def test_actual_curator_reports_judge_screen_merge_and_save(self):
        done = subprocess.run([sys.executable, str(ROOT/'bin/curator-run'), '--max', '1', '--since-days', '1'],
                              env=self.environment('nightly'), capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([x['phase'] for x in self.observations], ['judging', 'screening', 'merging'])
        self.assertTrue(all(x['current'] == 1 and x['total'] == 1 for x in self.observations))
        self.assertEqual(progress.read(self.state, 'nightly')['phase'], 'saving')
        self.assertTrue((self.lane/'status.json').exists())
        self.assertTrue(all('reasoning_effort' not in b for b in self.bodies))

    def test_actual_audit_reports_quality_and_skip_stages(self):
        (self.lane/'judgments.jsonl').write_text(json.dumps({'promote': False, 'source': 'example', 'excerpt': 'example'})+'\n')
        done = subprocess.run([sys.executable, str(ROOT/'bin/sov-audit'), '--max-screen', '1', '--max-skips', '1'],
                              env=self.environment('weekly-audit'), capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('retro_taste', [x['phase'] for x in self.observations])
        self.assertIn('skip_audit', [x['phase'] for x in self.observations])
        self.assertEqual(progress.read(self.state, 'weekly-audit')['phase'], 'saving')

    def test_actual_curator_exposes_lock_wait_without_calling_model(self):
        env = self.environment('curate')
        lock = self.home / '.local/state/sovs-cron/model.lock'
        lock.parent.mkdir(parents=True)
        with lock.open('w') as fh:
            fh.write('sov-audit pid 42 since 2026-01-01 01:00:00\n'); fh.flush()
            fcntl.flock(fh, fcntl.LOCK_EX)
            process = subprocess.Popen([sys.executable, str(ROOT/'bin/curator-run'), '--max', '1'],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    record = progress.read(self.state, 'curate')
                    if record['phase'] == 'waiting_model':
                        break
                    time.sleep(.02)
                self.assertEqual(record['phase'], 'waiting_model')
                self.assertEqual(record['holder']['worker'], 'sov-audit')
                self.assertEqual(self.bodies, [])
            finally:
                process.terminate(); process.communicate(timeout=5)


class RunnerIntegration(unittest.TestCase):
    def test_child_progress_and_completed_failure_keep_receipt_semantics(self):
        from test_hub_runner import Box
        from sovereign_hub import manifest
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp, patch.dict(manifest.JOBS):
            box = Box(tmp)
            command = ("import os,json; from sovereign_hub.progress import Progress,read; "
                       "p=Progress.from_env(); p.update('judging',current=2,total=3); "
                       "print(json.dumps(read(os.environ['SOV_STATE_DIR'],'nightly')))")
            import shlex
            box.job('nightly', shlex.quote(sys.executable)+' -c '+shlex.quote(command)+'\nexit 3\n')
            with patch.dict(os.environ, PYTHONPATH=str(ROOT/'lib')):
                self.assertEqual(box.tick('nightly'), 3)
            seen = json.loads(box.receipt('nightly', 'last-output'))
            self.assertTrue(seen['active'])
            self.assertEqual(seen['summary'], 'Judging 2/3')
            final = progress.read(box.state, 'nightly')
            self.assertFalse(final['active'])
            self.assertEqual(final['phase'], 'completed')
            self.assertEqual(box.receipt('nightly', 'last-exit').strip(), '3')
            self.assertFalse((box.state/'hub/nightly.last-ok').exists())


if __name__ == '__main__':
    unittest.main()
