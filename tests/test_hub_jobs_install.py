"""sov hub jobs install renders every job, says what would change, and on --apply writes
only that, loading through launchctl and rolling back if a bootstrap fails. Retiring the
hand-written jobs is explicit, parks the plists, and never deletes."""
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import jobs, instance, manifest  # noqa: E402

STUB = "#!/bin/bash\nprintf '%s %s\\n' \"$(basename \"$0\")\" \"$*\" >> \"$SOV_STUB_LOG\"\n[ \"$1\" = print ] && exit 1\nexit \"${SOV_STUB_RC:-0}\"\n"


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp); self.home = self.tmp / "home"; self.state = self.tmp / "state"
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True); self.state.mkdir()
        self.log = self.tmp / "stub.log"; self.log.write_text(""); os.environ["SOV_STUB_LOG"] = str(self.log)
        self.ctl = self.tmp / "launchctl"; self.ctl.write_text(STUB); self.ctl.chmod(0o755)
        instance.write(self.state, {"vault": str(self.tmp / "v"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "instance_jobs": {"health": {"program": "/opt/x/health", "hour": 9, "minute": 0, "deliver": True, "description": "t"}}})

    def plan(self, **kw):
        return jobs.plan(self.state, ROOT, self.home, "/opt/py/bin/python3", **kw)

    def agents(self):
        return sorted(p.name for p in (self.home / "Library" / "LaunchAgents").glob("*.plist"))


class Install(unittest.TestCase):
    def test_dry_run_plans_every_job_and_writes_nothing(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); p = b.plan()
            labels = {i["label"] for i in p["items"]}
            self.assertIn("com.sovereign.hub.nightly", labels); self.assertIn("com.sovereign.hub.health", labels)
            self.assertEqual(len(labels), len(manifest.JOBS) + 1)
            self.assertTrue(all(i["action"] == "create" for i in p["items"]))
            self.assertEqual(b.agents(), [])
            self.assertEqual(b.log.read_text(), "")

    def test_apply_writes_and_loads_then_a_second_plan_is_all_unchanged(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); r = jobs.apply(b.plan(), str(b.ctl), b.home)
            self.assertEqual(len(r["written"]), len(manifest.JOBS) + 1)
            self.assertIn("com.sovereign.hub.nightly.plist", b.agents())
            self.assertIn("bootstrap", b.log.read_text())
            item = plistlib.loads((b.home / "Library" / "LaunchAgents" / "com.sovereign.hub.nightly.plist").read_bytes())
            self.assertEqual(item["ProgramArguments"][0], "/opt/py/bin/python3")
            p2 = b.plan()
            self.assertTrue(all(i["action"] == "unchanged" for i in p2["items"]))
            b.log.write_text(""); r2 = jobs.apply(p2, str(b.ctl), b.home)
            self.assertEqual(r2["written"], []); self.assertEqual(b.log.read_text(), "", "unchanged jobs are not reloaded")

    def test_a_changed_schedule_is_a_replace(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); jobs.apply(b.plan(), str(b.ctl), b.home)
            inst = instance.load(b.state); inst["instance_jobs"]["health"]["minute"] = 30
            (b.state / "hub.json").write_text(json.dumps(inst))
            p = b.plan(); byl = {i["label"]: i["action"] for i in p["items"]}
            self.assertEqual(byl["com.sovereign.hub.health"], "replace")
            self.assertEqual(byl["com.sovereign.hub.nightly"], "unchanged")

    def test_retire_legacy_parks_matching_plists_and_only_those(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); la = b.home / "Library" / "LaunchAgents"
            (la / "com.old.cron.nightly.plist").write_bytes(plistlib.dumps({"Label": "com.old.cron.nightly"}))
            (la / "com.other.thing.plist").write_bytes(plistlib.dumps({"Label": "com.other.thing"}))
            p = b.plan(retire_prefix="com.old.cron.")
            self.assertEqual([Path(x).name for x in p["retire"]], ["com.old.cron.nightly.plist"])
            jobs.apply(p, str(b.ctl), b.home)
            self.assertFalse((la / "com.old.cron.nightly.plist").exists())
            self.assertTrue((la / "sovereign-retired" / "com.old.cron.nightly.plist").exists())
            self.assertTrue((la / "com.other.thing.plist").exists())
            self.assertIn("bootout gui/%d/com.old.cron.nightly" % os.getuid(), b.log.read_text())

    def test_a_failed_bootstrap_rolls_back_what_this_apply_created(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); os.environ["SOV_STUB_RC"] = "1"
            try:
                with self.assertRaises(ValueError):
                    jobs.apply(b.plan(), str(b.ctl), b.home)
            finally:
                del os.environ["SOV_STUB_RC"]
            self.assertEqual(b.agents(), [], "nothing left behind")

    def test_status_reads_the_runner_receipts(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); hub = b.state / "hub"; hub.mkdir()
            (hub / "nightly.last-run").write_text("1700000000\n"); (hub / "nightly.last-ok").write_text("1700000000\n"); (hub / "nightly.last-exit").write_text("0\n")
            rows = {r["job"]: r for r in jobs.status(b.state, ROOT)}
            self.assertEqual(rows["nightly"]["last_exit"], 0); self.assertEqual(rows["nightly"]["last_run"], 1700000000)
            self.assertIsNone(rows["burndown"]["last_run"])
            self.assertEqual(rows["health"]["schedule"], "09:00 daily")

    def test_uninstall_parks_only_hub_jobs(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            b = Box(tmp); jobs.apply(b.plan(), str(b.ctl), b.home); la = b.home / "Library" / "LaunchAgents"
            (la / "com.other.thing.plist").write_bytes(plistlib.dumps({"Label": "com.other.thing"}))
            would = jobs.uninstall(b.state, ROOT, b.home, str(b.ctl), apply_=False)
            self.assertEqual(len(would), len(manifest.JOBS) + 1); self.assertIn("com.sovereign.hub.nightly.plist", b.agents())
            jobs.uninstall(b.state, ROOT, b.home, str(b.ctl), apply_=True)
            self.assertEqual(b.agents(), ["com.other.thing.plist"])
            self.assertTrue((la / "sovereign-retired" / "com.sovereign.hub.nightly.plist").exists())


if __name__ == "__main__":
    unittest.main()
