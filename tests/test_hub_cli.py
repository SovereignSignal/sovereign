"""`sov hub status` has to answer on either kind of hub.

There are two: the app-installed managed hub, whose commands this module serves,
and the template-run hub, whose jobs live behind `sov hub jobs`. bin/sov routes
`status` here. On a machine running the template hub the managed config was never
written, so this used to raise and name no path, leaving the person who typed the
obvious command with nothing to go on.

Neither of these paths had a test before 2026-09-21; this module had none at all.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from sovereign_hub import cli  # noqa: E402


class StatusOnEitherHub(unittest.TestCase):

    def setUp(self):
        # realpath, because core.absolute() refuses a path with a symlinked parent
        # and macOS hands out temp dirs under /var, which is a link to /private/var.
        # That check is a real property of owner-controlled paths, not an obstacle.
        self.state = os.path.realpath(tempfile.mkdtemp())
        self.missing_config = os.path.join(os.path.realpath(tempfile.mkdtemp()), "hub", "config.json")

    def run_status(self):
        """Invoke the real entry point and capture what it prints.

        Captured, not printed: this command reports failure on stdout as JSON, and
        a test that lets its own expected failures onto the suite's output trains
        whoever reads it next to skim past errors there.
        """
        argv = ["sov-managed-hub", "status", "--config", self.missing_config]
        printed = io.StringIO()
        with mock.patch.dict(os.environ, {"SOV_STATE_DIR": self.state}), \
                contextlib.redirect_stdout(printed), \
                mock.patch.object(sys, "argv", argv):
            code = cli.main()
        self.printed = printed.getvalue()
        return code

    def test_a_template_hub_answers_with_its_job_table(self):
        Path(self.state, "hub.json").write_text(json.dumps({"vault": "/somewhere"}), encoding="utf-8")
        with mock.patch.object(cli.subprocess, "call", return_value=7) as called:
            self.assertEqual(self.run_status(), 7, "the delegated exit code is returned, not swallowed")
        self.assertEqual(called.call_count, 1)
        argv = called.call_args[0][0]
        self.assertEqual(argv[-2:], ["jobs", "status"])
        self.assertTrue(argv[1].endswith("sov-hub"), argv)

    def test_with_neither_hub_the_error_names_the_path_it_looked_for(self):
        # No hub.json in SOV_STATE_DIR, and the managed config does not exist.
        with mock.patch.object(cli.subprocess, "call") as never:
            out = self.run_status()
        self.assertFalse(never.called, "nothing is delegated when this is not a template hub")
        self.assertEqual(out, 65)
        # The path is the whole point: the error it replaced named none.
        self.assertIn(self.missing_config, self.printed)
        self.assertIn("sov hub jobs status", self.printed)

    def test_the_named_path_reaches_the_person_reading_the_output(self):
        from sovereign_hub import core
        with self.assertRaises(ValueError) as caught:
            core.load(self.missing_config)
        message = str(caught.exception)
        self.assertIn(os.path.basename(self.missing_config), message)
        self.assertIn("sov hub jobs status", message)

    def test_an_installed_managed_hub_is_not_diverted(self):
        """The delegation must be invisible to a machine that really has this hub.

        The config here is `{}`, so the managed hub rejects it at validation. That
        rejection IS the evidence: reaching validation means the request was served
        here and never handed to the template hub. Captured rather than printed,
        because a test that leaks an error onto the suite's output teaches whoever
        reads it next to ignore errors on the suite's output.
        """
        Path(self.state, "hub.json").write_text("{}", encoding="utf-8")
        real = Path(os.path.realpath(tempfile.mkdtemp()))
        (real / "config.json").write_text("{}", encoding="utf-8")
        printed = io.StringIO()
        with mock.patch.object(cli.subprocess, "call") as never, \
                mock.patch.dict(os.environ, {"SOV_STATE_DIR": self.state}), \
                contextlib.redirect_stdout(printed), \
                mock.patch.object(sys, "argv",
                                  ["sov-managed-hub", "status", "--config", str(real / "config.json")]):
            cli.main()
        self.assertFalse(never.called, "an existing managed config is served by the managed hub")
        self.assertIn("macOS only", printed.getvalue(),
                      "it got as far as validating the managed config, which is the point")


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
