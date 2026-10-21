import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
UPD = ROOT / "bin/sov-app-update"
def bundle(path, version, build, commit):
    (path / "Contents").mkdir(parents=True, exist_ok=True)
    d = {"CFBundleIdentifier": "com.sovereign.console", "CFBundleShortVersionString": version, "CFBundleVersion": build}
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
def embed(app, script):
    """Ship a copy of script inside app the way build.sh does: backend/bin beside backend/lib.

    A copy, not a symlink, because the updater locates its bundle from its own realpath,
    and a symlink would resolve back into this checkout."""
    inside = app / "Contents/Resources/backend/bin"; inside.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(script), str(inside / Path(script).name))
    lib = app / "Contents/Resources/backend/lib"
    if not lib.exists():
        lib.symlink_to(ROOT / "lib")
    return inside
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
            inside = embed(app, UPD)
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
        # In process, APP is wherever this machine keeps its app; never ask about it here.
        with patch.dict(apply.__globals__, plan=lambda template: fake, check_writable=lambda: None), \
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
    def test_status_says_behind_only_when_the_source_holds_the_installed_build(self):
        # Today and Settings call a differing build "a newer version"; status must say which.
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("sov_status_app_update", str(ROOT / "bin/sov-status"))
        status = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(status)
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp); git = commits(checkout); older = git("older"); newer = git("newer")
            status.TEMPLATE_ROOT = str(checkout)
            self.assertTrue(status._behind(older, newer + " 2026-10-04"))
            self.assertIsNone(status._behind(newer + "+local", newer + " 2026-10-04"), "equal is current, not behind")
            subprocess.run(["git", "-C", str(checkout), "checkout", "-q", older], check=True)
            self.assertFalse(status._behind(newer, older + " 2026-10-04"))
            self.assertFalse(status._behind("fffffff", older + " 2026-10-04"))
            # A stamp that is not a commit (build.sh writes "unknown" when git fails) is no
            # stamp: nothing to compare, so the app still offers the update that stamps it.
            for stamp in ("--output=x", "unknown", "unknown+local", None):
                self.assertIsNone(status._behind(stamp, older + " 2026-10-04"), stamp)
    def test_a_build_stamped_unknown_can_still_be_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); checkout = home / "src"; (checkout / "apps/console").mkdir(parents=True)
            (checkout / "apps/console/build.sh").write_text("#!/bin/bash\nexit 1\n")
            commits(checkout)("only")
            for stamp in ("unknown", "unknown+local"):
                bundle(home / "Applications/Sovereign.app", "0.6.0", "39", stamp)
                _, prev = run(home, "--preview", "--template", str(checkout))
                self.assertFalse(prev["current"], stamp); self.assertIn("Build Sovereign", prev["summary"])
    def test_an_absent_app_still_previews_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), "--preview")
            self.assertEqual(code, 0, out)
        # /Applications is outside any temp HOME, so name both folders to get the same
        # answer on every machine, including one that has Sovereign installed there.
        import runpy
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / "lib"))
        import sovereign_app
        with tempfile.TemporaryDirectory() as tmp:
            mine, system = Path(tmp) / "home/Applications", Path(tmp) / "Applications"
            with patch.object(sovereign_app, "ROOTS", (str(mine), str(system))):
                p = runpy.run_path(str(UPD))["plan"]()
            self.assertEqual(p["installed"], {})
            self.assertFalse(p["current"])
            self.assertEqual(p["app_path"], str(mine / "Sovereign.app"),
                             "a fresh install goes to the home folder's Applications")
