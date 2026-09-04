import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.paths import MAX_STEM, file_name, folder_for, folder_name, resolve_paths, sanitize, short_id, stem  # noqa: E402


def hid(n):
    return "%032x" % n


def item(n, kind, title, parent_kind, parent_id, **extra):
    d = {"id": hid(n), "kind": kind, "title": title, "parent_kind": parent_kind, "parent_id": parent_id,
         "last_edited": "2026-09-01T00:00:00.000Z", "in_trash": False, "ds_id": "", "db_id": "", "inline": False}
    d.update(extra)
    return d


class Names(unittest.TestCase):
    def test_sanitize_drops_colon_and_collapses_spaces(self):
        self.assertEqual(sanitize("Company Brain: Archive"), "Company Brain Archive")
        self.assertEqual(sanitize("Hygiene 2026-08-24 19:00"), "Hygiene 2026-08-24 19 00")
        self.assertEqual(sanitize("a/b\\c?d*e\"f<g>h|i"), "a b c d e f g h i")
        self.assertEqual(sanitize("  padded  "), "padded")

    def test_short_id_is_first_four_and_last_four(self):
        self.assertEqual(short_id("1b0000c0d5908025871fd52d5773e2ae"), "1b00-e2ae")

    def test_stem_untitled_and_truncation(self):
        self.assertEqual(stem("", "1b0000c0d5908025871fd52d5773e2ae"), "Untitled 1b00-e2ae")
        long = "Company Brain: Machine Sync Plan (Producer Read/Write Wire)"
        self.assertEqual(stem(long, hid(1)), "Company Brain Machine Sync Plan (Producer Read Wri")
        self.assertEqual(len(stem(long, hid(1))), MAX_STEM)
        self.assertEqual(stem("x" * 49 + " y", hid(1)), "x" * 49)

    def test_file_and_folder_names(self):
        page = item(1, "page", "Home", "workspace", "")
        db = item(2, "database", "LW Songs", "page", hid(1))
        self.assertEqual(file_name(page), "Home %s.md" % hid(1))
        self.assertEqual(file_name(db), "LW Songs %s_all.csv" % hid(2))
        self.assertEqual(folder_name(db), "LW Songs")
        self.assertEqual(folder_for("Private & Shared/Home %s.md" % hid(1)), "Private & Shared/Home")


class Resolve(unittest.TestCase):
    def tree(self):
        items = {}
        for it in (
            item(1, "page", "Root", "workspace", ""),
            item(2, "page", "Music", "page", hid(1)),
            item(3, "database", "LW Songs", "page", hid(2), ds_id=hid(30), db_id=hid(3)),
            item(4, "row", "Alive", "database", hid(3), ds_id=hid(30), db_id=hid(3)),
            item(5, "page", "Lyrics", "page", hid(4)),
            item(6, "page", "Team HQ", "workspace", ""),
        ):
            items[it["id"]] = it
        return items

    def test_paths_follow_the_export_layout(self):
        paths, orphans = resolve_paths(self.tree(), "Private & Shared", {hid(6): "Teamspace"})
        self.assertEqual(orphans, [])
        self.assertEqual(paths[hid(1)], "Private & Shared/Root %s.md" % hid(1))
        self.assertEqual(paths[hid(2)], "Private & Shared/Root/Music %s.md" % hid(2))
        self.assertEqual(paths[hid(3)], "Private & Shared/Root/Music/LW Songs %s_all.csv" % hid(3))
        self.assertEqual(paths[hid(4)], "Private & Shared/Root/Music/LW Songs/Alive %s.md" % hid(4))
        self.assertEqual(paths[hid(5)], "Private & Shared/Root/Music/LW Songs/Alive/Lyrics %s.md" % hid(5))
        self.assertEqual(paths[hid(6)], "Teamspace/Team HQ %s.md" % hid(6))

    def test_orphan_lands_under_default_root_and_is_reported(self):
        items = self.tree()
        items[hid(7)] = item(7, "page", "Lost", "page", hid(99))
        paths, orphans = resolve_paths(items, "Private & Shared", {})
        self.assertEqual(orphans, [hid(7)])
        self.assertEqual(paths[hid(7)], "Private & Shared/Lost %s.md" % hid(7))

    def test_block_parent_resolves_through_callback(self):
        items = self.tree()
        items[hid(8)] = item(8, "page", "In a column", "block", "blk1")
        paths, orphans = resolve_paths(items, "Private & Shared", {}, resolve_block=lambda b: hid(2))
        self.assertEqual(orphans, [])
        self.assertEqual(paths[hid(8)], "Private & Shared/Root/Music/In a column %s.md" % hid(8))

    def test_cycle_is_an_orphan_not_a_crash(self):
        items = {hid(1): item(1, "page", "A", "page", hid(2)), hid(2): item(2, "page", "B", "page", hid(1))}
        paths, orphans = resolve_paths(items, "Private & Shared", {})
        self.assertEqual(sorted(orphans), [hid(1), hid(2)])


if __name__ == "__main__":
    unittest.main()
