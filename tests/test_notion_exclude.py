import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.exclude import DEFAULT_EXCLUDE_TITLES, apply_excludes, marker_text, title_rule  # noqa: E402


def item(i, title, parent_kind="page", parent_id=""):
    return {"id": i, "kind": "page", "title": title, "parent_kind": parent_kind, "parent_id": parent_id}


class TitleRule(unittest.TestCase):
    def test_default_phrases_catch_the_usual_credential_pages(self):
        for title in ("Credentials Vault", "Keys and Creds", "Creds", "Key Management", "Secrets", "API Keys", "seed   PHRASE backup"):
            self.assertIsNotNone(title_rule(title, DEFAULT_EXCLUDE_TITLES), title)

    def test_whole_words_only(self):
        self.assertIsNone(title_rule("Credscore model", DEFAULT_EXCLUDE_TITLES))
        self.assertIsNone(title_rule("Passwordless login design", DEFAULT_EXCLUDE_TITLES))
        self.assertIsNone(title_rule("Secretariat notes", DEFAULT_EXCLUDE_TITLES))
        self.assertEqual(title_rule("Team secrets", DEFAULT_EXCLUDE_TITLES), "secrets")

    def test_empty_title_and_empty_rules(self):
        self.assertIsNone(title_rule("", DEFAULT_EXCLUDE_TITLES))
        self.assertIsNone(title_rule("Creds", []))

    def test_returns_the_phrase_that_matched(self):
        self.assertEqual(title_rule("Keys and Creds", ["key management", "creds"]), "creds")

    def test_marker_is_one_line_and_names_the_reason(self):
        text = marker_text('title matched "creds"')
        self.assertEqual(text.count("\n"), 1)
        self.assertIn('title matched "creds"', text)
        self.assertTrue(text.startswith("Excluded by the Notion mirror"))


class ApplyExcludes(unittest.TestCase):
    def tree(self):
        items = {
            "a" * 32: item("a" * 32, "Root", "workspace"),
            "b" * 32: item("b" * 32, "Keys and Creds", "page", "a" * 32),
            "c" * 32: item("c" * 32, "GitHub PAT", "page", "b" * 32),
            "d" * 32: item("d" * 32, "Old PAT", "page", "c" * 32),
            "e" * 32: item("e" * 32, "Music", "page", "a" * 32),
        }
        items["f" * 32] = {"id": "f" * 32, "kind": "database", "title": "Credentials Vault", "parent_kind": "page", "parent_id": "e" * 32}
        items["g" * 32] = {"id": "g" * 32, "kind": "row", "title": "xAI key", "parent_kind": "database", "parent_id": "f" * 32, "db_id": "f" * 32}
        return items

    def test_roots_marked_and_descendants_dropped(self):
        items = self.tree()
        dropped = apply_excludes(items, DEFAULT_EXCLUDE_TITLES, set())
        self.assertEqual(sorted(dropped), sorted(["c" * 32, "d" * 32, "g" * 32]))
        self.assertEqual(sorted(items), sorted(["a" * 32, "b" * 32, "e" * 32, "f" * 32]))
        self.assertEqual(items["b" * 32]["excluded"], 'title matched "creds"')
        self.assertEqual(items["f" * 32]["excluded"], 'title matched "credentials"')
        self.assertEqual(items["a" * 32]["excluded"], "")
        self.assertEqual(items["e" * 32]["excluded"], "")

    def test_ids_exclude_regardless_of_title(self):
        items = self.tree()
        dropped = apply_excludes(items, [], {"e" * 32})
        self.assertEqual(items["e" * 32]["excluded"], "id listed in NOTION_EXCLUDE_IDS")
        self.assertIn("f" * 32, dropped)
        self.assertIn("g" * 32, dropped)
        self.assertEqual(items["b" * 32]["excluded"], "")

    def test_nested_excluded_root_is_dropped_not_marked(self):
        items = self.tree()
        items["c" * 32]["title"] = "Secrets"
        dropped = apply_excludes(items, DEFAULT_EXCLUDE_TITLES, set())
        self.assertIn("c" * 32, dropped)

    def test_recomputed_each_run(self):
        items = self.tree()
        apply_excludes(items, DEFAULT_EXCLUDE_TITLES, set())
        again = self.tree()
        again["b" * 32]["excluded"] = 'title matched "creds"'  # as a manifest entry would carry it
        apply_excludes(again, [], set())
        self.assertEqual(again["b" * 32]["excluded"], "")
        self.assertIn("c" * 32, again)

    def test_block_parented_child_of_excluded_page_is_dropped(self):
        items = self.tree()
        items["h" * 32] = item("h" * 32, "Column child", "block", "1" * 32)
        dropped = apply_excludes(items, DEFAULT_EXCLUDE_TITLES, set(), resolve_block=lambda b: "b" * 32)
        self.assertIn("h" * 32, dropped)


if __name__ == "__main__":
    unittest.main()
