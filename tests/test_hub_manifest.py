"""The manifest is the one place hub jobs are defined. Every job renders to a launchd item
whose program is the resolver's interpreter running the hub runner, never the Xcode shim."""
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import manifest  # noqa: E402


class Manifest(unittest.TestCase):
    def test_every_job_has_a_program_a_schedule_and_a_description(self):
        self.assertGreaterEqual(len(manifest.JOBS), 10)
        for job_id, spec in manifest.JOBS.items():
            self.assertRegex(job_id, r"^[a-z][a-z0-9-]*$")
            self.assertTrue(spec["program"], job_id)
            self.assertTrue(spec["description"], job_id)
            self.assertTrue(("interval_s" in spec) ^ ("hour" in spec), job_id)

    def test_render_names_the_runner_on_the_given_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item = manifest.render("nightly", manifest.JOBS["nightly"], ROOT, "/opt/py/bin/python3", tmp / "state", tmp / "home")
            self.assertEqual(item["Label"], "com.sovereign.hub.nightly")
            self.assertEqual(item["ProgramArguments"][:3], ["/opt/py/bin/python3", "-B", str(ROOT / "bin" / "sov-hub")])
            self.assertEqual(item["ProgramArguments"][3:], ["tick", "nightly"])
            self.assertEqual(item["StartCalendarInterval"], {"Hour": 6, "Minute": 0})
            self.assertNotIn("StartInterval", item)
            self.assertTrue(item["StandardErrorPath"].endswith("hub/nightly.error.log"))
            self.assertNotIn("/usr/bin/python3", str(item))
            plistlib.dumps(item)  # serialisable

    def test_interval_jobs_render_with_start_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item = manifest.render("verdict-poll", manifest.JOBS["verdict-poll"], ROOT, "/opt/py/bin/python3", tmp, tmp)
            self.assertEqual(item["StartInterval"], 60)
            self.assertNotIn("StartCalendarInterval", item)

    def test_weekday_jobs_carry_the_weekday(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item = manifest.render("weekly-audit", manifest.JOBS["weekly-audit"], ROOT, "/opt/py/bin/python3", tmp, tmp)
            self.assertEqual(item["StartCalendarInterval"], {"Hour": 10, "Minute": 0, "Weekday": 5})

    def test_instance_jobs_join_the_manifest_without_replacing_it(self):
        inst = {"instance_jobs": {"health": {"program": "/opt/venv/bin/python3", "args": ["/opt/scripts/health.py"],
                                             "hour": 9, "minute": 0, "deliver": True, "description": "Daily health"}}}
        jobs = manifest.all_jobs(inst)
        self.assertIn("nightly", jobs)
        self.assertEqual(jobs["health"]["program"], "/opt/venv/bin/python3")
        with self.assertRaises(ValueError):
            manifest.all_jobs({"instance_jobs": {"nightly": {"program": "/x", "hour": 1, "minute": 0}}})

    def test_managed_hub_jobs_are_a_view_of_the_manifest(self):
        from sovereign_hub import core
        for job_id in ("nightly", "snapshot"):
            self.assertEqual(core.JOBS[job_id]["hour"], manifest.JOBS[job_id]["hour"])
            self.assertEqual(core.JOBS[job_id]["minute"], manifest.JOBS[job_id]["minute"])
        self.assertEqual(core.JOBS["audit"]["hour"], manifest.JOBS["weekly-audit"]["hour"])
        self.assertEqual(core.JOBS["audit"]["weekday"], manifest.JOBS["weekly-audit"]["weekday"])


if __name__ == "__main__":
    unittest.main()
