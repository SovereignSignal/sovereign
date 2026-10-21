"""`sov ingest sessions`: the owner's commands for session capture.

The dry plan, --show and status read and print; they make no model call and write
nothing, so the model stub here counts every request and the archive and the state
directory are hashed around each run. --apply runs the shipped sessions.sh once and is
refused while capture is off. --on prints the plan before it writes the switch, and
is refused where no model may read a session, with the reason.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402
from session_ingest import inference  # noqa: E402

INGEST = ROOT / "bin" / "sov-ingest"
SID = "5e551011-0000-4000-8000-00000000c711"
OFF_SENTENCE = ("Session capture is off. Turn it on with `sov ingest sessions --on` after looking at "
                "the preview.")
VALID = {"title": "Every archive copy stays encrypted",
         "body": "Any copy of the archive that leaves the owner's storage is encrypted first.",
         "kind": "decision", "confidence": "high", "evidence": ["T1"]}


def tree_hash(*roots):
    h = hashlib.sha256()
    for root in roots:
        for folder, dirs, files in sorted(os.walk(str(root))):
            dirs.sort()
            h.update(("D" + os.path.relpath(folder, str(root))).encode())
            for name in sorted(files):
                path = os.path.join(folder, name)
                h.update(("F" + os.path.relpath(path, str(root))).encode())
                if not os.path.islink(path):
                    with open(path, "rb") as fh:
                        h.update(fh.read())
    return h.hexdigest()


class Cli(unittest.TestCase):
    def rig(self, reply_fn=None, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = fx.Rig(tmp.name, reply_fn or (lambda body: json.dumps({"captures": [VALID]})), **kw)
        self.addCleanup(rig.close)
        return rig

    def sessions(self, rig, *args, **extra):
        return subprocess.run([sys.executable, str(INGEST), "sessions"] + list(args), capture_output=True,
                              text=True, env=rig.env(**extra), timeout=240)

    def config(self, rig):
        return json.loads((rig.state / "session-capture.json").read_text())

    def write_config(self, rig, cfg):
        (rig.state / "session-capture.json").write_text(json.dumps(cfg))

    def client(self, rig):
        (rig.state / "hub.json").unlink()
        (rig.home / ".brain-hub").write_text("hub-host\n")

    # -- the dry plan and --show ----------------------------------------------------

    def test_dry_plan_and_show_make_no_call_and_write_nothing(self):
        rig = self.rig()
        rig.transcript(SID)
        rig.transcript("5e551011-0000-4000-8000-00000000c712", prompts=["only one prompt"])
        before = tree_hash(rig.vault, rig.state)
        plan = self.sessions(rig)
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        self.assertIn(SID, plan.stdout)
        self.assertIn("would distil", plan.stdout)
        self.assertIn("skipped:few-prompts", plan.stdout)
        self.assertIn("no model call", plan.stdout)
        self.assertRegex(plan.stdout, r"Budget left: 3 calls this tick, 30 of 30 today, 60000 characters a tick\.")

        dry = self.sessions(rig, "--json")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        doc = json.loads(dry.stdout)
        rows = {r["id"]: r for r in doc["candidates"]}
        self.assertIsNone(rows[SID]["verdict"])
        self.assertEqual(rows[SID]["project"], "proj")
        self.assertEqual(rows[SID]["prompts"], 3)
        self.assertGreater(rows[SID]["excerpt_chars"], 0)
        self.assertEqual(rows["5e551011-0000-4000-8000-00000000c712"]["verdict"], "skipped:few-prompts")
        self.assertEqual(doc["budget"]["left_today"], 30)
        self.assertTrue(doc["enabled"])

        show = self.sessions(rig, "--show", SID)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("Remember that every archive copy stays encrypted", show.stdout)
        for marker in fx.MARKERS:
            self.assertNotIn(marker, show.stdout)
        for key in fx.KEYS:
            self.assertNotIn(key, show.stdout)

        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(tree_hash(rig.vault, rig.state), before)
        self.assertFalse((rig.state / "sessions").exists())

    def test_show_of_an_unknown_or_malformed_id_is_refused(self):
        rig = self.rig()
        rig.transcript(SID)
        self.assertEqual(self.sessions(rig, "--show", "5e551011-0000-4000-8000-0000000000ff").returncode, 1)
        bad = self.sessions(rig, "--show", "../../etc/passwd")
        self.assertEqual(bad.returncode, 64, bad.stderr)

    def test_show_stops_at_a_refused_cwd(self):
        rig = self.rig()
        rig.transcript(SID, cwd=rig.vault)
        show = self.sessions(rig, "--show", SID)
        self.assertEqual(show.returncode, 1)
        self.assertIn("inside an archive", show.stderr)
        self.assertNotIn("Remember that", show.stdout + show.stderr)

    def test_before_enable_sessions_are_counted_and_since_previews_a_backfill(self):
        rig = self.rig(enabled=False)
        rig.transcript(SID)
        plan = self.sessions(rig)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertNotIn(SID, plan.stdout)
        self.assertIn("1 session ended before capture was turned on", plan.stdout)
        back = self.sessions(rig, "--since", "2d")
        self.assertIn(SID, back.stdout)
        self.assertIn("would distil", back.stdout)
        self.assertEqual(rig.stub.calls, 0)

    # -- --apply ------------------------------------------------------------------------

    def test_apply_while_off_is_refused(self):
        rig = self.rig(enabled=False)
        rig.transcript(SID)
        r = self.sessions(rig, "--apply")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(OFF_SENTENCE, r.stderr)
        self.assertEqual(rig.stub.calls, 0)
        self.assertFalse(rig.sessions.exists())
        self.assertFalse((rig.state / "sessions").exists())

    def test_apply_runs_one_tick_through_sessions_sh(self):
        rig = self.rig()
        rig.transcript(SID)
        r = self.sessions(rig, "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rig.stub.calls, 1)
        self.assertEqual(len(rig.captures()), 1)
        self.assertEqual(rig.verdict(SID), "distilled")
        self.assertFalse((rig.state / "lanes" / "claude-code-sessions.lock").exists())

    def test_apply_waits_for_a_tick_that_holds_the_lane_lock(self):
        rig = self.rig()
        rig.transcript(SID)
        lock = rig.state / "lanes" / "claude-code-sessions.lock"
        lock.mkdir(parents=True)
        r = self.sessions(rig, "--apply")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("running now", r.stderr)
        self.assertEqual(rig.stub.calls, 0)
        self.assertTrue(lock.is_dir())

    # -- --on and --off -------------------------------------------------------------------

    def test_on_prints_the_plan_then_writes_enabled_at(self):
        rig = self.rig(enabled=False)
        rig.transcript(SID)
        start = time.time()
        r = self.sessions(rig, "--on")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        entry = self.config(rig)["tools"]["claude-code"]
        self.assertIs(entry["enabled"], True)
        from session_ingest import prefilter
        at = prefilter._epoch(entry["enabled_at"])
        self.assertIsNotNone(at)
        self.assertLessEqual(abs(at - start), 5)
        self.assertLess(r.stdout.index("Budget left"), r.stdout.index("Session capture is on"))
        self.assertEqual(rig.stub.calls, 0)

        off = self.sessions(rig, "--off")
        self.assertEqual(off.returncode, 0, off.stderr)
        self.assertIs(self.config(rig)["tools"]["claude-code"]["enabled"], False)

    def test_on_with_since_backdates_the_floor_and_previews_it(self):
        rig = self.rig(enabled=False)
        rig.transcript(SID)
        start = time.time()
        r = self.sessions(rig, "--on", "--since", "2d")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(SID, r.stdout)
        from session_ingest import prefilter
        at = prefilter._epoch(self.config(rig)["tools"]["claude-code"]["enabled_at"])
        self.assertLessEqual(abs(at - (start - 2 * 86400)), 5)

    def test_on_in_client_mode_exits_nonzero_with_the_reason(self):
        rig = self.rig(enabled=False)
        self.client(rig)
        r = self.sessions(rig, "--on")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(inference.CLIENT_REASON, r.stderr)
        self.assertIs(self.config(rig)["tools"]["claude-code"]["enabled"], False)
        status = json.loads(self.sessions(rig, "status", "--json").stdout)
        self.assertEqual(status["mode"], "client")
        self.assertIs(status["available"], False)
        self.assertEqual(status["reason"], inference.CLIENT_REASON)

    def test_a_hosted_provider_under_local_only_sends_nothing(self):
        rig = self.rig(enabled=False)
        (rig.state / "hub.json").unlink()   # hubless: the owner's provider, Anthropic by default
        rig.transcript(SID)
        proxy = {k: rig.stub.base for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
        env = dict(proxy, CURATOR_LOCAL_ONLY="1")
        before = tree_hash(rig.vault)
        self.assertEqual(self.sessions(rig, **env).returncode, 0)
        self.assertEqual(self.sessions(rig, "--since", "2d", **env).returncode, 0)
        self.assertEqual(self.sessions(rig, "--show", SID, **env).returncode, 0)
        status = self.sessions(rig, "status", "--json", **env)
        self.assertEqual(status.returncode, 0, status.stderr)
        doc = json.loads(status.stdout)
        self.assertEqual(doc["mode"], "hubless")
        self.assertIs(doc["available"], False)
        self.assertEqual(doc["reason"], inference.GUARD_REASON)
        on = self.sessions(rig, "--on", **env)
        self.assertNotEqual(on.returncode, 0)
        self.assertIn(inference.GUARD_REASON, on.stderr)
        self.assertIs(self.config(rig)["tools"]["claude-code"]["enabled"], False)
        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(tree_hash(rig.vault), before)

    # -- status -------------------------------------------------------------------------

    def test_status_json_shape(self):
        rig = self.rig()
        temp_proj = "/private/tmp/sov-ses-cli-%s" % uuid.uuid4().hex[:10]
        rig.transcript(SID)
        rig.transcript("5e551011-0000-4000-8000-00000000c713", cwd=temp_proj)
        rig.transcript("5e551011-0000-4000-8000-00000000c714", cwd=rig.vault)
        # A committed row's cwd is the project; the file is not read for it.
        rig.transcript("5e551011-0000-4000-8000-00000000c715")
        elsewhere = str(rig.tmp / "work" / "other")
        (rig.state / "sessions").mkdir()
        (rig.state / "sessions" / "claude-code.json").write_text(json.dumps({"sessions": {
            "5e551011-0000-4000-8000-00000000c715": {"verdict": "distilled", "captures": 2, "cwd": elsewhere,
                                                     "at": fx.iso_minute(time.time() - 600)}},
            "waiting": None}))
        before = tree_hash(rig.vault, rig.state)
        r = self.sessions(rig, "status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(set(doc), {"tool", "enabled", "available", "mode", "reason", "distiller", "budget",
                                    "week", "waiting", "projects", "next"})
        self.assertEqual(doc["tool"], "claude-code")
        self.assertIs(doc["enabled"], True)
        self.assertIs(doc["available"], True)
        self.assertEqual(doc["mode"], "hub")
        self.assertEqual(doc["reason"], "")
        self.assertEqual(doc["distiller"], {"provider": "local", "model": "qwen-test:8b", "name": "Local model"})
        self.assertEqual(doc["budget"], {"calls_per_tick": 3, "calls_per_day": 30, "chars_per_tick": 60000,
                                         "used_today": 0})
        self.assertEqual(set(doc["week"]), {"distilled", "captures", "skipped", "waiting", "failed", "refused"})
        self.assertEqual(doc["week"]["distilled"], 1)
        self.assertEqual(doc["week"]["captures"], 2)
        self.assertEqual(doc["week"]["waiting"], 1)   # the one quiet session that would be distilled
        self.assertIsNone(doc["waiting"])
        self.assertEqual(doc["next"], [{"tool": "codex", "label": "Codex"}])
        projects = {p["path"]: p for p in doc["projects"]}
        for p in doc["projects"]:
            self.assertEqual(set(p), {"path", "label", "sessions", "on", "kind", "denied"})
        temp = projects[os.path.realpath(temp_proj)]
        self.assertEqual((temp["kind"], temp["on"], temp["denied"], temp["sessions"]), ("temp", False, False, 1))
        self.assertEqual(temp["label"], os.path.basename(temp_proj))
        self.assertEqual(projects[os.path.realpath(str(rig.vault))]["kind"], "archive")
        self.assertIs(projects[os.path.realpath(str(rig.vault))]["on"], False)
        self.assertIs(projects[str(rig.proj)]["on"], True)   # under the allow-listed temp root
        self.assertEqual(projects[str(rig.proj)]["sessions"], 1)
        self.assertEqual(projects[elsewhere]["sessions"], 1)
        self.assertEqual(rig.stub.calls, 0)
        self.assertEqual(tree_hash(rig.vault, rig.state), before)

        text = self.sessions(rig, "status")
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("Session capture for Claude Code is on", text.stdout)
        self.assertIn("Codex", text.stdout)

    def test_status_while_off_has_no_waiting(self):
        rig = self.rig(enabled=False)
        (rig.state / "sessions").mkdir()
        (rig.state / "sessions" / "claude-code.json").write_text(json.dumps(
            {"sessions": {}, "waiting": {"reason": "model unreachable", "since": "2026-10-20T10:00:00Z"}}))
        doc = json.loads(self.sessions(rig, "status", "--json").stdout)
        self.assertIs(doc["enabled"], False)
        self.assertIsNone(doc["waiting"])
        self.write_config(rig, dict(self.config(rig), tools={"claude-code": {"enabled": True,
                                                                             "enabled_at": "2026-10-19T00:00:00Z"}}))
        doc = json.loads(self.sessions(rig, "status", "--json").stdout)
        self.assertEqual(doc["waiting"], {"reason": "model unreachable", "since": "2026-10-20T10:00:00Z"})

    # -- the lists ------------------------------------------------------------------------

    def test_deny_then_allow_leaves_the_path_only_in_allow(self):
        rig = self.rig()
        target = rig.tmp / "work" / "real"
        target.mkdir(parents=True)
        link = rig.tmp / "work" / "alias"
        link.symlink_to(target)
        real = os.path.realpath(str(target))
        self.assertEqual(self.sessions(rig, "--deny", str(link)).returncode, 0)
        cfg = self.config(rig)
        self.assertIn(real, cfg["deny"])
        self.assertNotIn(str(link), cfg["deny"])
        r = self.sessions(rig, "--allow", str(link))
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.config(rig)
        self.assertIn(real, cfg["allow"])
        self.assertNotIn(real, cfg["deny"])
        self.assertEqual(cfg["allow"].count(real), 1)
        self.sessions(rig, "--allow", str(target))
        self.assertEqual(self.config(rig)["allow"].count(real), 1)
        self.assertEqual(self.sessions(rig, "--deny", real).returncode, 0)
        cfg = self.config(rig)
        self.assertIn(real, cfg["deny"])
        self.assertNotIn(real, cfg["allow"])

    def test_allowing_a_folder_inside_an_archive_says_it_stays_refused(self):
        rig = self.rig()
        r = self.sessions(rig, "--allow", str(rig.vault / "workstreams"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("inside an archive", r.stdout)

    # -- --where and usage ----------------------------------------------------------------

    def test_where_prints_the_row_cwd_or_the_first_cwd(self):
        rig = self.rig()
        rig.transcript(SID)
        r = self.sessions(rig, "--where", SID)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), str(rig.proj))
        (rig.state / "sessions").mkdir()
        (rig.state / "sessions" / "claude-code.json").write_text(json.dumps(
            {"sessions": {SID: {"verdict": "distilled", "cwd": "/somewhere/else"}}, "waiting": None}))
        self.assertEqual(self.sessions(rig, "--where", SID).stdout.strip(), "/somewhere/else")
        self.assertEqual(self.sessions(rig, "--where", "5e551011-0000-4000-8000-0000000000ff").returncode, 1)

    def test_usage_errors_exit_64(self):
        rig = self.rig()
        for args in (["--bogus"], ["--on", "--off"], ["--show"], ["--tool", "nope"], ["--since", "soon"],
                     ["--apply", "--json"], ["status", "--since", "2d"]):
            r = self.sessions(rig, *args)
            self.assertEqual(r.returncode, 64, (args, r.stdout, r.stderr))
            self.assertIn("usage: sov ingest sessions", r.stderr)

    def test_printed_text_keeps_the_house_voice(self):
        rig = self.rig(enabled=False)
        rig.transcript(SID)
        outs = [self.sessions(rig, *a) for a in ([], ["--since", "2d"], ["status"], ["--apply"], ["--bogus"])]
        self.client(rig)
        outs.append(self.sessions(rig, "--on"))
        text = "".join(r.stdout + r.stderr for r in outs)
        for bad in ("\u2014", "\u2013", "foster", "crucial", "significantly", "comprehensive"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