def release_app(path, version, build, bundle_id="com.sovereign.console"):
    (path / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
    (path / "Contents/Info.plist").write_bytes(plistlib.dumps(
        {"CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": version, "CFBundleVersion": build}))
    (path / "Contents/MacOS/Sovereign").write_text("build %s\n" % build)
def stub(path, body):
    path.write_text("#!/bin/sh\n%s\n" % body)
    path.chmod(0o755)
    return path
class ReleaseUpdate(unittest.TestCase):
    """The second source: the latest GitHub release, checked before anything is replaced.

    Every case runs against a fake release on disk (SOV_UPDATE_FEED) and a stub in place
    of Apple's verification (SOV_UPDATE_VERIFY), with HOME, open and pgrep all fake, so
    no test reaches the network or an installed app.
    """
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); root = Path(self._tmp.name)
        self.home = root / "home"; self.rel = root / "release"; self.bin = root / "bin"
        for d in (self.home, self.rel, self.bin):
            d.mkdir()
        self.opened = root / "opened"
        stub(self.bin / "open", 'echo "$@" >> "%s"' % self.opened)
        stub(self.bin / "pgrep", "exit 1")
        self.ok = stub(root / "verify-ok", "exit 0")
        self.no = stub(root / "verify-no", 'echo "signed by someone else" >&2; exit 1')
        self.app = self.home / "Applications/Sovereign.app"
        release_app(self.app, "0.7.1", "50")
        self.plist = (self.app / "Contents/Info.plist").read_bytes()
        self.updates = self.home / "Library/Caches/Sovereign/updates"
    def tearDown(self):
        self._tmp.cleanup()
    def publish(self, version, build, bundle_id="com.sovereign.console", plist=None,
                tamper=False, drop=(), url=None, prepare=None):
        """A release as GitHub serves it: the zip, its .sha256, and the latest-release feed."""
        name = "Sovereign-%s-build%s.zip" % (version, build)
        stage = self.rel / ("stage-" + name); app = stage / "Sovereign.app"
        release_app(app, *(plist or (version, build)), bundle_id=bundle_id)
        if prepare:
            prepare(app)
        z = self.rel / name
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(z)], check=True)
        sha = self.rel / (name + ".sha256")
        sha.write_text("%s  %s\n" % (hashlib.sha256(z.read_bytes()).hexdigest(), name))
        if tamper:
            data = bytearray(z.read_bytes()); data[len(data) // 2] ^= 0xFF; z.write_bytes(bytes(data))
        assets = [{"name": name, "browser_download_url": url or z.as_uri(), "size": z.stat().st_size},
                  {"name": sha.name, "browser_download_url": sha.as_uri(), "size": sha.stat().st_size}]
        feed = self.rel / ("feed-%s-%s.json" % (version, build))
        feed.write_text(json.dumps({"tag_name": "v" + version,
                                    "html_url": "https://github.com/SovereignSignal/sovereign/releases/tag/v" + version,
                                    "assets": [a for a in assets if not any(a["name"].endswith(d) for d in drop)]}))
        return feed
    def upd(self, feed, *args, verify=None, script=None):
        env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                   SOV_UPDATE_FEED=str(feed))
        env.pop("SOV_UPDATE_VERIFY", None)
        if verify:
            env["SOV_UPDATE_VERIFY"] = str(verify)
        # The app runs its bundled updater with -I -B, so PYTHONPATH cannot paper over a missing lib.
        command = [sys.executable, "-I", "-B", str(script)] if script else [sys.executable, str(UPD)]
        cp = subprocess.run(command + ["--source", "release", *args],
                            env=env, capture_output=True, text=True)
        try:
            return cp.returncode, json.loads(cp.stdout or "{}")
        except json.JSONDecodeError:
            return cp.returncode, {"raw": cp.stdout, "err": cp.stderr}
    def files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))
    def assert_untouched(self):
        self.assertEqual((self.app / "Contents/Info.plist").read_bytes(), self.plist, "the installed app must not change")
        self.assertFalse(self.updates.exists() and any(self.updates.iterdir()), "the download must be deleted")
        self.assertFalse(self.opened.exists(), "nothing was installed, so nothing reopens")
        self.assertFalse((self.home / "sovereign-rollback").exists())
    def apply(self, feed, verify=None, script=None):
        _, prev = self.upd(feed, "--preview", verify=verify, script=script)
        self.assertFalse(prev["current"], prev)
        return self.upd(feed, "--apply", "--token", prev["token"], verify=verify, script=script)
    def system_app(self):
        """An app in an Applications folder outside HOME, as /Applications is, running its own backend."""
        app = Path(os.path.realpath(self._tmp.name)) / "Applications/Sovereign.app"
        release_app(app, "0.7.1", "50")
        return app, embed(app, UPD) / "sov-app-update"

    def test_1_the_installed_release_is_current_and_preview_writes_nothing(self):
        before = self.files()
        code, out = self.upd(self.publish("0.7.1", "50"), "--preview")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["state"], out["source"], out["current"]), ("preview", "release", True))
        self.assertEqual((out["latest"]["version"], out["latest"]["build"]), ("0.7.1", "50"))
        self.assertIn("latest release", out["summary"])
        self.assertEqual(self.files(), before)
    def test_2_a_newer_release_is_offered_with_its_size_and_effects(self):
        code, out = self.upd(self.publish("0.8.0", "51"), "--preview", verify=self.ok)
        self.assertEqual(code, 0, out)
        self.assertFalse(out["current"])
        for word in ("0.8.0", "51", "MB"):
            self.assertIn(word, out["summary"])
        self.assertIn("close and reopen", out["effects"])
        self.assertIn("current app is kept", out["effects"])
        self.assertEqual(out["verification"], "stubbed")
        self.assertTrue(out["latest"]["notes_url"].endswith("/v0.8.0"))
    def test_3_apply_installs_keeps_the_previous_app_and_reopens(self):
        code, out = self.apply(self.publish("0.8.0", "51"), verify=self.ok)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["state"], "installed")
        self.assertEqual((out["installed"]["version"], out["installed"]["build"]), ("0.8.0", "51"))
        self.assertEqual(out["verification"], "stubbed")
        self.assertEqual((self.app / "Contents/MacOS/Sovereign").read_text(), "build 51\n")
        kept = list((self.home / "sovereign-rollback").glob("app-update-*/previous.app"))
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0] / "Contents/Info.plist").read_bytes(), self.plist)
        self.assertEqual(out["rollback"], str(kept[0].parent))
        self.assertIn(str(self.app), self.opened.read_text())
        self.assertFalse(self.updates.exists() and any(self.updates.iterdir()))
    def test_4_a_zip_altered_after_its_checksum_is_refused(self):
        code, out = self.apply(self.publish("0.8.0", "51", tamper=True), verify=self.ok)
        self.assertEqual(code, 1, out)
        self.assertIn("checksum", out["error"])
        self.assert_untouched()
    def test_5_a_failed_verification_is_refused_with_its_reason(self):
        code, out = self.apply(self.publish("0.8.0", "51"), verify=self.no)
        self.assertEqual(code, 1, out)
        self.assertIn("signed by someone else", out["error"])
        self.assertIn("Nothing was changed", out["error"])
        self.assert_untouched()
    def test_6_an_older_release_is_never_offered(self):
        release_app(self.app, "0.9.0", "60")
        self.plist = (self.app / "Contents/Info.plist").read_bytes()
        feed = self.publish("0.8.0", "51")
        _, out = self.upd(feed, "--preview", verify=self.ok)
        self.assertTrue(out["current"])
        self.assertIn("newer than the latest release", out["summary"])
        code, out = self.upd(feed, "--apply", "--token", out["token"], verify=self.ok)
        self.assertEqual(code, 1, out)
        self.assert_untouched()
    def test_7_a_bundle_that_is_not_the_named_release_is_refused(self):
        for feed, why in ((self.publish("0.8.0", "51", bundle_id="com.example.other"), "com.example.other"),
                          (self.publish("0.8.1", "52", plist=("0.8.1", "53")), "says version 0.8.1 build 53"),
                          (self.publish("0.8.2", "54", plist=("0.8.3", "54")), "says version 0.8.3 build 54")):
            code, out = self.apply(feed, verify=self.ok)
            self.assertEqual(code, 1, out)
            self.assertIn("refused", out["error"]); self.assertIn(why, out["error"])
            self.assert_untouched()
    def test_8_a_token_from_another_preview_is_refused(self):
        _, other = self.upd(self.publish("0.8.0", "51"), "--preview", verify=self.ok)
        code, out = self.upd(self.publish("0.8.1", "52"), "--apply", "--token", other["token"], verify=self.ok)
        self.assertEqual(code, 1, out)
        self.assertIn("changed since the preview", out["error"])
        self.assert_untouched()
    def test_9_a_release_missing_its_zip_or_checksum_says_what_is_missing(self):
        for drop, named in ((".zip",), ".zip"), ((".sha256",), ".sha256"):
            code, out = self.upd(self.publish("0.8.0", "51", drop=drop), "--preview", verify=self.ok)
            self.assertEqual(code, 0, out)
            self.assertEqual(out["state"], "preview")
            self.assertTrue(out["current"]); self.assertIsNone(out["latest"])
            self.assertIn(named, out["error"]); self.assertEqual(out["summary"], out["error"])
            self.assertFalse(self.updates.exists())
    def test_10_an_unreachable_feed_is_still_a_preview_naming_the_cause(self):
        code, out = self.upd(self.rel / "no-such-feed.json", "--preview")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["current"]); self.assertIsNone(out["latest"])
        self.assertIn("could not be reached", out["summary"])
        # The app reports this as an error, never styled as up to date.
        self.assertEqual(out["state"], "preview"); self.assertEqual(out["error"], out["summary"])
    def test_11_an_address_outside_github_is_refused_before_any_request(self):
        for url in ("http://github.com/SovereignSignal/sovereign/x.zip", "https://example.com/x.zip"):
            code, out = self.apply(self.publish("0.8.0", "51", url=url), verify=self.ok)
            self.assertEqual(code, 1, out)
            self.assertIn("refused", out["error"])
            self.assertFalse(self.updates.exists(), "no download may start for " + url)
            self.assert_untouched()
    def test_12_a_copy_that_fails_after_the_app_closed_puts_the_previous_app_back(self):
        # After stand_down() the app that would show an error is gone. A cp that fails after
        # the installed app was removed used to leave nothing in ~/Applications and no word.
        stub(self.bin / "cp", 'echo "cp: No space left on device" >&2; exit 1')
        code, out = self.apply(self.publish("0.8.0", "51"), verify=self.ok)
        self.assertEqual(code, 1, out)
        kept = list((self.home / "sovereign-rollback").glob("app-update-*/previous.app"))
        self.assertEqual(len(kept), 1)
        self.assertIn("cp", out["error"]); self.assertIn("put back", out["error"])
        self.assertIn(str(kept[0]), out["error"])
        self.assertEqual((self.app / "Contents/Info.plist").read_bytes(), self.plist, "the previous app must be back")
        self.assertIn(str(self.app), self.opened.read_text(), "the restored app must be reopened")
        self.assertFalse(self.updates.exists() and any(self.updates.iterdir()), "the download must be deleted")
    def test_13_an_app_outside_home_updates_itself_in_place(self):
        # Run from inside a bundle, the updater's own bundle is the installed app, wherever
        # it sits. An app in /Applications used to get no version and no update, because
        # only ~/Applications was ever looked at; and a copy in ~/Applications must not be
        # mistaken for the one that is running.
        app, script = self.system_app()
        home_plist = self.plist   # the ~/Applications copy from setUp
        code, prev = self.upd(self.publish("0.8.0", "51"), "--preview", verify=self.ok, script=script)
        self.assertEqual(code, 0, prev)
        self.assertEqual(prev["app_path"], str(app))
        self.assertEqual((prev["installed"]["version"], prev["installed"]["build"]), ("0.7.1", "50"))
        code, out = self.apply(self.publish("0.8.0", "51"), verify=self.ok, script=script)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["state"], "installed")
        self.assertEqual((app / "Contents/MacOS/Sovereign").read_text(), "build 51\n")
        kept = list((self.home / "sovereign-rollback").glob("app-update-*/previous.app"))
        self.assertEqual(len(kept), 1)
        self.assertTrue((kept[0] / "Contents/Resources/backend/bin/sov-app-update").exists(), "the whole bundle is kept")
        self.assertIn(str(app), self.opened.read_text())
        self.assertEqual((self.app / "Contents/Info.plist").read_bytes(), home_plist,
                         "the copy in ~/Applications is not the running app and must not change")
    def test_14_an_app_folder_this_user_cannot_write_is_refused_before_anything_changes(self):
        # /Applications needs an administrator to change. Say so, name the folder, and
        # stop before the download, the quit and the swap.
        app, script = self.system_app()
        plist = (app / "Contents/Info.plist").read_bytes()
        folder = app.parent
        folder.chmod(0o555)
        try:
            if os.access(str(folder), os.W_OK):
                self.skipTest("running as a user who can write anything")
            code, out = self.apply(self.publish("0.8.0", "51"), verify=self.ok, script=script)
        finally:
            folder.chmod(0o755)
        self.assertEqual(code, 1, out)
        self.assertIn("This process is not allowed to change %s." % app, out["error"])
        self.assertIn("App Management", out["error"])
        self.assertIn("Nothing was changed", out["error"])
        self.assertNotIn("\u2014", out["error"]); self.assertNotIn("\u2013", out["error"])
        self.assertEqual((app / "Contents/Info.plist").read_bytes(), plist)
        self.assertFalse(self.updates.exists() and any(self.updates.iterdir()), "nothing may be downloaded")
        self.assertFalse(self.opened.exists())
        self.assertFalse((self.home / "sovereign-rollback").exists())
    def test_15_something_else_at_the_app_path_is_never_deleted(self):
        # The swap deletes the installed app before copying the new one in, so whatever
        # sits at that path has to be Sovereign. Anything else is refused untouched.
        release_app(self.app, "0.7.1", "50", bundle_id="com.example.other")
        self.plist = (self.app / "Contents/Info.plist").read_bytes()
        code, out = self.apply(self.publish("0.8.0", "51"), verify=self.ok)
        self.assertEqual(code, 1, out)
        self.assertIn("%s is not a Sovereign app" % self.app, out["error"])
        self.assert_untouched()
    def test_a_verify_hook_that_is_not_executable_is_ignored(self):
        # The stub replaces Apple's gate only when it is a real executable. Anything else
        # falls through to codesign, which a fake bundle cannot pass.
        hook = self.rel / "not-executable"; hook.write_text("exit 0\n")
        code, out = self.apply(self.publish("0.8.0", "51"), verify=hook)
        self.assertEqual(code, 1, out)
        self.assertIn("signature is not valid", out["error"])
        self.assert_untouched()
    def test_an_ad_hoc_bundle_that_prints_the_team_text_is_refused(self):
        # The executable's name is printed in codesign -dvv output, so a substring check
        # on that text passed this bundle. The code requirement does not.
        trick = "TeamIdentifier=SM97GYTF25 Authority=Developer ID Application"
        def sign(app):
            shutil.copy("/usr/bin/true", str(app / "Contents/MacOS" / trick))
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            info.update(CFBundleExecutable=trick, CFBundlePackageType="APPL")
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
            (app / "Contents/MacOS/Sovereign").unlink()
            subprocess.run(["codesign", "-s", "-", "--force", str(app)], check=True, capture_output=True)
            # The plain checks the old code relied on all pass for it.
            self.assertEqual(subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)]).returncode, 0)
            shown = subprocess.run(["codesign", "-dvv", str(app)], capture_output=True, text=True).stderr
            self.assertIn(trick, shown); self.assertIn("Signature=adhoc", shown)
        code, out = self.apply(self.publish("0.8.0", "51", prepare=sign))
        self.assertEqual(code, 1, out)
        self.assertIn("not signed with Sovereign's Developer ID", out["error"])
        self.assert_untouched()
