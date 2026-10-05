"""An archive the status cannot read is not an empty archive.

The configured archive renamed in Finder, on a drive that unmounted, or with its
knowledge folder unreadable: the card glob found nothing, raised nothing, and the
status reported a connected archive with 0 cards. Today said "Cards 0", Library said
"No cards yet." and nothing anywhere said the archive itself needed attention.
"""
import os
import shutil
import tempfile
import unittest

import tests.test_brain_status_jobs as base


class UnreadableArchive(unittest.TestCase):
    def needs(self, d):
        return [n for n in d["needs_you"] if n.get("kind") == "archive"]

    def test_a_readable_archive_reports_its_cards_and_no_need(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = base.Box(tmp); b.declare({}); b.record({})
            d = b.status()
        self.assertEqual(d["archive"]["total"], 1)
        self.assertEqual(self.needs(d), [])

    def test_a_missing_archive_folder_is_an_error_and_a_need(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = base.Box(tmp); b.declare({}); b.record({})
            shutil.move(str(b.vault), str(b.tmp / "renamed"))
            d = b.status()
        self.assertNotIn("total", d["archive"])
        self.assertEqual(d["archive"]["error"], "archive folder not found")
        need = self.needs(d)
        self.assertEqual(len(need), 1)
        self.assertIn(str(b.vault), need[0]["text"])
        for key in ("why", "action", "verify"):
            self.assertTrue(need[0].get(key), key)

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder whatever its mode")
    def test_an_unreadable_knowledge_folder_is_an_error_and_a_need(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = base.Box(tmp); b.declare({}); b.record({})
            k = b.vault / "knowledge"
            k.chmod(0)
            try:
                d = b.status()
            finally:
                k.chmod(0o755)
        self.assertIn("unreadable", d["archive"]["error"])
        self.assertEqual(len(self.needs(d)), 1)


if __name__ == "__main__":
    unittest.main()
