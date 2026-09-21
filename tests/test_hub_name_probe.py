"""The guard's hub probe, checked in all three states a machine can be in.

Every other probe in test_template_is_general is built from the machine running
it, which means a client can never catch the hub's name. On 2026-09-21 two
vendored scripts said "fenced and merged by <hub>", the laptop's run was green
with those files staged, and the guard only went red once the commit reached the
hub - by which point it was one scheduled job away from being published.

The probe added there reads ~/.brain-hub and takes the alias before the colon.
These cases fix its three states so the next edit cannot quietly lose one:
pointed at a hub whose name appears in a file, pointed at a clean one, and
pointed at no hub at all. That last is the one worth guarding: a standalone
instance has no hub name to leak, and a probe that fails on every unwired machine
is a red check nobody reads.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_template_is_general as guard  # noqa: E402


class HubProbe(unittest.TestCase):

    def setUp(self):
        self.case = guard.NothingNamesThisMachine("test_no_shipped_file_names_the_hub_this_machine_points_at")

    def run_probe(self, hub_pointer, shipped_lines):
        """Run the real test method against a fixed pointer and a fixed shipped file."""
        shipped = Path(tempfile.mkdtemp()) / "a-shipped-file"
        shipped.write_text("\n".join(shipped_lines) + "\n", encoding="utf-8")
        with mock.patch.object(guard, "pointer", return_value=hub_pointer), \
                mock.patch.object(guard, "shipped", return_value=[shipped]), \
                mock.patch.object(guard, "ROOT", shipped.parent):
            result = unittest.TestResult()
            self.case.run(result)
            return result

    def test_a_hub_name_in_a_shipped_file_is_caught(self):
        result = self.run_probe("somehub:/somewhere/archive",
                                ["fenced and merged by somehub).", "an ordinary line"])
        self.assertEqual(len(result.failures), 1, "the hub name must be caught")
        message = result.failures[0][1]
        self.assertIn("hub name 'somehub' matched", message)
        self.assertIn("a-shipped-file:1", message, "the failure names file and line")

    def test_a_clean_tree_passes(self):
        result = self.run_probe("somehub:/somewhere/archive",
                                ["fenced and merged by the hub).", "nothing to see"])
        self.assertEqual((result.failures, result.errors, result.skipped), ([], [], []))

    def test_no_hub_pointer_skips_rather_than_failing(self):
        """An unwired machine has no hub name to leak and must not go red for it."""
        result = self.run_probe("", ["fenced and merged by somehub)."])
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertEqual(len(result.skipped), 1)

    def test_a_generic_hub_name_is_not_probed(self):
        """Somebody whose hub is called "hub" cannot be searched for, and needs no guard."""
        result = self.run_probe("hub:/somewhere", ["the hub does the merging"])
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual((result.failures, result.errors), ([], []))

    def test_the_match_is_on_word_boundaries_and_ignores_case(self):
        caught = self.run_probe("somehub:/x", ["merged by SOMEHUB at dawn"])
        self.assertEqual(len(caught.failures), 1, "case must not matter")
        clear = self.run_probe("somehub:/x", ["merged by somehubbub at dawn"])
        self.assertEqual(clear.failures, [], "a longer word that contains it is not a match")


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