class ReleaseUpdateUnits(unittest.TestCase):
    """Pieces of the release path checked in process, without a release on disk."""
    @classmethod
    def setUpClass(cls):
        import runpy
        cls.mod = runpy.run_path(str(UPD))
    def test_the_code_requirement_names_apples_anchor_developer_id_the_team_and_the_bundle(self):
        self.assertEqual(self.mod["code_requirement"](),
            '=anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] exists '
            'and certificate leaf[field.1.2.840.113635.100.6.1.13] exists '
            'and certificate leaf[subject.OU] = "SM97GYTF25" and identifier "com.sovereign.console"')
    def test_a_redirect_passes_the_same_address_check_as_the_first_request(self):
        import urllib.request
        from unittest.mock import patch
        handler = self.mod["_CheckedRedirects"]()
        req = urllib.request.Request("https://github.com/SovereignSignal/sovereign/releases/download/v1/x.zip")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOV_UPDATE_FEED", None)
            for bad in ("http://github.com/x", "https://evil.example/x"):
                with self.assertRaises(ValueError, msg=bad):
                    handler.redirect_request(req, None, 302, "Found", {}, bad)
            good = handler.redirect_request(req, None, 302, "Found", {},
                                            "https://release-assets.githubusercontent.com/x")
            self.assertEqual(good.full_url, "https://release-assets.githubusercontent.com/x")
