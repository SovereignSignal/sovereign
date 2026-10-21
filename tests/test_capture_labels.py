"""sov-capture writes a title or origin YAML reads back as the same string, whatever its characters.

Headings and filenames arrive unvetted. "[Work] notes" parsed as a list, "C# notes" lost
everything after the #, "2026" became a number. Plain values keep their exact bytes.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "bin/sov-capture"

try:
    import yaml
except ImportError:  # PyYAML is a test-only dependency (docs/release-checks.md)
    yaml = None


class Labels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "v"
        (self.vault / "knowledge").mkdir(parents=True)
        (self.vault / "raw/workspaces/test").mkdir(parents=True)
        self.n = 0

    def capture(self, title, origin=""):
        self.n += 1
        slug = "c%d" % self.n
        args = [sys.executable, str(CAPTURE), slug, "--lane", "test", "--note", "A body long enough to keep.",
                "--title", title] + (["--origin", origin] if origin else [])
        r = subprocess.run(args, capture_output=True, text=True, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "HOME": self.tmp.name, "BRAIN_ROOT": str(self.vault),
                                "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.vault / "raw/workspaces/test" / (slug + ".md")).read_text()
        return text.split("---\n")[1]

    def test_plain_values_keep_their_bytes(self):
        fm = self.capture("Garden planner project", "https://example.com/a/b")
        self.assertIn("\ntitle: Garden planner project\n", fm)
        self.assertIn("\norigin: https://example.com/a/b\n", fm)

    @unittest.skipIf(yaml is None, "PyYAML is not installed")
    def test_awkward_values_read_back_as_the_same_string(self):
        for title in ("[Work] Garden notes", "C# notes", "2026", "yes", "Plans: next quarter", "*starred",
                      "'quoted", '"double"', "{braces}", "- dash first", "& anchor", "!tagged", "% done",
                      "@handle", "`code`", "ends with colon:", "2026-10-20 review", "Café ☕ plans", "| pipe", "> fold"):
            data = yaml.safe_load(self.capture(title, origin="notes/" + title + ".md"))
            self.assertEqual(data["title"], title, title)
            self.assertEqual(data["origin"], "notes/" + title + ".md", title)


if __name__ == "__main__":
    unittest.main()
