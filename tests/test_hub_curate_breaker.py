"""A tripped circuit breaker is a condition, not a clean tick.

bin/hub/curate stops before judging anything when the owner's review queue is full
(ARCHIVIST_PENDING_LIMIT, 50 by default). That pause is archive-wide: no lane is
curated again until the gate drains. It used to exit 0, so the runner's receipts,
runs.log and `sov status` could not tell a paused tick from a healthy one, and the
pause was invisible for as long as it lasted: every two hours, for days.

It exits 75 now (EX_TEMPFAIL: nothing is broken, the work is deliberately not being
done). The runner keeps that code in the receipt and withholds last-ok, job_health
names the condition instead of reporting a generic failure, and the owner hears once,
on the tick the condition appears, not on every tick while it holds.

The interpreter is the second half of the same silence. curator-run's shebang is
`#!/usr/bin/env python3`, which on a Mac finds the Xcode shim; after an Xcode update
that shim exits 69 until someone accepts the license, and a job that names it fails
every tick. curate now starts curator-run with the interpreter bin/_sov-python.sh
resolves, the one every rendered launchd job already uses.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from sovereign_hub import instance, job_health, manifest, runner  # noqa: E402

CURATE = ROOT / "bin" / "hub" / "curate"
BREAKER = "curator-run: queue circuit breaker open"
NOTIFY = ("#!/bin/bash\nprintf 'channel=%s\\n%s\\n' \"${TG_ENV_FILE:-}\" \"$*\" "
          ">> \"$SOV_STUB_LOG\"\ncat >> \"$SOV_STUB_LOG\"\nexit 0\n")


def run_curate(tmp, pending, limit=50, **extra_env):
    """The real script against a fixture vault, with curator-run stubbed.

    The stub carries no shebang and is not executable, so it runs only if curate names
    an interpreter for it; it reports which one, what arguments it was given, and the
    auto-promote cap it was handed.
    """
    root = Path(tmp)
    proposals = root / "vault" / "raw/workspaces/curator/proposals"
    proposals.mkdir(parents=True)
    for i in range(pending):
        (proposals / ("card-%02d.md" % i)).write_text("---\ntype: concept\n---\n")
    tpl = root / "tpl" / "bin"
    tpl.mkdir(parents=True)
    (tpl / "curator-run").write_text(
        "import os, sys\nprint('curator-run stub: %s :: %s :: cap=%s' % (sys.executable, ' '.join(sys.argv[1:]),"
        " os.environ.get('ARCHIVIST_AUTO_PROMOTE_MAX')))\n")
    shutil.copy2(ROOT / "bin" / "_sov-python.sh", tpl / "_sov-python.sh")
    env = dict(os.environ, SOVS_VAULT=str(root / "vault"), CURATOR_LANE="curator",
               SOV_TEMPLATE=str(root / "tpl"), SOV_PYTHON=sys.executable,
               ARCHIVIST_PENDING_LIMIT=str(limit))
    env.pop("ARCHIVIST_AUTO_PROMOTE_MAX", None)
    env.pop("SOV_CURATE_AUTO_PROMOTE_MAX", None)
    env.update(extra_env)
    return subprocess.run(["/bin/bash", str(CURATE)], env=env, capture_output=True, text=True, timeout=60)


class TheBreakerSaysItTripped(unittest.TestCase):

    def test_a_full_queue_exits_paused_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = run_curate(tmp, pending=50, limit=50)
            self.assertEqual(done.returncode, runner.PAUSED_EXIT,
                             "a tripped breaker must not read as a healthy tick\n" + done.stdout + done.stderr)
            self.assertNotIn("curator-run stub", done.stdout, "nothing may be judged while the breaker is open")

    def test_the_message_stays_on_stdout_and_names_the_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = run_curate(tmp, pending=51, limit=50)
            self.assertIn(BREAKER, done.stdout)
            self.assertIn("51 pending >= limit 50", done.stdout)
            self.assertNotIn(BREAKER, done.stderr, "the runner delivers stdout; the message belongs there")

    def test_a_queue_under_the_limit_still_curates(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = run_curate(tmp, pending=3, limit=50)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertNotIn(BREAKER, done.stdout)
            self.assertIn("--max 50", done.stdout, "the pass itself is unchanged")

    def test_curator_run_starts_on_the_resolved_interpreter(self):
        """Not `#!/usr/bin/env python3`, which on a Mac is the Xcode shim."""
        with tempfile.TemporaryDirectory() as tmp:
            done = run_curate(tmp, pending=0, limit=50)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn(sys.executable, done.stdout,
                          "curator-run must run under the interpreter _sov-python.sh picks")

    def test_the_tick_cap_is_four_unless_hub_json_says_otherwise(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("cap=4", run_curate(tmp, pending=0).stdout)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("cap=12", run_curate(tmp, pending=0, SOV_CURATE_AUTO_PROMOTE_MAX="12").stdout,
                          "hub.json curate_auto_promote_max raises the tick's cap")

    def test_the_nightly_cap_is_not_the_ticks(self):
        """The nightly exports its own 12 before calling curate; the tick setting must not
        reach it, or raising or lowering the tick would silently move the nightly too."""
        with tempfile.TemporaryDirectory() as tmp:
            done = run_curate(tmp, pending=0, ARCHIVIST_AUTO_PROMOTE_MAX="12", SOV_CURATE_AUTO_PROMOTE_MAX="4")
            self.assertIn("cap=12", done.stdout)

    def test_an_unusable_limit_is_still_its_own_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = run_curate(tmp, pending=1, limit="nine")
            self.assertEqual(done.returncode, 64)
            self.assertNotEqual(done.returncode, runner.PAUSED_EXIT, "a bad setting is not a paused queue")

    def test_the_script_and_the_runner_agree_on_the_number(self):
        source = CURATE.read_text(encoding="utf-8")
        self.assertIn("exit %d" % runner.PAUSED_EXIT, source)
        self.assertIn("PAUSED_EXIT", source, "the header must point at the constant the runner reads")


class TheRunnerRecordsAPause(unittest.TestCase):
    """Receipts and alerts for a job that stood down on purpose."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.state = base / "state"
        self.template = base / "template"
        (self.template / "bin" / "hub").mkdir(parents=True)
        (self.state / "hub").mkdir(parents=True)
        (base / "v").mkdir()
        self.log = base / "notify.log"
        self.log.write_text("")
        self.notify = base / "notify"
        self.notify.write_text(NOTIFY)
        self.notify.chmod(0o755)
        os.environ["SOV_STUB_LOG"] = str(self.log)
        instance.write(self.state, {"vault": str(base / "v"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "notify": {"alerts": str(base / "alerts.env"),
                                               "archive": str(base / "archive.env")}})
        (base / "alerts.env").write_text("TG_BOT_TOKEN=x\nTG_CHAT_ID=y\n")
        (base / "archive.env").write_text("TG_BOT_TOKEN=x\nTG_CHAT_ID=z\n")

    def job(self, name, body, **spec):
        path = self.template / "bin" / "hub" / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)
        entry = dict(program="hub/" + name, interval_s=7200, deliver=False, description="t")
        entry.update(spec)
        manifest.JOBS[name] = entry
        self.addCleanup(manifest.JOBS.pop, name, None)
        return name

    def paused(self, name="t-paused", **spec):
        return self.job(name, "echo '%s: 51 pending >= limit 50'\nexit %d\n" % (BREAKER, runner.PAUSED_EXIT), **spec)

    def tick(self, name):
        return runner.tick(name, self.state, self.template, str(self.notify))

    def receipt(self, name, kind):
        return (self.state / "hub" / (name + "." + kind)).read_text()

    def sends(self):
        """One line per message the notify stub was handed, whatever its channel."""
        return self.log.read_text().count("channel=")

    def test_the_receipt_keeps_the_code_and_withholds_last_ok(self):
        job = self.paused()
        self.assertEqual(self.tick(job), runner.PAUSED_EXIT)
        self.assertEqual(self.receipt(job, "last-exit").strip(), str(runner.PAUSED_EXIT))
        self.assertFalse((self.state / "hub" / (job + ".last-ok")).exists(),
                         "a paused tick did no work, so it is not a success either")
        self.assertIn("exit=%d" % runner.PAUSED_EXIT, (self.state / "hub" / "runs.log").read_text())

    def test_the_owner_hears_once_not_every_two_hours(self):
        job = self.paused()
        self.tick(job)
        first = self.log.read_text()
        self.assertIn("PAUSED t-paused", first)
        self.assertIn("51 pending >= limit 50", first, "the condition travels with the notice")
        self.assertIn("alerts.env", first)
        self.assertEqual(self.sends(), 1)
        self.tick(job)
        self.assertEqual(self.log.read_text(), first, "a condition that is still true says nothing new")

    def test_a_pause_that_returns_after_a_clean_run_speaks_again(self):
        job = self.paused()
        self.tick(job)
        self.job(job, "echo judged\nexit 0\n")
        self.assertEqual(self.tick(job), 0)
        self.paused(job)
        self.tick(job)
        self.assertEqual(self.sends(), 2, "the pause is new again, so it is said again")

    def test_a_delivering_job_still_delivers_while_paused(self):
        """The nightly's digest is the owner's notice; it must not become an alert."""
        job = self.paused("t-digest", deliver=True)
        self.assertEqual(self.tick(job), runner.PAUSED_EXIT)
        sent = self.log.read_text()
        self.assertIn("archive.env", sent)
        self.assertIn("51 pending >= limit 50", sent)
        self.assertNotIn("ALERT", sent)
        self.assertNotIn("PAUSED t-digest", sent, "it already told the owner on its own channel")

    def test_a_real_failure_still_alerts_every_time(self):
        job = self.job("t-fail", "echo boom >&2\nexit 1\n")
        self.assertEqual(self.tick(job), 1)
        self.tick(job)
        self.assertIn("ALERT t-fail exit 1", self.log.read_text())
        self.assertEqual(self.sends(), 2, "only a deliberate pause is edge-triggered; a failure repeats")