class InstalledAppLocation(unittest.TestCase):
    """Where the installed app is: the bundle the backend runs from, else the known folders."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "lib"))
        import sovereign_app
        cls.mod = sovereign_app
    def test_the_bundle_the_backend_runs_from_is_the_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Elsewhere/Sovereign.app"
            release_app(app, "0.8.0", "51")
            here = embed(app, UPD) / "sov-app-update"
            self.assertEqual(self.mod.installed_app_path(str(here), roots=()), os.path.realpath(str(app)))
    def test_from_a_checkout_the_first_known_folder_that_holds_the_app_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            mine, system = Path(tmp) / "home/Applications", Path(tmp) / "Applications"
            roots = (str(mine), str(system))
            self.assertEqual(self.mod.installed_app_path(str(UPD), roots=roots), str(mine / "Sovereign.app"),
                             "nothing installed: a fresh install goes to the first folder")
            release_app(system / "Sovereign.app", "0.8.0", "51")
            self.assertEqual(self.mod.installed_app_path(str(UPD), roots=roots), str(system / "Sovereign.app"))
            release_app(mine / "Sovereign.app", "0.8.0", "51")
            self.assertEqual(self.mod.installed_app_path(str(UPD), roots=roots), str(mine / "Sovereign.app"))
    def test_a_bundle_with_another_id_is_never_the_app_even_when_it_holds_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "Applications/Sovereign.app"
            release_app(other, "0.8.0", "51", bundle_id="com.example.other")
            here = embed(other, UPD) / "sov-app-update"
            mine = Path(tmp) / "home/Applications"
            self.assertEqual(self.mod.installed_app_path(str(here), roots=(str(mine), str(other.parent))),
                             str(mine / "Sovereign.app"), "falls through, and the roots get the same check")
            release_app(mine / "Sovereign.app", "0.8.0", "51")
            self.assertEqual(self.mod.installed_app_path(str(here), roots=(str(other.parent), str(mine))),
                             str(mine / "Sovereign.app"), "the first root that is Sovereign wins")
    def test_a_folder_named_like_an_app_with_no_identity_is_not_the_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "Projects.app"; (fake / "Contents").mkdir(parents=True)
            here = embed(fake, UPD) / "sov-app-update"
            mine = Path(tmp) / "home/Applications"
            self.assertEqual(self.mod.installed_app_path(str(here), roots=(str(mine),)), str(mine / "Sovereign.app"))
    def test_only_the_innermost_bundle_counts_and_only_with_sovereigns_id(self):
        # /x/Foo.app/Contents/y/Sovereign.app: the inner bundle is the app when its id is
        # Sovereign's, and the outer one is never taken in its place.
        for outer_id, inner_id, inner_wins in (("com.example.foo", "com.sovereign.console", True),
                                               ("com.sovereign.console", "com.example.other", False),
                                               ("com.example.foo", "com.example.other", False)):
            with tempfile.TemporaryDirectory() as tmp:
                outer = Path(os.path.realpath(tmp)) / "x/Foo.app"
                release_app(outer, "1.0", "1", bundle_id=outer_id)
                inner = outer / "Contents/y/Sovereign.app"
                release_app(inner, "0.8.0", "51", bundle_id=inner_id)
                here = embed(inner, UPD) / "sov-app-update"
                mine = Path(tmp) / "home/Applications"
                got = self.mod.installed_app_path(str(here), roots=(str(mine),))
                self.assertEqual(got, str(inner) if inner_wins else str(mine / "Sovereign.app"), (outer_id, inner_id))
                self.assertNotEqual(got, str(outer))
    def test_a_script_reached_through_a_symlink_resolves_to_its_real_bundle_then_checks_it(self):
        for real_id, resolves in (("com.sovereign.console", True), ("com.example.other", False)):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(os.path.realpath(tmp))
                real = root / "Applications/Sovereign.app"
                release_app(real, "0.8.0", "51", bundle_id=real_id)
                script = embed(real, UPD) / "sov-app-update"
                host = root / "Other.app"
                release_app(host, "1.0", "1", bundle_id="com.sovereign.console")
                (host / "Contents/Resources").mkdir(parents=True)
                link = host / "Contents/Resources/sov-app-update"; link.symlink_to(script)
                mine = root / "home/Applications"
                got = self.mod.installed_app_path(str(link), roots=(str(mine),))
                self.assertEqual(got, str(real) if resolves else str(mine / "Sovereign.app"), real_id)
                self.assertNotEqual(got, str(host), "the bundle holding the link is never the app")
    def test_a_preview_bundle_is_never_taken_for_the_installed_app(self):
        # Preview builds stay separate (build.sh refuses to install one), so an update or a
        # version read from inside one is about the installed app, never the preview.
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "build/Sovereign Preview.app"
            release_app(preview, "0.9.0", "60")
            info = plistlib.loads((preview / "Contents/Info.plist").read_bytes())
            info["SovereignPreview"] = True
            (preview / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
            here = embed(preview, UPD) / "sov-app-update"
            mine = Path(tmp) / "home/Applications"
            self.assertEqual(self.mod.installed_app_path(str(here), roots=(str(mine),)), str(mine / "Sovereign.app"))
    def test_status_reads_the_app_it_runs_inside_wherever_it_is(self):
        import importlib.machinery, importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Applications/Sovereign.app"
            release_app(app, "0.8.0", "51")
            script = embed(app, ROOT / "bin/sov-status") / "sov-status"
            loader = importlib.machinery.SourceFileLoader("sov_status_in_bundle", str(script))
            status = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
            loader.exec_module(status)
            found = status._installed_app()
            self.assertTrue(found["installed"], found)
            self.assertEqual(found["path"], os.path.realpath(str(app)))
            self.assertEqual((found["version"], found["build"]), ("0.8.0", "51"))
if __name__ == "__main__":
    unittest.main()
