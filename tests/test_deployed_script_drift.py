"""Does the exporter that ran on a producer match the copy vendored here?

The scripts entered the repo on 2026-09-21 and nothing compared the two sides, so
the repo could say one thing while the machines did another and no one would know.
The exporter hashes itself into its heartbeat tag; this compares that with the
vendored copy.

Four states, and three of the four must stay quiet. A drift alarm that fires when
nothing is wrong is the failure this archive keeps meeting: a preflight that
watched the wrong number, a guard red for five days over a variable name, a
column of `info` findings that taught the eye to skip it.
"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load():
    """sov-status is an executable with no .py suffix."""
    import importlib.machinery
    import importlib.util
    spec = importlib.util.spec_from_loader(
        "sov_status", importlib.machinery.SourceFileLoader("sov_status", str(ROOT / "bin" / "sov-status")))
    module = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["sov-status", "--json"]
    try:
        spec.loader.exec_module(module)
    except SystemExit:                                     # argv parsing, not our concern
        pass
    finally:
        sys.argv = saved
    return module


TAG = """object 0000000000000000000000000000000000000000
type commit
tag hb-local
tagger somebody <somebody@somewhere> 1789128602 +0000

heartbeat
%s"""


class DeployedScriptDrift(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def setUp(self):
        self.template = Path(tempfile.mkdtemp())
        (self.template / "connectors" / "producers").mkdir(parents=True)
        self.vendored = self.template / "connectors" / "producers" / "alpha-brain-daily"

    def check(self, tag_body, vendored_text="the vendored script\n", vendor=True, rc=0):
        if vendor:
            self.vendored.write_text(vendored_text, encoding="utf-8")
        def answer(argv, **kw):
            if "cat-file" in argv:
                return subprocess.CompletedProcess(argv, rc, stdout=TAG % tag_body, stderr="")
            if "rev-parse" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="abc1234\n", stderr="")
            raise AssertionError("unexpected command: %r" % (argv,))
        with mock.patch.object(self.m, "TEMPLATE_ROOT", str(self.template)), \
                mock.patch.object(self.m.subprocess, "run", side_effect=answer):
            return self.m.deployed_script_drift("alpha", "/archive")

    def sha(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def test_a_matching_script_says_nothing(self):
        text = "the vendored script\n"
        self.assertIsNone(self.check("\nscript_sha: " + self.sha(text), text))

    def test_a_mismatch_names_both_sides_and_which_is_which(self):
        ran = "f" * 64
        found = self.check("\nscript_sha: " + ran)
        self.assertIsNotNone(found)
        self.assertEqual(found["level"], "warn")
        text = found["text"]
        self.assertIn("ran " + ran[:8], text)
        self.assertIn("vendored " + self.sha("the vendored script\n")[:8], text)
        # Being behind the exchange produces this same observation, so say so here
        # rather than let it be investigated as a leak.
        self.assertIn("pull before investigating", text)
        self.assertIn("2026-09-11", text, "the heartbeat's own time, so a stale tag is visible")
        self.assertIn("at abc1234", text, "this checkout's revision, so 'I am behind' is one read")
        self.assertNotIn("tagger", text, "the tag body does not leak into the finding")

    def test_no_vendored_copy_says_nothing(self):
        """A lane never brought into the repo is not drifting from anything."""
        self.assertIsNone(self.check("\nscript_sha: " + "f" * 64, vendor=False))

    def test_a_heartbeat_without_the_hash_says_nothing(self):
        """Every exporter predates this field until it is deployed; silence, not alarm."""
        self.assertIsNone(self.check(""))
        self.assertIsNone(self.check("\ncoverage: {\"documents\":7}"))

    def test_an_unreadable_heartbeat_says_nothing(self):
        """No tag yet, or a lane that never pushes one. Absence is not drift."""
        self.assertIsNone(self.check("\nscript_sha: " + "f" * 64, rc=1))

    def test_a_malformed_hash_is_not_treated_as_one(self):
        for body in ("\nscript_sha: notahash", "\nscript_sha: " + "f" * 63, "\nscript_sha:"):
            with self.subTest(body=body):
                self.assertIsNone(self.check(body))

    def test_the_real_vendored_scripts_are_hashed_not_guessed(self):
        """Against the actual repo: each vendored exporter hashes to something."""
        for name in ("spp3", "uniclaude"):
            path = ROOT / "connectors" / "producers" / (name + "-brain-daily")
            if not path.exists():                          # pragma: no cover
                continue
            with self.subTest(lane=name):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(len(digest), 64)
                self.assertIsNone(self.check("\nscript_sha: " + digest,
                                             vendored_text=path.read_text(encoding="utf-8")))


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
