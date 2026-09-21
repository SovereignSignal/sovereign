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
    def test_an_absent_app_still_previews_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), "--preview")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["installed"], {})
            self.assertFalse(out["current"])
if __name__ == "__main__":
    unittest.main()
