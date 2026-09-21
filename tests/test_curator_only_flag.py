"""--only names files the ordinary ordering was never going to reach.

Which means they are usually old, and two things then go wrong quietly.

The mtime window still applies after the --only filter, so a listed file older than
the watermark is skipped and the run reports success having judged a fraction of
the list. On 2026-09-21, 42 of 46 documents predated the watermark: the run would
have judged four and looked fine.

Worse, a run without --since-days writes the watermark to now at the end, held back
only for errored and deferred files. A small --only run defers nothing, so it would
jump the watermark forward and strand every unjudged item the nightly is still
draining - 2,360 of them that day.

Neither fails loudly on its own, so the flag refuses the combination instead. These
cases hold that refusal in place, and hold the empty-list refusal beside it: "judge
nothing" and "judge everything" must not be one typo apart.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "bin" / "curator-run"


def run(args):
    """Invoke the real script, because the guard has to hold at the entry point."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
           "PYTHONPATH": str(ROOT / "lib"), "SOVS_VAULT": tempfile.mkdtemp()}
    return subprocess.run([sys.executable, str(CURATOR)] + args,
                          capture_output=True, text=True, timeout=120, env=env)


def listing(lines):
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    handle.write("\n".join(lines) + "\n")
    handle.close()
    return handle.name


class OnlyRequiresAnExplicitWindow(unittest.TestCase):

    def test_only_without_since_days_refuses(self):
        done = run(["--only", listing(["raw/tools/Somewhere/a.docx"])])
        self.assertEqual(done.returncode, 1)
        self.assertIn("--only requires --since-days", done.stdout + done.stderr)

    def test_the_refusal_explains_both_hazards(self):
        """A reader who does not know the watermark exists has to learn it here."""
        said = run(["--only", listing(["raw/tools/Somewhere/a.docx"])]).stdout + \
            run(["--only", listing(["raw/tools/Somewhere/a.docx"])]).stderr
        self.assertIn("silently skipped", said, "the window hazard")
        self.assertIn("strand", said, "the watermark hazard")

    def test_with_since_days_it_proceeds(self):
        done = run(["--only", listing(["raw/tools/Somewhere/a.docx"]),
                    "--since-days", "110", "--dry"])
        self.assertNotIn("--only requires --since-days", done.stdout + done.stderr)


class AnEmptyListIsNotNoRestriction(unittest.TestCase):

    def test_an_empty_list_refuses(self):
        done = run(["--only", listing(["# nothing but a comment"]), "--since-days", "110"])
        self.assertEqual(done.returncode, 1)
        self.assertIn("is empty", done.stdout + done.stderr)

    def test_an_unreadable_list_refuses(self):
        done = run(["--only", "/nonexistent/list.txt", "--since-days", "110"])
        self.assertEqual(done.returncode, 1)
        self.assertIn("cannot read --only list", done.stdout + done.stderr)


class TheWatermarkIsOnlyMovedByAnImplicitWindow(unittest.TestCase):
    """The property --since-days relies on, asserted rather than assumed."""

    def test_the_write_is_gated_on_an_absent_since_days(self):
        source = CURATOR.read_text(encoding="utf-8")
        index = source.index('open(WM, "w").write(str(wm_val))')
        preceding = source[:index]
        guard = preceding.rindex("if a.since_days is None:")
        self.assertLess(preceding[guard:].count("\n"), 12,
                        "the watermark write must stay inside the `a.since_days is None` "
                        "branch; an explicit window is a backfill and never moves it")


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
