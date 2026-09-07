"""The console's Run-now buttons: what a click is asking for.

Every tool used to have a job of its own, so "Run mirror now" on a lane could only mean
one thing: kick that job. With one shared job carrying every lane, kicking the job no
longer runs the lane that was clicked -- it restarts the whole tick, cutting short
whatever other lane is mid-copy, and returns "started" as if it had done what was asked.

So a lane row has to name the lane. The runner already takes one by name (`--only`), and
this file pins both halves: the page names it, and the runner really runs exactly that one
lane when it is named.

The page is checked as shipped text rather than in a browser -- the console is one HTML
file with no build step and no test harness in it -- so the assertions are about the
buttons the page renders and the message the click handler sends.
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_connectors_runner import PATH, PY, RUNNER, declare, entry

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "apps" / "console" / "ui" / "index.html"
RUN_NOW = "Run mirror now"


def page():
    return PAGE.read_text(encoding="utf-8")


def inspector(text, kind):
    """The INSPECTOR branch for one kind of row: the branch that draws an action bar.

    Each kind is rendered twice -- once as a list row, once as the panel beside it -- and
    only the panel carries buttons, so the branch is found by that rather than by its
    position in the file."""
    starts = [m.start() for m in re.finditer(r'it\.kind === "%s"' % kind, text)]
    assert starts, "the console has no %s branch at all" % kind
    for i in starts:
        ends = [m.start() for m in re.finditer(r'if \(it\.kind ===|const j = o;', text[i + 1:])]
        chunk = text[i:i + 1 + ends[0]] if ends else text[i:]
        if 'class="acts"' in chunk:
            return chunk
    raise AssertionError("no %s branch draws an action bar" % kind)


def button_templates(text):
    """Every <button> template in a piece of the page, tag text only."""
    return re.findall(r"<button[^>]*>", text)


def kickstart_buttons(text):
    return [b for b in button_templates(text) if 'data-act="kickstart"' in b]


def builders(text):
    """The helper functions that render a kickstart button, by name. One helper is the
    point: a second, hand-rolled copy is how one row keeps the old behaviour."""
    out = []
    for m in re.finditer(r"function (\w+)\(([^)]*)\)\s*\{", text):
        body = text[m.end():text.index("\n  }", m.end())]
        if 'data-act="kickstart"' in body:
            out.append((m.group(1), body))
    return out


class TheLaneButtonNamesTheLane(unittest.TestCase):
    """A lane inside the shared job is not the job. The row that was clicked has to say
    which lane it is, or the bridge can only restart everything."""

    def setUp(self):
        self.text = page()
        self.assertIn(RUN_NOW, self.text, "the console has no Run-now button at all")
        self.helpers = builders(self.text)
        self.assertTrue(self.helpers, "no helper renders the Run-now button; every row builds "
                                      "its own and they cannot be checked together")

    def test_the_button_carries_the_lane_and_not_only_the_job_that_kicks_it(self):
        named = [name for name, body in self.helpers if "data-lane" in body]
        self.assertTrue(named,
                        "the Run-now button names only the job that kicks the lane. On the "
                        "shared connector job that job carries every lane there is, so the "
                        "click restarts the whole tick instead of running the lane it names.")

    def test_a_lane_with_a_job_of_its_own_is_still_kicked_by_that_job(self):
        """A calendar-cadence pull, or a lane a legacy per-tool job still carries: there
        the job IS the lane, and the shared runner would refuse a lane it never ticks."""
        bodies = [b for _, b in self.helpers if "data-lane" in b]
        self.assertTrue(any(re.search(r"(kick|job)[^\n]*===[^\n]*label|label[^\n]*===[^\n]*(kick|job)", b)
                            for b in bodies),
                        "the button names a lane unconditionally: a lane whose own job carries "
                        "it would be handed to the shared runner, which never ticks it")

    def test_the_lane_row_and_the_tool_row_both_use_it(self):
        """These are the two rows a person clicks Run-now on for a lane."""
        names = [name for name, body in self.helpers if "data-lane" in body]
        for what in ("lane", "tool"):
            with self.subTest(row=what):
                chunk = inspector(self.text, what)
                self.assertTrue(any(("%s(" % n) in chunk for n in names),
                                "the %s row builds its own Run-now button instead of the one "
                                "that names the lane: clicking it restarts the whole tick.\n%s"
                                % (what, chunk[-400:]))
                self.assertEqual(kickstart_buttons(chunk), [],
                                 "the %s row still writes a kickstart button by hand" % what)

    def test_the_click_sends_the_lane_to_the_bridge(self):
        """Naming it in the markup and dropping it at the click is the same defect one
        step later."""
        i = self.text.index('act === "kickstart"')
        handler = self.text[i:self.text.index('act === "reveal"', i)]
        self.assertIn("dataset.lane", handler,
                      "the click handler ignores the lane the button names")
        self.assertRegex(handler, r"lane\s*[:=]",
                         "the message the bridge receives carries no lane, so the bridge can "
                         "only kick the job: " + handler.strip()[:200])
        self.assertIn("cmd:", handler)


class TheRunnerRunsTheLaneItIsGiven(unittest.TestCase):
    """The other half of the contract the button relies on: a single lane, by name, and
    nothing else on the machine touched."""

    def box(self, tmp):
        state, home, out = Path(tmp) / "state", Path(tmp) / "home", Path(tmp) / "out"
        home.mkdir()
        out.mkdir()
        (home / ".brain-host").write_text("testbox")
        declare(state, {h: entry(tmp, h, 'echo x >> "%s/%s"' % (out, h)) for h in ("one", "two")})
        return state, home, out

    def run_only(self, state, home, lane):
        return subprocess.run([PY, str(RUNNER), "--only", lane], capture_output=True, text=True,
                              env={"HOME": str(home), "PATH": PATH, "SOV_STATE_DIR": str(state),
                                   "SOV_MANIFEST": str(state / "connectors.json")}, timeout=120)

    def test_only_runs_the_lane_it_names_and_leaves_the_others_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, out = self.box(tmp)
            r = self.run_only(state, home, "one")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual((out / "one").read_text().count("\n"), 1)
            self.assertFalse((out / "two").exists(),
                             "running one lane by name ran another lane too: on a real machine "
                             "that is a mid-copy mirror cut short by a button someone pressed "
                             "on a different row")
            runs = json.loads((state / "runs.json").read_text())
            self.assertEqual(runs["runner"]["lanes_ran"], 1)

    def test_a_lane_the_runner_does_not_have_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home, _ = self.box(tmp)
            r = self.run_only(state, home, "nosuchlane")
            self.assertEqual(r.returncode, 64)
            self.assertIn("nosuchlane", r.stderr)


if __name__ == "__main__":
    unittest.main()
