"""Build 45: the first loop on a clean Mac (connect, curate on Claude, see a card reach a session)."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'connectors' / 'harness' / '_lib'))
import brain_local as local
import brainhook


class PythonResolver(unittest.TestCase):
    """bin/_sov-python.sh: the app's own runtime is used when the template is its backend."""

    def resolve(self, template, env=None):
        script = '. "%s/bin/_sov-python.sh"; p="$(sov_python "$1")"; echo "$p"; sov_python_is_bundled "$p" && echo bundled || echo plain'
        e = {'PATH': '/usr/bin:/bin', 'SOV_CLT_PYTHON': '/nonexistent/python3', **(env or {})}
        out = subprocess.run(['/bin/bash', '-c', script % ROOT, '_', str(template)], env=e,
                             capture_output=True, text=True, check=True).stdout.split()
        return out

    def test_app_backend_uses_bundled_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Path(tmp) / 'Sovereign.app/Contents/Resources'
            py = res / 'runtime/bin/python3'; py.parent.mkdir(parents=True); py.write_text('#!/bin/sh\n'); py.chmod(0o755)
            (res / 'backend').mkdir()
            path, kind = self.resolve(res / 'backend')
            self.assertEqual(path, str(py.resolve()))
            self.assertEqual(kind, 'bundled')

    def test_explicit_choice_still_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Path(tmp) / 'Sovereign.app/Contents/Resources'
            py = res / 'runtime/bin/python3'; py.parent.mkdir(parents=True); py.write_text(''); py.chmod(0o755)
            self.assertEqual(self.resolve(res / 'backend', {'SOV_PYTHON': '/opt/py/bin/python3'}), ['/opt/py/bin/python3', 'plain'])

    def test_operator_checkout_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.resolve(Path(tmp) / 'sovs-brain-template'), ['/usr/bin/python3', 'plain'])


class NewestCards(unittest.TestCase):
    def test_fresh_archive_core_is_its_newest_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, sub in enumerate(('concepts', 'entities', 'syntheses', 'concepts')):
                p = root / 'knowledge' / sub / f'card-{i}.md'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('x')
                os.utime(p, (1_000_000 + i, 1_000_000 + i))
            (root / 'knowledge/concepts/.hidden.md').write_text('x')
            self.assertEqual(brainhook.newest_cards(str(root), 3), 'card-3,card-2,card-1')

    def test_empty_archive_has_no_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(brainhook.newest_cards(tmp), '')


class ReceiptNamesCards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'archive'
        local.create(self.root, ROOT)
        self.root = local.archive_root(self.root)

    def test_receipt_written_with_slugs_is_read_back(self):
        # BRAIN_STAGE pins the receipt into this fixture; without it a Mac with a real
        # ~/.vault-staging would receive it (and its relay would carry it into a vault).
        from unittest import mock
        with mock.patch.dict(os.environ, {'BRAIN_STAGE': str(self.root), 'BRAIN_LANE': '', 'HOME': self.tmp.name}):
            self._receipt_round_trip()

    def _receipt_round_trip(self):
        brainhook.receipt(str(self.root), 'claude-code-test', 'core', 'core', '2', 'abcd1234ef', 'startup',
                          ['owner-prefers-terse', 'garden-planner', 'bad slug!'])
        line = (self.root / 'raw/tools/claude-code-test/brain-load-usage.md').read_text().splitlines()[-1]
        self.assertTrue(line.endswith(' session=abcd1234 slugs=owner-prefers-terse,garden-planner'), line)
        got = local.context_state(self.root)['receipts'][0]
        self.assertEqual(got['slugs'], ['owner-prefers-terse', 'garden-planner'])
        self.assertFalse(got['test'])

    def test_older_receipts_still_parse(self):
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%MZ')
        p = self.root / 'raw/tools/example/brain-load-usage.md'; p.parent.mkdir(parents=True)
        p.write_text(f'- {stamp} core scope=core cards=3 source=startup session=abcd1234\n')
        got = local.context_state(self.root)['receipts'][0]
        self.assertEqual(got['slugs'], [])
        self.assertEqual(got['cards'], '3')


