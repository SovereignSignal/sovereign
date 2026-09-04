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


if __name__ == "__main__":
    unittest.main()
