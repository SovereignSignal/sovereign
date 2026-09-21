"""The continuous curation pilot: its cap, and the config trap it nearly walked into.

Owner decision 2026-09-21, in his words: "we can't gate progress to that window
every night; why aren't we running continuously and when things pop up we address
them." A curate tick every two hours, --max 50, four auto-promotions per tick so
the daily ceiling stays near the twelve the nightly already had. Cadence and cap
only: no judge, prompt, threshold or promotion-logic change.

Two things nearly went wrong quietly, and both are held here.

The cap was first proposed as an "env" key on the job spec. render() writes a FIXED
EnvironmentVariables dict, so nothing would have read it: the manifest would have
shown the cap, the plist would have loaded, the job would have run at the default
twelve, and only the promotions would have said otherwise days later. A spec key
nothing reads is now an error.

Then the obvious fix had its own trap: bin/hub/nightly runs $HERE/curate, the same
script, so a hardcoded default of 4 would have cut the nightly from twelve to four
as a side effect - not a cadence change but a change to how much lands unreviewed.
So curate defaults to 4 and the nightly states 12.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from sovereign_hub import manifest  # noqa: E402


class TheSpecRejectsWhatNothingReads(unittest.TestCase):

    def spec(self, **extra):
        base = {"program": "hub/curate", "interval_s": 7200, "deliver": False,
                "description": "x"}
        base.update(extra)
        return base

    def render(self, spec):
        return manifest.render("curate", spec, str(ROOT), sys.executable, "/tmp/state", "/tmp/home")

    def test_a_good_spec_renders(self):
        item = self.render(self.spec())
        self.assertEqual(item["StartInterval"], 7200)

    def test_an_unrecognised_key_is_refused(self):
        """The exact mistake: a cap declared where nothing would have read it."""
        with self.assertRaises(ValueError) as caught:
            self.render(self.spec(env={"ARCHIVIST_AUTO_PROMOTE_MAX": "4"}))
        message = str(caught.exception)
        self.assertIn("env", message)
        self.assertIn("would render and run", message,
                      "the message must say WHY silence is the danger")

    def test_the_refusal_lists_what_is_allowed(self):
        with self.assertRaises(ValueError) as caught:
            self.render(self.spec(schedule="hourly"))
        self.assertIn("interval_s", str(caught.exception))

    def test_an_instance_job_carrying_every_real_key_renders(self):
        """instance_jobs carry keys the shipped ones do not — `args` above all.

        The first version of KNOWN_SPEC_KEYS was enumerated from the jobs this file
        ships, so it omitted `args`, which runner.py passes to the program and which
        all five of one hub's instance jobs carry. The validator would have raised on
        the first of them and broken `sov hub jobs install --apply` on that machine.
        These are the exact keys that hub's instance_jobs use between them.
        """
        for schedule in ({"hour": 9, "minute": 0},
                         {"hours": [0, 6, 12, 18], "minute": 15},
                         {"interval_s": 900}):
            spec = dict({"program": "hub/x", "args": ["--json"], "deliver": True,
                         "description": "an instance job"}, **schedule)
            with self.subTest(schedule=sorted(schedule)):
                item = manifest.render("instance-job", spec, str(ROOT), sys.executable,
                                       "/tmp/state", "/tmp/home")
                self.assertTrue(item["Label"].endswith("instance-job"))

    def test_every_shipped_job_passes_its_own_validator(self):
        """A validator that rejects the manifest it ships with is worse than none."""
        for job_id, spec in manifest.JOBS.items():
            with self.subTest(job=job_id):
                manifest.validate_spec(job_id, spec)


class TheCurateTickIsDeclared(unittest.TestCase):

    def test_it_runs_every_two_hours(self):
        spec = manifest.JOBS["curate"]
        self.assertEqual(spec["interval_s"], 7200)
        self.assertEqual(spec["program"], "hub/curate")

    def test_it_does_not_deliver(self):
        """The 06:00 nightly stays the daily digest; a tick is not a notification."""
        self.assertFalse(manifest.JOBS["curate"]["deliver"])


class TheCapDependsOnWhoIsCalling(unittest.TestCase):
    """One script, two callers, and the number written down in both."""

    def test_curate_defaults_to_four_and_respects_an_existing_value(self):
        source = (ROOT / "bin" / "hub" / "curate").read_text(encoding="utf-8")
        self.assertRegex(source, r':\s*"\$\{ARCHIVIST_AUTO_PROMOTE_MAX:=4\}"',
                         "the tick default is 4, assigned only when unset")
        self.assertIn("export ARCHIVIST_AUTO_PROMOTE_MAX", source)

    def test_the_nightly_states_twelve_before_invoking_the_runner(self):
        source = (ROOT / "bin" / "hub" / "nightly").read_text(encoding="utf-8")
        export = source.index('ARCHIVIST_AUTO_PROMOTE_MAX="${ARCHIVIST_AUTO_PROMOTE_MAX:-12}"')
        runner = source.index('RUNNER="${ARCHIVIST_RUNNER:-$HERE/curate}"')
        self.assertLess(export, runner, "the cap must be set before the runner is chosen")

    def test_the_nightly_and_the_tick_do_not_share_a_number(self):
        """If these ever converge, one of the two callers changed silently."""
        nightly = (ROOT / "bin" / "hub" / "nightly").read_text(encoding="utf-8")
        curate = (ROOT / "bin" / "hub" / "curate").read_text(encoding="utf-8")
        self.assertIsNotNone(re.search(r"ARCHIVIST_AUTO_PROMOTE_MAX:-12", nightly))
        self.assertIsNotNone(re.search(r"ARCHIVIST_AUTO_PROMOTE_MAX:=4", curate))


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
