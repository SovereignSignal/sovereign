import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
UPD = ROOT / "bin/sov-app-update"
def bundle(path, version, build, commit):
    (path / "Contents").mkdir(parents=True, exist_ok=True)
    d = {"CFBundleShortVersionString": version, "CFBundleVersion": build}
    if commit is not None:
        d["SovereignSourceCommit"] = commit
    (path / "Contents/Info.plist").write_bytes(plistlib.dumps(d))
def commits(checkout):
    subprocess.run(["git", "-C", str(checkout), "init", "-q"], check=True)
    def commit(message):
        subprocess.run(["git", "-C", str(checkout), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", message], check=True)
        return subprocess.run(["git", "-C", str(checkout), "log", "-1", "--format=%h"],
                              capture_output=True, text=True, check=True).stdout.strip()
    return commit
def run(home, *args):
    env = dict(os.environ, HOME=str(home))
    cp = subprocess.run([sys.executable, str(UPD), *args], env=env, capture_output=True, text=True)
    try:
        return cp.returncode, json.loads(cp.stdout or "{}")
    except json.JSONDecodeError:
        return cp.returncode, {"raw": cp.stdout, "err": cp.stderr}
class AppUpdatePreview(unittest.TestCase):
    def test_preview_writes_nothing_and_names_the_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); app = home / "Applications/Sovereign.app"
            bundle(app, "1.0.0", "7", "aaaaaaa")
            before = sorted(p.name for p in (home / "Applications").iterdir())
            code, out = run(home, "--preview")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["state"], "preview")
            self.assertEqual(out["installed"]["build"], "7")
            # A person must be told what happens to the app and their settings.
            self.assertIn("close and reopen", out["effects"])
            self.assertIn("settings", out["effects"])
            self.assertIn("Nothing is installed if the build fails", out["effects"])
            self.assertEqual(sorted(p.name for p in (home / "Applications").iterdir()), before)
    def test_it_says_plainly_when_there_is_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            rev = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h"],
                                 capture_output=True, text=True).stdout.strip()
            bundle(home / "Applications/Sovereign.app", "1.0.0", "7", rev)
            _, out = run(home, "--preview")
            self.assertTrue(out["current"])
            self.assertIn("already the newest", out["summary"])
    def test_a_stale_confirmation_is_refused(self):
        # The token binds a confirmation to the exact state that was shown. Without it a
        # click could apply to a machine that changed underneath the preview.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle(home / "Applications/Sovereign.app", "1.0.0", "7", "aaaaaaa")
            code, out = run(home, "--apply", "--token", "not-the-token")
            self.assertEqual(code, 1)
            self.assertIn("changed since the preview", out["error"])
    def test_apply_refuses_when_there_is_no_bundled_runtime_to_build_with(self):
        # It must fail before touching anything, not halfway through.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); app = home / "Applications/Sovereign.app"
            bundle(app, "1.0.0", "7", "aaaaaaa")
            _, prev = run(home, "--preview")
            code, out = run(home, "--apply", "--token", prev["token"])
            self.assertEqual(code, 1)
            self.assertIn("runtime", out["error"])
            self.assertTrue((app / "Contents/Info.plist").exists(), "the installed app must survive a refusal")
    def test_the_bundles_own_backend_is_not_mistaken_for_a_checkout(self):
        # The app reports machine.template as its BUNDLED backend, because it runs
        # backend/bin/sov-status and that computes the template from where it sits. A UI
        # forwarding that value in good faith asks the app to build itself out of its own
        # bundle, which ships no apps/console. That is what the first real click of
        # Update now did, and the guard has to be in the updater, not in every caller.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle = home / "Applications/Sovereign.app/Contents/Resources/backend"
            (bundle / "bin").mkdir(parents=True)
            bundle_str = str(bundle)
            env = dict(os.environ, HOME=str(home))
            cp = subprocess.run([sys.executable, str(UPD), "--preview", "--template", bundle_str],
                                env=env, capture_output=True, text=True)
            out = json.loads(cp.stdout or "{}")
            self.assertNotEqual(out.get("template"), bundle_str,
                                "a path with no apps/console must never be used as the checkout")
            # It falls through to a real one, or says there is none; never pretends.
            if out.get("template"):
                self.assertTrue(out.get("buildable"), "a resolved template must be able to build")
    def test_apply_builds_from_the_resolved_checkout_not_from_where_the_script_sits(self):
        # The second real click of Update now: the plan resolved a real checkout, then
        # apply() built from TEMPLATE, the directory the script sits in, which inside the
        # app is the bundle and ships no build.sh. Run a copy of the updater from a fake
        # bundle and prove the build is invoked in the checkout the plan chose.
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); app = home / "Applications/Sovereign.app"
            (app / "Contents/Resources/runtime/bin").mkdir(parents=True)
            (app / "Contents/Resources/runtime/bin/python3").write_text("")
            inside = app / "Contents/Resources/backend/bin"; inside.mkdir(parents=True)
            shutil.copy(UPD, inside / "sov-app-update")
            checkout = home / "src"; (checkout / "apps/console").mkdir(parents=True)
            marker = checkout / "build-ran-here"
            (checkout / "apps/console/build.sh").write_text(
                "#!/bin/bash\ntouch '%s'\necho 'stop here' >&2\nexit 1\n" % marker)
            git = commits(checkout)
            bundle(app, "1.0.0", "7", git("older"))
            git("newer")
            env = dict(os.environ, HOME=str(home))
            def go(*args):
                cp = subprocess.run([sys.executable, str(inside / "sov-app-update"), *args],
                                    env=env, capture_output=True, text=True)
                return cp.returncode, json.loads(cp.stdout or "{}")
            _, prev = go("--preview", "--template", str(checkout))
            self.assertEqual(prev.get("template"), str(checkout))
            code, out = go("--apply", "--token", prev["token"], "--template", str(checkout))
            self.assertEqual(code, 1)
            self.assertTrue(marker.exists(), "build.sh in the resolved checkout must be the one that runs: %s" % out)
            self.assertIn("stop here", out["error"])
            self.assertNotIn("No such file", out["error"])
    def test_stdout_only_build_failure_is_reported_without_touching_app(self):
        import runpy
        from unittest.mock import patch
        updater = runpy.run_path(str(UPD))
        apply = updater['apply']
        fake = {'token': 'ok', 'template': '/test/source', 'source_commit': 'abc', 'buildable': True}
        with patch.dict(apply.__globals__, plan=lambda template: fake), \
             patch('os.path.isfile', return_value=True), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess([], 9, 'stdout diagnostic', '')) as run:
            with self.assertRaisesRegex(ValueError, 'exit 9.*stdout diagnostic'):
                apply('ok')
            self.assertEqual(run.call_count, 1, 'failure must stop before quit or installation')

    def test_an_older_or_other_source_is_never_offered_or_installed(self):
        # Unequal is not newer. An app built from a worktree or a later branch differs from an
        # older checkout, and rebuilding that checkout would quietly install an older Sovereign.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); app = home / "Applications/Sovereign.app"
            (app / "Contents/Resources/runtime/bin").mkdir(parents=True)
            (app / "Contents/Resources/runtime/bin/python3").write_text("")
            checkout = home / "src"; (checkout / "apps/console").mkdir(parents=True)
            marker = checkout / "build-ran"
            (checkout / "apps/console/build.sh").write_text("#!/bin/bash\ntouch '%s'\nexit 1\n" % marker)
            git = commits(checkout); older = git("older"); newer = git("newer")
            subprocess.run(["git", "-C", str(checkout), "checkout", "-q", older], check=True)
            for installed in (newer, newer + "+local", "fffffff"):
                bundle(app, "0.6.0", "39", installed)
                _, prev = run(home, "--preview", "--template", str(checkout))
                self.assertTrue(prev["current"], installed); self.assertIn("nothing newer", prev["summary"])
                code, out = run(home, "--apply", "--token", prev["token"], "--template", str(checkout))
                self.assertEqual(code, 1); self.assertIn("nothing newer", out["error"])
                self.assertFalse(marker.exists(), "an older source must never be built over a newer app")
            bundle(app, "0.5.16", "38", older)
            subprocess.run(["git", "-C", str(checkout), "checkout", "-q", newer], check=True)
            _, prev = run(home, "--preview", "--template", str(checkout))
            self.assertFalse(prev["current"]); self.assertIn("Build Sovereign", prev["summary"])
    def test_an_absent_app_still_previews_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), "--preview")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["installed"], {})
            self.assertFalse(out["current"])
if __name__ == "__main__":
    unittest.main()
