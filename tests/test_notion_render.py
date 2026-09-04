import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from notion_mirror.render import Links, rel_link, render_blocks, render_rich_text  # noqa: E402


def rt(text, **ann):
    a = {"bold": False, "italic": False, "strikethrough": False, "underline": False, "code": False}
    a.update(ann)
    return {"type": "text", "plain_text": text, "text": {"content": text, "link": None}, "annotations": a, "href": None}


def blk(kind, text="", children=None, **extra):
    body = {"rich_text": [rt(text)] if text else []}
    body.update(extra)
    b = {"object": "block", "id": "b-" + kind, "type": kind, "has_children": bool(children), kind: body}
    if children:
        b["children"] = children
    return b


PAGE = "Private & Shared/Home 00000000000000000000000000000001.md"
LINKS = Links(
    paths={"00000000000000000000000000000002": "Private & Shared/Home/Child (v2) 00000000000000000000000000000002.md",
           "00000000000000000000000000000003": "Private & Shared/Home/LW Songs 00000000000000000000000000000003_all.csv"},
    titles={"00000000000000000000000000000002": "Child: v2", "00000000000000000000000000000003": "LW Songs"},
)


class RichText(unittest.TestCase):
    def test_annotations(self):
        self.assertEqual(render_rich_text([rt("a", bold=True), rt("b", italic=True), rt("c", code=True), rt("d", strikethrough=True)], LINKS), "**a***b*`c`~~d~~")

    def test_link_and_page_mention(self):
        seg = rt("site")
        seg["href"] = "https://example.org"
        mention = {"type": "mention", "plain_text": "Child: v2", "mention": {"type": "page", "page": {"id": "00000000-0000-0000-0000-000000000002"}}, "annotations": {}}
        out = render_rich_text([seg, mention], LINKS, from_path=PAGE)
        self.assertEqual(out, "[site](https://example.org)[Child: v2](Home/Child%20(v2)%2000000000000000000000000000000002.md)")


class RelLink(unittest.TestCase):
    def test_relative_and_percent_encoded(self):
        self.assertEqual(rel_link(PAGE, "Private & Shared/Home/Child (v2) 2.md"), "Home/Child%20(v2)%202.md")
        self.assertEqual(rel_link("A/B/c 1.md", "A/D 2.md"), "../D%202.md")


