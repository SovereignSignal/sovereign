import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.state import Manifest, State, atomic_write, sha256_bytes, write_if_changed  # noqa: E402


class Writes(unittest.TestCase):
    def test_atomic_write_creates_parents_and_leaves_no_part_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a" / "b" / "x.md"
            atomic_write(p, b"hello")
            self.assertEqual(p.read_bytes(), b"hello")
            self.assertEqual(sorted(os.listdir(p.parent)), ["x.md"])

    def test_write_if_changed_skips_identical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.md"
            self.assertTrue(write_if_changed(p, b"one"))
            before = p.stat().st_mtime_ns
            time.sleep(0.01)
            self.assertFalse(write_if_changed(p, b"one"))
            self.assertEqual(p.stat().st_mtime_ns, before)
            self.assertTrue(write_if_changed(p, b"two"))
            self.assertEqual(p.read_bytes(), b"two")

    def test_sha256(self):
        self.assertEqual(sha256_bytes(b"abc")[:12], "ba7816bf8f01")


class ManifestRoundTrip(unittest.TestCase):
    def test_save_load_and_rows_of(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = Manifest(Path(tmp) / "state" / "manifest.json")
            m.load()
            self.assertEqual(m.items, {})
            m.items = {
                "a" * 32: {"id": "a" * 32, "kind": "database", "title": "DB", "path": "P/DB a_all.csv", "header": ["Name"]},
                "b" * 32: {"id": "b" * 32, "kind": "row", "title": "zeta", "db_id": "a" * 32, "cells": ["zeta"]},
                "c" * 32: {"id": "c" * 32, "kind": "row", "title": "Alpha", "db_id": "a" * 32, "cells": ["Alpha"]},
                "d" * 32: {"id": "d" * 32, "kind": "page", "title": "Other"},
            }
            m.save()
            m2 = Manifest(m.path)
            m2.load()
            self.assertEqual(m2.items, m.items)
            self.assertEqual([r["title"] for r in m2.rows_of("a" * 32)], ["Alpha", "zeta"])


class StateFiles(unittest.TestCase):
    def test_status_cursor_and_full_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = State(Path(tmp))
            self.assertIsNone(s.read_cursor())
            self.assertTrue(s.full_due())
            s.write_cursor("2026-09-01T00:00:00.000Z")
            self.assertEqual(s.read_cursor(), "2026-09-01T00:00:00.000Z")
            s.write_last_full()
            self.assertFalse(s.full_due())
            old = time.time() - 7 * 86400
            os.utime(s.state / "last-full", (old, old))
            self.assertTrue(s.full_due(days=6))
            s.ok("wrote 3")
            self.assertTrue((Path(tmp) / "last-status").read_text().startswith("OK "))
            self.assertTrue((Path(tmp) / "last-status").read_text().rstrip().endswith("wrote 3"))
            success = (Path(tmp) / "last-success").read_text().strip()
            self.assertRegex(success, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
            s.fail("boom")
            self.assertTrue((Path(tmp) / "last-status").read_text().startswith("FAILED "))
            self.assertEqual((Path(tmp) / "last-success").read_text().strip(), success)
            s.log("a line")
            self.assertIn("a line", (Path(tmp) / "mirror.log").read_text())


if __name__ == "__main__":
    unittest.main()
