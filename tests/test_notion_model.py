import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.model import date_mention_text, item_from, parent_of, plain_text, title_of  # noqa: E402

PAGE = {
    "object": "page", "id": "3ce000c0-d590-81b6-bd08-c412ab652353", "last_edited_time": "2026-09-01T16:00:00.000Z",
    "in_trash": False, "parent": {"type": "page_id", "page_id": "361000c0-d590-80e6-b6a2-e877fe87be23"},
    "properties": {"title": {"type": "title", "title": [{"plain_text": "Health "}, {"plain_text": "Check"}]}},
}
ROW = {
    "object": "page", "id": "1b0000c0-d590-8014-9346-cb6f2e36a4e8", "last_edited_time": "2026-08-30T00:00:00.000Z",
    "parent": {"type": "data_source_id", "data_source_id": "1b0000c0-d590-80af-b628-000bf37a3e4d", "database_id": "1b0000c0-d590-8025-871f-d52d5773e2ae"},
    "properties": {"Song": {"type": "title", "title": [{"plain_text": "Alive"}]}, "Status": {"type": "select", "select": {"name": "IP"}}},
}
DATA_SOURCE = {
    "object": "data_source", "id": "1b0000c0-d590-80af-b628-000bf37a3e4d", "last_edited_time": "2026-08-30T00:00:00.000Z",
    "parent": {"type": "database_id", "database_id": "1b0000c0-d590-8025-871f-d52d5773e2ae"},
    "database_parent": {"type": "page_id", "page_id": "2c455aa0-1fef-4c9c-81c1-00810b22d1fa"},
    "is_inline": False, "in_trash": False, "title": [{"plain_text": "LW Songs"}],
}


class Model(unittest.TestCase):
    def test_plain_text_joins_segments(self):
        self.assertEqual(plain_text([{"plain_text": "a"}, {"plain_text": "b"}]), "ab")
        self.assertEqual(plain_text(None), "")

    def test_date_mention_text_date_only(self):
        mention = {"type": "date", "date": {"start": "2026-06-18"}}
        self.assertEqual(date_mention_text(mention, "2026-06-18"), "@June 18, 2026")

    def test_date_mention_text_with_time(self):
        mention = {"type": "date", "date": {"start": "2026-08-13T15:00:00.000-07:00"}}
        self.assertEqual(date_mention_text(mention, "August 13, 2026 3:00 PM"), "@August 13, 2026 3:00 PM")

    def test_date_mention_text_unparseable_falls_back_to_plain_text(self):
        mention = {"type": "date", "date": {"start": "not-a-date"}}
        self.assertEqual(date_mention_text(mention, "@Some Text"), "@Some Text")
        self.assertEqual(date_mention_text(mention, "Some Text"), "@Some Text")

    def test_plain_text_renders_date_mentions(self):
        seg = {"type": "mention", "plain_text": "2026-06-18",
               "mention": {"type": "date", "date": {"start": "2026-06-18"}}}
        self.assertEqual(plain_text([seg]), "@June 18, 2026")

    def test_plain_text_prefixes_a_page_mention_in_a_title(self):
        title = [
            {"type": "mention", "plain_text": "Field Notes",
             "mention": {"type": "page", "page": {"id": "x"}}},
            {"type": "text", "plain_text": " ongoing"},
        ]
        self.assertEqual(plain_text(title), "@Field Notes ongoing")

    def test_plain_text_does_not_double_prefix_a_user_mention(self):
        seg = {"type": "mention", "plain_text": "@Anna", "mention": {"type": "user", "user": {"id": "u1"}}}
        self.assertEqual(plain_text([seg]), "@Anna")

    def test_plain_text_prefixes_a_database_mention(self):
        seg = {"type": "mention", "plain_text": "LW Songs", "mention": {"type": "database", "database": {"id": "d1"}}}
        self.assertEqual(plain_text([seg]), "@LW Songs")

    def test_title_of_empty_mention_stays_empty(self):
        title = [{"type": "mention", "plain_text": "", "mention": {"type": "page", "page": {"id": "x"}}}]
        obj = {"object": "page", "properties": {"title": {"type": "title", "title": title}}}
        self.assertEqual(title_of(obj), "")

    def test_title_of_renders_date_mention_in_title(self):
        title = [
            {"type": "text", "plain_text": "Owner + Nick - "},
            {"type": "mention", "plain_text": "2026-06-18",
             "mention": {"type": "date", "date": {"start": "2026-06-18"}}},
            {"type": "text", "plain_text": " "},
        ]
        obj = {"object": "page", "properties": {"title": {"type": "title", "title": title}}}
        self.assertEqual(title_of(obj), "Owner + Nick - @June 18, 2026 ")

    def test_title_of_page_and_data_source(self):
        self.assertEqual(title_of(PAGE), "Health Check")
        self.assertEqual(title_of(DATA_SOURCE), "LW Songs")
        self.assertEqual(title_of({"object": "page", "properties": {}}), "")

    def test_parent_of(self):
        self.assertEqual(parent_of({"type": "workspace", "workspace": True}), ("workspace", ""))
        self.assertEqual(parent_of({"type": "page_id", "page_id": "AB-cd"}), ("page", "abcd"))
        self.assertEqual(parent_of({"type": "block_id", "block_id": "ff"}), ("block", "ff"))
        self.assertEqual(parent_of(None), ("unknown", ""))

    def test_page_item(self):
        it = item_from(PAGE)
        self.assertEqual(it["id"], "3ce000c0d59081b6bd08c412ab652353")
        self.assertEqual(it["kind"], "page")
        self.assertEqual(it["parent_kind"], "page")
        self.assertEqual(it["parent_id"], "361000c0d59080e6b6a2e877fe87be23")
        self.assertEqual(it["title"], "Health Check")
        self.assertFalse(it["in_trash"])

    def test_row_item_points_at_its_database(self):
        it = item_from(ROW)
        self.assertEqual(it["kind"], "row")
        self.assertEqual(it["parent_kind"], "database")
        self.assertEqual(it["parent_id"], "1b0000c0d5908025871fd52d5773e2ae")
        self.assertEqual(it["db_id"], "1b0000c0d5908025871fd52d5773e2ae")
        self.assertEqual(it["ds_id"], "1b0000c0d59080afb628000bf37a3e4d")
        self.assertEqual(it["title"], "Alive")

    def test_database_item_is_keyed_by_database_id(self):
        it = item_from(DATA_SOURCE)
        self.assertEqual(it["kind"], "database")
        self.assertEqual(it["id"], "1b0000c0d5908025871fd52d5773e2ae")
        self.assertEqual(it["ds_id"], "1b0000c0d59080afb628000bf37a3e4d")
        self.assertEqual(it["parent_kind"], "page")
        self.assertEqual(it["parent_id"], "2c455aa01fef4c9c81c100810b22d1fa")
        self.assertFalse(it["inline"])


if __name__ == "__main__":
    unittest.main()
