"""Part 1 of the law is the copyable standard. The template's copy and the vault's must
say the same thing, and sov check says so when they drift."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import law  # noqa: E402


class Law(unittest.TestCase):
    def test_identical_part_one_has_no_drift(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            a = Path(tmp) / "a.md"; b = Path(tmp) / "b.md"
            a.write_text("# Part 1 — the standard\n\nrule one\n\n# Part 2 — mine\n\nsecret\n")
            b.write_text("intro\n# Part 1 — the standard\nrule one\n# Part 2 — other\ndifferent\n")
            self.assertEqual(law.drift(a, b), [])

    def test_a_changed_rule_is_named(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            a = Path(tmp) / "a.md"; b = Path(tmp) / "b.md"
            a.write_text("# Part 1 — the standard\nrule one\n# Part 2\n")
            b.write_text("# Part 1 — the standard\nrule two\n# Part 2\n")
            d = law.drift(a, b)
            self.assertTrue(any("rule one" in x for x in d) and any("rule two" in x for x in d))

    def test_the_template_law_has_a_part_one(self):
        self.assertTrue(law.part1((ROOT / "CLAUDE.md").read_text()))


if __name__ == "__main__":
    unittest.main()
