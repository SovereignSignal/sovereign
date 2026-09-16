"""The runner is the wrapper every hub job runs through: receipts, one log line, an
alert on failure, delivery of clean output when the job says so. Semantics match the
hand-written wrapper it replaces, so a cutover changes nothing the owner sees."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import runner, instance, manifest  # noqa: E402

NOTIFY = "#!/bin/bash\nprintf 'channel=%s\\n%s\\n' \"${TG_ENV_FILE:-}\" \"$*\" >> \"$SOV_STUB_LOG\"\ncat >> \"$SOV_STUB_LOG\"\nexit 0\n"


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp); self.state = self.tmp / "state"; self.template = self.tmp / "template"
        (self.template / "bin" / "hub").mkdir(parents=True); (self.state / "hub").mkdir(parents=True)
        self.log = self.tmp / "notify.log"; self.log.write_text("")
        self.notify = self.tmp / "notify"; self.notify.write_text(NOTIFY); self.notify.chmod(0o755)
        (self.tmp / "v").mkdir()
        instance.write(self.state, {"vault": str(self.tmp / "v"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "notify": {"alerts": str(self.tmp / "alerts.env"), "archive": str(self.tmp / "archive.env")}})
        (self.tmp / "alerts.env").write_text("TG_BOT_TOKEN=x\nTG_CHAT_ID=y\n")
        (self.tmp / "archive.env").write_text("TG_BOT_TOKEN=x\nTG_CHAT_ID=z\n")
        os.environ["SOV_STUB_LOG"] = str(self.log)

    def job(self, name, body, **spec):
        p = self.template / "bin" / "hub" / name
        p.write_text("#!/bin/bash\n" + body); p.chmod(0o755)
        entry = dict(program="hub/" + name, interval_s=60, deliver=False, description="t"); entry.update(spec)
        manifest.JOBS[name] = entry
        return name

    def tick(self, name):
        return runner.tick(name, self.state, self.template, str(self.notify))

    def receipt(self, name, kind):
        return (self.state / "hub" / (name + "." + kind)).read_text()


class Runner(unittest.TestCase):
    def tearDown(self):
        for k in [k for k in manifest.JOBS if k.startswith("t-")]:
            del manifest.JOBS[k]

    def test_a_clean_quiet_run_leaves_receipts_and_no_message(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); j = b.job("t-quiet", 'echo "$CURATOR_LANE" > "$SOV_STATE_DIR/saw-env"\n')
            self.assertEqual(b.tick(j), 0)
            self.assertTrue(b.receipt(j, "last-run").strip().isdigit())
            self.assertEqual(b.receipt(j, "last-ok"), b.receipt(j, "last-run"))
            self.assertEqual(b.receipt(j, "last-exit").strip(), "0")
            self.assertEqual((b.state / "saw-env").read_text().strip(), "curator", "the job did not get the instance env")
            self.assertEqual(b.log.read_text(), "", "nothing to say, nothing sent")
            line = (b.state / "hub" / "runs.log").read_text().strip().splitlines()[-1]
            self.assertIn("job=t-quiet exit=0", line)

    def test_a_deliver_job_sends_its_output_on_the_archive_channel(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); j = b.job("t-say", 'echo "hello owner"\n', deliver=True)
            self.assertEqual(b.tick(j), 0)
            sent = b.log.read_text()
            self.assertIn("hello owner", sent)
            self.assertIn("archive.env", sent, "delivery rides the archive channel")

    def test_a_failing_run_alerts_with_the_tail_and_keeps_last_ok(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); j = b.job("t-fail", 'for i in $(seq 1 30); do echo "line $i"; done; echo boom >&2; exit 3\n')
            self.assertEqual(b.tick(j), 3)
            self.assertEqual(b.receipt(j, "last-exit").strip(), "3")
            self.assertFalse((b.state / "hub" / "t-fail.last-ok").exists())
            sent = b.log.read_text()
            self.assertIn("ALERT t-fail exit 3", sent)
            self.assertIn("line 30", sent); self.assertIn("boom", sent)
            self.assertNotIn("line 10\n", sent, "only the tail travels")
            self.assertIn("alerts.env", sent, "alerts ride the alerts channel")

    def test_a_missing_program_is_a_loud_failure_not_a_silent_zero(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); manifest.JOBS["t-gone"] = {"program": "hub/does-not-exist", "interval_s": 60, "deliver": False, "description": "t"}
            self.assertNotEqual(b.tick("t-gone"), 0)
            self.assertIn("ALERT t-gone", b.log.read_text())

    def test_the_cli_entry_ticks_and_prints_env(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp)
            # a subprocess cannot see this process's manifest, so the job is declared the real
            # way an owner adds one: as an instance job in hub.json with an absolute program
            script = b.template / "bin" / "hub" / "t-cli"; script.write_text("#!/bin/bash\necho ok\n"); script.chmod(0o755)
            import json
            inst = json.loads((b.state / "hub.json").read_text())
            inst["instance_jobs"] = {"t-cli": {"program": str(script), "interval_s": 60, "deliver": False, "description": "t"}}
            (b.state / "hub.json").write_text(json.dumps(inst))
            env = dict(os.environ, SOV_STATE_DIR=str(b.state), SOV_NOTIFY=str(b.notify), SOV_TEMPLATE=str(b.template))
            r = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-hub"), "tick", "t-cli"], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-hub"), "env"], env=env, capture_output=True, text=True, timeout=60)
            self.assertIn("export CURATOR_LANE='curator'", r.stdout)
            r = subprocess.run(["/bin/bash", str(ROOT / "bin" / "sov"), "hub", "env"], env=env, capture_output=True, text=True, timeout=60)
            self.assertIn("export CURATOR_LANE='curator'", r.stdout, "the front door routes sov hub env")


if __name__ == "__main__":
    unittest.main()