class CuratorCommand(unittest.TestCase):
    """bin/sov-curator: refuses on a hub, never takes a malformed key, pins every gear shut."""

    def run_curator(self, *args, env=None, home=None):
        e = {'PATH': '/usr/bin:/bin', 'HOME': home, 'SOV_STATE_DIR': str(Path(home) / 'state'), **(env or {})}
        return subprocess.run([sys.executable, str(ROOT / 'bin/sov-curator'), *args], env=e, capture_output=True, text=True)

    def test_refuses_on_a_hub(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            (Path(home) / '.sovereign-hub').write_text('')
            r = self.run_curator('run', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('runs a hub', r.stderr)

    def test_rejects_a_key_that_is_not_anthropic(self):
        with tempfile.TemporaryDirectory() as home:
            r = self.run_curator('key', env={'SOV_CURATOR_KEY': 'not-a-key'}, home=home)
            self.assertEqual(r.returncode, 65)

    def test_job_pins_both_caps_to_zero_and_names_claude(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader('sov_curator', str(ROOT / 'bin/sov-curator'))
        spec = importlib.util.spec_from_loader('sov_curator', loader)
        mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
        env = mod.curator_env(Path('/tmp/archive'))
        self.assertEqual(env['CURATOR_BACKEND'], 'anthropic')
        self.assertEqual(env['ARCHIVIST_AUTO_PROMOTE_MAX'], '0')
        self.assertEqual(env['ARCHIVIST_AUTO_REJECT_MAX'], '0')
        self.assertEqual(env['CURATOR_SCREEN'], 'on')
        self.assertNotIn('CURATOR_KEY', env)

    def test_an_owner_profile_is_never_overwritten(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader('sov_curator2', str(ROOT / 'bin/sov-curator'))
        spec = importlib.util.spec_from_loader('sov_curator2', loader)
        mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lane = root / 'raw/workspaces/curator'; lane.mkdir(parents=True)
            (lane / 'profile.md').write_text('I am a grant writer.')
            mod.seed_profile(root)
            self.assertEqual((lane / 'profile.md').read_text(), 'I am a grant writer.')
            (lane / 'profile.md').unlink(); mod.seed_profile(root)
            self.assertIn('This archive is new', (lane / 'profile.md').read_text())

    def test_dry_enable_installs_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            r = self.run_curator('enable', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('dry run', r.stdout)
            self.assertFalse((Path(home) / 'Library/LaunchAgents/com.sovereign.curator.plist').exists())


    def test_trust_grants_act_and_report_and_off_restores_the_zero_cap(self):
        import importlib.machinery, importlib.util
        from unittest import mock
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            gears_path = root / 'raw/workspaces/curator/gears.json'
            state_file = Path(home) / 'state/curator-trust.json'
            r = self.run_curator('trust', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('dry run', r.stdout)
            self.assertFalse(gears_path.exists()); self.assertFalse(state_file.exists())
            r = self.run_curator('trust', '--apply', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('granted', r.stdout)
            gears = json.loads(gears_path.read_text())
            for typ in ('concept', 'synthesis'):
                self.assertEqual(gears[typ]['auto_approve_confidence'], ['high', 'med'])
                self.assertEqual(gears[typ]['auto_approve_update_confidence'], ['high', 'med'])
            self.assertNotIn('entity', gears)
            self.assertTrue(json.loads(state_file.read_text())['act_and_report'])
            with mock.patch.dict(os.environ, {'SOV_STATE_DIR': str(Path(home) / 'state')}):
                loader = importlib.machinery.SourceFileLoader('sov_curator3', str(ROOT / 'bin/sov-curator'))
                spec = importlib.util.spec_from_loader('sov_curator3', loader)
                mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
                env = mod.curator_env(root)
            self.assertEqual(env['ARCHIVIST_AUTO_PROMOTE_MAX'], '12')
            self.assertEqual(env['ARCHIVIST_AUTO_REJECT_MAX'], '0')
            r = self.run_curator('trust', '--off', '--apply', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(json.loads(state_file.read_text())['act_and_report'])
            self.assertTrue(gears_path.exists())  # the zero cap disables it; the grant stays on record


    def test_status_reports_when_background_landing_has_been_earned(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            lane = root / 'raw/workspaces/curator'; lane.mkdir(parents=True, exist_ok=True)
            folders = {'concept': 'concepts', 'synthesis': 'syntheses', 'entity': 'entities'}
            tick = [0]

            def event(slug, typ, confidence, verdict, actor, when):
                tick[0] += 10
                judged = when + timedelta(seconds=tick[0])
                decided = judged + timedelta(seconds=1)
                with open(lane / 'judgments.jsonl', 'a') as f:
                    f.write(json.dumps({'timestamp': judged.isoformat(), 'promote': True,
                                        'slug': slug, 'type': typ, 'confidence': confidence}) + '\n')
                detail = f'knowledge/{folders[typ]}/{slug}.md: owner' if verdict == 'approved' else 'owner verdict'
                with open(lane / 'decisions.log', 'a') as f:
                    f.write('\t'.join([decided.strftime('%Y-%m-%dT%H:%M:%S%z'), verdict,
                                       slug + '.md', actor, detail]) + '\n')
                return decided

            def record():
                r = self.run_curator('status', '--json', env={'SOVS_VAULT': str(root)}, home=home)
                self.assertEqual(r.returncode, 0, r.stderr)
                return json.loads(r.stdout)['trust_record']

            now = datetime.now(timezone.utc).replace(microsecond=0)
            for i in range(9):
                event(f'routine-{i}', 'concept' if i % 2 else 'synthesis',
                      'high' if i % 2 else 'med', 'approved', 'console-owner', now - timedelta(days=3))
            got = record()
            self.assertEqual((got['clean_streak'], got['eligible']), (9, False))
            event('a-person', 'entity', 'high', 'approved', 'console-owner', now - timedelta(days=3))
            event('routine-9', 'concept', 'high', 'approved', 'console-owner', now - timedelta(days=3))
            got = record()
            self.assertEqual((got['clean_streak'], got['eligible'], got['routine_approved']), (10, True, 10))
            event('routine-no', 'synthesis', 'med', 'rejected', 'console-owner', now - timedelta(days=3))
            got = record()
            self.assertEqual((got['clean_streak'], got['eligible'], got['routine_rejected']), (0, False, 1))

    def test_status_reports_recent_background_landings_and_reverts(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            lane = root / 'raw/workspaces/curator'; lane.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc).replace(microsecond=0)

            def land(slug, when):
                with open(lane / 'judgments.jsonl', 'a') as f:
                    f.write(json.dumps({'timestamp': when.isoformat(), 'promote': True, 'slug': slug,
                                        'type': 'concept', 'confidence': 'high'}) + '\n')
                with open(lane / 'decisions.log', 'a') as f:
                    f.write('\t'.join([(when + timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S%z'),
                                       'approved', slug + '.md', 'auto-gear',
                                       f'knowledge/concepts/{slug}.md: act-and-report']) + '\n')

            land('too-old', now - timedelta(days=40))
            land('kept-card', now - timedelta(days=2))
            land('wrong-card', now - timedelta(days=1))
            with open(lane / 'decisions.log', 'a') as f:
                f.write('\t'.join([now.strftime('%Y-%m-%dT%H:%M:%S%z'), 'retired',
                                   'wrong-card.md', 'console-owner', 'not durable']) + '\n')
            r = self.run_curator('status', '--json', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = json.loads(r.stdout)['trust_record']
            self.assertEqual((got['auto_landed_30d'], got['auto_reverted_30d']), (2, 1))
            self.assertEqual([x['slug'] for x in got['recent_auto_landed']], ['wrong-card', 'kept-card'])
            self.assertTrue(got['recent_auto_landed'][0]['reverted'])


    def test_retire_only_moves_a_recent_background_landing(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            lane = root / 'raw/workspaces/curator'; lane.mkdir(parents=True, exist_ok=True)
            card = root / 'knowledge/concepts/background-card.md'; card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text('---\ntype: concept\nsource: test\ncreated: 2026-10-18\n---\n\n**Why this matters:** Test.\n')
            r = self.run_curator('trust', '--apply', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            (lane / 'judgments.jsonl').write_text(json.dumps({
                'timestamp': (now - timedelta(seconds=2)).isoformat(), 'promote': True,
                'slug': 'background-card', 'type': 'concept', 'confidence': 'high'}) + '\n')
            (lane / 'decisions.log').write_text('\t'.join([
                (now - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S%z'), 'approved',
                'background-card.md', 'auto-gear', 'knowledge/concepts/background-card.md: act-and-report']) + '\n')
            r = self.run_curator('retire', 'background-card', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('dry run', r.stdout); self.assertTrue(card.exists())
            r = self.run_curator('retire', 'background-card', '--apply', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertFalse(card.exists())
            self.assertTrue((lane / 'rejected/background-card.md').exists())
            self.assertIn('\tretired\tbackground-card.md\tconsole-owner\t', (lane / 'decisions.log').read_text())
            r = self.run_curator('retire', 'background-card', '--apply', env={'SOVS_VAULT': str(root)}, home=home)
            self.assertNotEqual(r.returncode, 0)


class AnthropicBackendOffline(unittest.TestCase):
    """curator-run on the anthropic backend, with the network replaced by a stub."""

    STUB = '''
import io, json, os, urllib.request
def _fake(req, *a, **k):
    body = json.loads(req.data); hdr = {k.lower(): v for k, v in req.header_items()}
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps({"url": req.full_url, "key": hdr.get("x-api-key"), "version": hdr.get("anthropic-version"),
                            "auth": "authorization" in hdr, "system": bool(body.get("system")),
                            "roles": [m["role"] for m in body["messages"]], "json_mode": "response_format" in body,
                            "sampling": sorted(k for k in ("temperature", "top_p", "top_k") if k in body),
                            "thinking": body.get("thinking"), "max_tokens": body.get("max_tokens"),
                            "effort": (body.get("output_config") or {}).get("effort"),
                            "fallbacks": body.get("fallbacks"), "beta": hdr.get("anthropic-beta")}) + "\\n")
    # Shapes the real API refuses with a 400 fail here too, so this stand-in cannot pass a
    # request Claude would reject (2026-10-15: temperature reached the real API that way).
    if any(k in body for k in ("temperature", "top_p", "top_k")):
        raise ValueError("HTTP 400: sampling parameters are deprecated for this model")
    if "security boundary classifier" in body.get("system", ""):
        text = '{"decision":"clean"}'
    else:
        text = json.dumps({"promote": True, "reason": "a working preference", "type": "concept", "slug": "prefers-terse",
                           "title": "Prefers terse answers", "body": "The owner prefers short answers.",
                           "why": "Shapes every reply.", "confidence": "high", "update_of": None})
    return io.BytesIO(json.dumps({"content": [{"type": "text", "text": text}]}).encode())
urllib.request.urlopen = _fake
urllib.request.OpenerDirector.open = lambda self, req, *a, **k: _fake(req)
'''

    def test_capture_becomes_a_proposal_that_waits_for_the_owner(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            src = root / 'raw/tools/notes/pref.md'; src.parent.mkdir(parents=True)
            src.write_text('---\ntype: capture\nsource: test\ncreated: 2026-10-13\n---\n\nI prefer terse answers.\n')
            stub = Path(home) / 'stub'; stub.mkdir(); (stub / 'sitecustomize.py').write_text(self.STUB)
            log = Path(home) / 'calls.jsonl'
            env = {'PATH': '/usr/bin:/bin', 'HOME': home, 'PYTHONPATH': f'{stub}:{ROOT / "lib"}', 'STUB_LOG': str(log),
                   'SOVS_VAULT': str(root), 'CURATOR_LANE': 'curator', 'CURATOR_BACKEND': 'anthropic',
                   'CURATOR_KEY': 'sk-ant-test', 'CURATOR_SCREEN': 'on', 'ARCHIVIST_AUTO_PROMOTE_MAX': '0'}
            r = subprocess.run([sys.executable, str(ROOT / 'bin/curator-run'), '--max', '5'], env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            calls = [json.loads(l) for l in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)  # the injection screen, then the judge
            for c in calls:
                self.assertEqual(c['sampling'], [])              # current Claude models 400 on these
                self.assertIsNone(c['thinking'])                 # always on; effort sets the depth
                self.assertIn(c['effort'], ('low', 'medium', 'high', 'xhigh', 'max'))
                self.assertGreaterEqual(c['max_tokens'], 16000)  # room for thinking and the card
                self.assertEqual(c['fallbacks'], 'default')
                self.assertEqual(c['beta'], 'server-side-fallback-2026-07-01')
                self.assertEqual(c['url'], 'https://api.anthropic.com/v1/messages')
                self.assertEqual(c['key'], 'sk-ant-test')
                self.assertEqual(c['version'], '2023-06-01')
                self.assertFalse(c['auth'])
                self.assertFalse(c['json_mode'])
                self.assertTrue(c['system'])
                self.assertEqual(c['roles'], ['user'])
            self.assertTrue((root / 'raw/workspaces/curator/proposals/prefers-terse.md').exists())
            self.assertFalse(list((root / 'knowledge').rglob('prefers-terse.md')))

    def test_local_only_archive_refuses_the_hosted_backend(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / 'a'; local.create(root, ROOT)
            env = {'PATH': '/usr/bin:/bin', 'HOME': home, 'PYTHONPATH': str(ROOT / 'lib'), 'SOVS_VAULT': str(root),
                   'CURATOR_BACKEND': 'anthropic', 'CURATOR_KEY': 'sk-ant-test', 'CURATOR_LOCAL_ONLY': '1'}
            r = subprocess.run([sys.executable, str(ROOT / 'bin/curator-run'), '--max', '1'], env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 4)
            self.assertIn('local-only', r.stderr)


if __name__ == '__main__':
    unittest.main()


class CleanMacFlow(unittest.TestCase):
    """The whole first loop as the app's bundle runs it, on a Mac where python3 and git are
    Apple's developer-tools shims. Traps stand in for both: any call that would reach the
    shim (and open the installer on a real clean Mac) is recorded and fails the test."""

    def test_first_loop_never_reaches_the_developer_tools_shims(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); home = tmp / 'home'; home.mkdir()
            res = tmp / 'Sovereign.app/Contents/Resources'
            backend = res / 'backend'; backend.mkdir(parents=True)
            for name in ('bin', 'lib', 'connectors', 'templates'):
                shutil.copytree(ROOT / name, backend / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copy(ROOT / 'CLAUDE.md', backend / 'CLAUDE.md')
            (res / 'runtime/bin').mkdir(parents=True)
            (res / 'runtime/bin/python3').symlink_to(sys.executable)
            trap, log = tmp / 'trap', tmp / 'shim-calls.log'; trap.mkdir()
            for tool in ('python3', 'git', 'xcrun'):
                t = trap / tool
                t.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\nexit 1\n'); t.chmod(0o755)
            ok = trap / 'launchctl-ok'; ok.write_text('#!/bin/sh\nexit 0\n'); ok.chmod(0o755)
            stub = tmp / 'stub'; stub.mkdir()
            (stub / 'sitecustomize.py').write_text(AnthropicBackendOffline.STUB.replace('prefers-terse', 'garden-planner'))
            env = {'HOME': str(home), 'PATH': f'{trap}:/usr/bin:/bin:/usr/sbin:/sbin', 'USER': 'newcomer',
                   'SOV_STATE_DIR': str(home / '.local/state/sovereign'), 'SOV_LAUNCHCTL': str(ok),
                   'PYTHONPATH': str(stub), 'STUB_LOG': str(tmp / 'api-calls.jsonl'), 'CURATOR_KEY': 'sk-ant-test'}
            sov = [str(backend / 'bin/sov')]
            def run(args, **kw):
                r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=300, **kw)
                return r
            archive = home / 'Archive'
            r = run([str(res / 'runtime/bin/python3'), str(backend / 'bin/sov-local')],
                    input=json.dumps({'action': 'create', 'root': str(archive)}))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = run(sov + ['connect', 'claude-code', '--vault', str(archive), '--host', 'newmac', '--apply'])
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
            import plistlib
            job = plistlib.loads((home / 'Library/LaunchAgents/com.sovereign.connector.runner.plist').read_bytes())
            self.assertEqual(job.get('AssociatedBundleIdentifiers'), ['com.sovereign.console'])  # shown as Sovereign
            self.assertTrue(job['EnvironmentVariables']['PATH'].split(':')[0].endswith('/Contents/Resources/backend/bin/git-guard'), job['EnvironmentVariables']['PATH'])
            memory = home / '.claude/projects/-Users-newcomer-garden/memory'; memory.mkdir(parents=True)
            (memory / 'garden.md').write_text('---\nname: garden\n---\n\nI am building a garden planner app.\n')
            r = run(sov + ['curator', 'run'], cwd=str(home))
            profile = archive / 'raw/workspaces/curator/profile.md'
            self.assertIn('This archive is new', profile.read_text())   # the starter owner profile
            proposals = list((archive / 'raw/workspaces/curator/proposals').glob('*.md'))
            self.assertTrue(proposals, r.stdout[-3000:] + r.stderr[-3000:])
            r = run(sov + ['gate', 'approve', str(proposals[0]), 'first card'])
            self.assertTrue(list((archive / 'knowledge').rglob(proposals[0].name)), r.stdout + r.stderr)
            settings = json.loads((home / '.claude/settings.json').read_text())
            hook = [h['command'] for g in settings['hooks']['SessionStart'] for h in g['hooks']][0]
            self.assertIn('runtime/bin/python3', hook)
            r = run(['/bin/bash', '-c', hook], input=json.dumps({'cwd': str(archive), 'session_id': 'firstrun1', 'source': 'startup'}))
            self.assertIn('garden-planner', r.stdout, r.stderr[-2000:])  # the approved card reached the session
            self.assertFalse(log.exists() and log.read_text().strip(),
                             'reached a developer-tools shim: ' + (log.read_text() if log.exists() else ''))