class TheNightlyStillSpeaksWhilePaused(unittest.TestCase):
    """The 06:00 run shares this breaker, and its digest is the owner's notice.

    The nightly aborts before the digest on any non-zero exit from its runner, so a
    breaker that now exits non-zero would have taken the one message that explains the
    pause with it. It passes 75 through instead: digest first, code after.
    """

    def run_nightly(self, tmp, runner_body):
        root = Path(tmp)
        hub = root / "bin" / "hub"
        hub.mkdir(parents=True)
        (root / "vault" / "raw/workspaces/curator/proposals").mkdir(parents=True)
        shutil.copy2(ROOT / "bin" / "hub" / "nightly", hub / "nightly")
        sent = root / "sent.txt"
        (hub / "tg-send").write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" > '" + str(sent) + "'\n")
        (hub / "tg-send").chmod(0o755)
        (hub / "fake-curate").write_text("#!/bin/bash\n" + runner_body)
        (hub / "fake-curate").chmod(0o755)
        env = dict(os.environ, SOVS_VAULT=str(root / "vault"), CURATOR_LANE="curator",
                   SOV_TEMPLATE=str(root), SOV_STATE_DIR=str(root / "state"),
                   ARCHIVIST_RUNNER=str(hub / "fake-curate"))
        for key in ("SOV_HUB_DIGEST", "ARCHIVIST_DIGEST_ONLY_IF_NEW", "ARCHIVIST_SKIP_NIGHTLY"):
            env.pop(key, None)
        done = subprocess.run(["/bin/bash", str(hub / "nightly")], env=env,
                              capture_output=True, text=True, timeout=120)
        return done, (sent.read_text() if sent.exists() else "")

    def test_the_digest_goes_out_and_the_run_reports_the_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, sent = self.run_nightly(
                tmp, "echo '%s: 60 pending >= limit 50'\nexit %d\n" % (BREAKER, runner.PAUSED_EXIT))
            self.assertIn("BREAKER OPEN", sent, "the one message that explains the pause must still be sent")
            self.assertEqual(done.returncode, runner.PAUSED_EXIT, done.stdout + done.stderr)

    def test_a_real_failure_still_aborts_before_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, sent = self.run_nightly(tmp, "echo 'the model is unreachable' >&2\nexit 1\n")
            self.assertEqual(done.returncode, 1)
            self.assertEqual(sent, "", "a broken run sends no digest; the runner alerts instead")