class Blocks(unittest.TestCase):
    def test_headings_paragraph_lists_and_todos(self):
        blocks = [blk("heading_1", "Title"), blk("paragraph", "Body text."), blk("bulleted_list_item", "one"),
                  blk("bulleted_list_item", "two", children=[blk("bulleted_list_item", "nested")]),
                  blk("numbered_list_item", "first"), blk("numbered_list_item", "second"),
                  blk("to_do", "done", checked=True), blk("to_do", "open", checked=False)]
        out = render_blocks(blocks, LINKS, [], PAGE)
        self.assertEqual(out, "# Title\n\nBody text.\n\n- one\n- two\n    - nested\n\n1. first\n2. second\n\n- [x] done\n- [ ] open\n")

    def test_quote_callout_code_divider_toggle(self):
        blocks = [blk("quote", "wise"), blk("callout", "note", icon={"type": "emoji", "emoji": "💡"}),
                  blk("code", "print(1)", language="python"), blk("divider"), blk("toggle", "more", children=[blk("paragraph", "inside")])]
        out = render_blocks(blocks, LINKS, [], PAGE)
        self.assertEqual(out, "> wise\n\n<aside>\n💡 note\n</aside>\n\n```python\nprint(1)\n```\n\n---\n\n- more\n    inside\n")

    def test_table(self):
        row = lambda *cells: {"object": "block", "type": "table_row", "table_row": {"cells": [[rt(c)] for c in cells]}}
        table = blk("table", has_column_header=True, table_width=2, children=[row("h1", "h2"), row("a", "b")])
        out = render_blocks([table], LINKS, [], PAGE)
        self.assertEqual(out, "| h1 | h2 |\n| --- | --- |\n| a | b |\n")

    def test_child_page_and_database_links(self):
        blocks = [{"object": "block", "id": "00000000-0000-0000-0000-000000000002", "type": "child_page", "child_page": {"title": "Child: v2"}},
                  {"object": "block", "id": "00000000-0000-0000-0000-000000000003", "type": "child_database", "child_database": {"title": "LW Songs"}}]
        out = render_blocks(blocks, LINKS, [], PAGE)
        self.assertEqual(out, "[Child: v2](Home/Child%20(v2)%2000000000000000000000000000000002.md)\n\n[LW Songs](Home/LW%20Songs%2000000000000000000000000000000003_all.csv)\n")

    def test_image_collects_attachment_and_links_relative(self):
        img = {"object": "block", "id": "i1", "type": "image", "image": {"type": "file", "file": {"url": "https://s3/x/My%20Shot.png?sig=1"}, "caption": []}}
        att = []
        out = render_blocks([img], LINKS, att, PAGE)
        self.assertEqual(out, "![My Shot.png](Home/My_Shot.png)\n")
        self.assertEqual(att, [("https://s3/x/My%20Shot.png?sig=1", "Private & Shared/Home/My_Shot.png")])

    def test_external_file_links_to_url_and_unknown_is_marked(self):
        ext = {"object": "block", "id": "f1", "type": "file", "file": {"type": "external", "external": {"url": "https://x/y.pdf"}, "name": "y.pdf", "caption": []}}
        odd = {"object": "block", "id": "u1", "type": "flux_capacitor", "flux_capacitor": {}}
        att = []
        out = render_blocks([ext, odd], LINKS, att, PAGE)
        self.assertEqual(out, "[y.pdf](https://x/y.pdf)\n\n<!-- unsupported: flux_capacitor -->\n")
        self.assertEqual(att, [])

    def test_attachment_name_cannot_escape_the_page_folder(self):
        import posixpath
        evil = {"object": "block", "id": "e1", "type": "file", "file": {"type": "file", "file": {"url": "https://s3/x/y?sig=1"}, "name": "../../etc/passwd", "caption": []}}
        dot = {"object": "block", "id": "e2", "type": "file", "file": {"type": "file", "file": {"url": "https://s3/x/z?sig=1"}, "name": "..", "caption": []}}
        att = []
        render_blocks([evil, dot], LINKS, att, PAGE)
        self.assertEqual(len(att), 2)
        for url, dest in att:
            self.assertEqual(posixpath.dirname(dest), "Private & Shared/Home")
            self.assertNotIn("..", posixpath.basename(dest).split("_")[0] if posixpath.basename(dest) in (".", "..") else "")
        self.assertEqual(att[0][1], "Private & Shared/Home/.._.._etc_passwd")
        self.assertEqual(att[1][1], "Private & Shared/Home/e2")
from notion_mirror.render import property_order, property_text, render_csv, render_page, row_cells  # noqa: E402

SCHEMA = {"Song": {"type": "title"}, "Lyrics": {"type": "rich_text"}, "Status": {"type": "select"}, "Tab": {"type": "url"}, "Type": {"type": "multi_select"}}


def row(title, status=None, types=(), tab=None, when=None):
    props = {
        "Song": {"type": "title", "title": [rt(title)]},
        "Lyrics": {"type": "rich_text", "rich_text": []},
        "Status": {"type": "select", "select": {"name": status} if status else None},
        "Tab": {"type": "url", "url": tab},
        "Type": {"type": "multi_select", "multi_select": [{"name": t} for t in types]},
    }
    if when:
        props["When"] = {"type": "date", "date": {"start": when, "end": None}}
    return {"object": "page", "id": "r-" + title, "created_time": "2026-01-01T00:00:00.000Z", "properties": props}