class TheConditionHasAName(unittest.TestCase):
    """What `sov status` shows for a paused job."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.vault = base / "vault"
        self.vault.mkdir()
        self.state = base / "state"
        (self.state / "hub").mkdir(parents=True)
        (self.state / "hub" / "curate.last-output").write_text(
            "%s: 51 pending >= limit 50; no new sources judged\n" % BREAKER)
        self.row = {"last_run": 1700000000, "last_exit": runner.PAUSED_EXIT}

    def describe(self, job="curate", spec=None):
        return job_health.describe(job, self.row, spec or dict(manifest.JOBS[job]),
                                   self.state, ROOT, self.vault, 1700000100)

    def test_a_paused_curate_is_named_not_reported_as_a_failure(self):
        health = self.describe()
        self.assertEqual(health["state"], "paused")
        self.assertEqual(health["summary"], "Review queue full, curation paused")
        self.assertNotIn("failed", health["summary"].lower())
        self.assertIn("Review", health["action"], "the owner's next step is the gate, not a repair")

    def test_the_job_s_own_words_travel_with_it(self):
        self.assertIn("51 pending >= limit 50", self.describe()["why"])

    def test_any_other_job_pausing_is_still_not_a_failure(self):
        health = self.describe("burndown")
        self.assertEqual(health["state"], "paused")
        self.assertNotEqual(health["summary"], "Review queue full, curation paused",
                            "the named condition belongs to the job that reports it")

    def test_a_real_failure_is_untouched(self):
        self.row["last_exit"] = 1
        self.assertEqual(self.describe()["state"], "needs_attention")

    def test_a_clean_run_is_untouched(self):
        self.row["last_exit"] = 0
        self.assertEqual(self.describe()["state"], "healthy")


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