class Properties(unittest.TestCase):
    def test_property_text_by_type(self):
        self.assertEqual(property_text({"type": "select", "select": {"name": "IP"}}, LINKS), "IP")
        self.assertEqual(property_text({"type": "select", "select": None}, LINKS), "")
        self.assertEqual(property_text({"type": "multi_select", "multi_select": [{"name": "Rock"}, {"name": "Folk"}]}, LINKS), "Rock, Folk")
        self.assertEqual(property_text({"type": "date", "date": {"start": "2026-08-01", "end": "2026-08-03"}}, LINKS), "2026-08-01 to 2026-08-03")
        self.assertEqual(property_text({"type": "checkbox", "checkbox": True}, LINKS), "Yes")
        self.assertEqual(property_text({"type": "number", "number": 3.0}, LINKS), "3")
        self.assertEqual(property_text({"type": "number", "number": 2.5}, LINKS), "2.5")
        self.assertEqual(property_text({"type": "people", "people": [{"name": "Owner"}]}, LINKS), "Owner")
        self.assertEqual(property_text({"type": "relation", "relation": [{"id": "00000000-0000-0000-0000-000000000002"}]}, LINKS), "Child: v2")
        self.assertEqual(property_text({"type": "formula", "formula": {"type": "string", "string": "x"}}, LINKS), "x")
        self.assertEqual(property_text({"type": "rollup", "rollup": {"type": "number", "number": 4}}, LINKS), "4")
        self.assertEqual(property_text({"type": "status", "status": {"name": "Done"}}, LINKS), "Done")
        self.assertEqual(property_text({"type": "unique_id", "unique_id": {"prefix": "T", "number": 7}}, LINKS), "T-7")
        self.assertEqual(property_text({"type": "files", "files": [{"name": "a.pdf"}]}, LINKS), "a.pdf")

    def test_property_order_puts_title_first(self):
        self.assertEqual(property_order(SCHEMA), ["Song", "Lyrics", "Status", "Tab", "Type"])
        self.assertEqual(property_order({"B": {"type": "url"}, "A": {"type": "title"}}), ["A", "B"])

    def test_row_page_lists_non_empty_properties_then_body(self):
        item = {"id": "1" * 32, "kind": "row", "title": "Alive"}
        page_obj = row("Alive", status="IP", types=("Rock",))
        out = render_page(item, page_obj, [blk("paragraph", "body")], LINKS, [], PAGE, schema_props=SCHEMA)
        self.assertEqual(out, "# Alive\n\nStatus: IP\nType: Rock\n\nbody\n")

    def test_plain_page_is_title_then_body(self):
        item = {"id": "1" * 32, "kind": "page", "title": "Home"}
        out = render_page(item, {"properties": {}}, [blk("paragraph", "hello")], LINKS, [], PAGE)
        self.assertEqual(out, "# Home\n\nhello\n")
        self.assertEqual(render_page(item, {"properties": {}}, [], LINKS, [], PAGE), "# Home\n")

    def test_csv_has_bom_header_in_schema_order_and_quoted_cells(self):
        out = render_csv(SCHEMA, [row("Alive", status="IP", types=("Rock",)), row("Atlantic, City", tab="https://t")], LINKS)
        self.assertTrue(out.startswith("﻿"))
        lines = out.lstrip("﻿").splitlines()
        self.assertEqual(lines[0], "Song,Lyrics,Status,Tab,Type")
        self.assertEqual(lines[1], "Alive,,IP,,Rock")
        self.assertEqual(lines[2], '"Atlantic, City",,,https://t,')

    def test_row_cells_align_to_schema_and_ignore_extra_props(self):
        cells = row_cells(SCHEMA, row("Alive", status="IP", when="2026-01-02"), LINKS)
        self.assertEqual(cells, ["Alive", "", "IP", "", ""])

if __name__ == "__main__":
    unittest.main()
