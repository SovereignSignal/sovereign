"""Blocks and properties to the markdown and CSV Notion's export writes. Pure.

The renderer never fetches. Attachments it wants are appended to the caller's list
as (url, lane_relative_destination) and the caller decides whether to download.
"""
import csv
import io
import posixpath
import urllib.parse
from typing import Dict, List, Optional, Tuple

from .config import norm_id
from .model import plain_text
from .paths import folder_for, sanitize

INDENT = "    "
LINK_SAFE = "/()!*'~,-._"


class Links:
    """Resolve ids to relative links from the page being rendered."""

    def __init__(self, paths: Dict[str, str], titles: Optional[Dict[str, str]] = None):
        self.paths = paths
        self.titles = titles or {}

    def href(self, from_path: str, target_id: str) -> Optional[str]:
        target = self.paths.get(norm_id(target_id))
        return rel_link(from_path, target) if target else None

    def title(self, target_id: str) -> str:
        return self.titles.get(norm_id(target_id), "")


def rel_link(from_path: str, to_path: str) -> str:
    rel = posixpath.relpath(to_path, posixpath.dirname(from_path) or ".")
    return urllib.parse.quote(rel, safe=LINK_SAFE)


def render_rich_text(rich, links: Links, from_path: str = "") -> str:
    out: List[str] = []
    for seg in rich or []:
        text = str(seg.get("plain_text", ""))
        ann = seg.get("annotations") or {}
        if seg.get("type") == "mention":
            mention = seg.get("mention") or {}
            if mention.get("type") == "page":
                href = links.href(from_path, (mention.get("page") or {}).get("id", ""))
                if href:
                    out.append("[%s](%s)" % (text, href))
                    continue
            elif mention.get("type") == "database":
                href = links.href(from_path, (mention.get("database") or {}).get("id", ""))
                if href:
                    out.append("[%s](%s)" % (text, href))
                    continue
        elif seg.get("type") == "equation":
            out.append("$%s$" % text)
            continue
        if ann.get("code"):
            text = "`%s`" % text
        if ann.get("bold"):
            text = "**%s**" % text
        if ann.get("italic"):
            text = "*%s*" % text
        if ann.get("strikethrough"):
            text = "~~%s~~" % text
        href = seg.get("href")
        if href and not (seg.get("type") == "mention"):
            text = "[%s](%s)" % (text, href)
        out.append(text)
    return "".join(out)


def _file_target(block: dict, body: dict, page_path: str, attachments: list) -> Tuple[str, str]:
    """Return (label, href) for an image/file/pdf/video/audio block, queueing a download for
    Notion-hosted files. External files link straight to their URL."""
    kind = body.get("type")
    if kind == "external":
        url = (body.get("external") or {}).get("url", "")
        return body.get("name") or posixpath.basename(urllib.parse.urlsplit(url).path) or url, url
    url = (body.get("file") or body.get("file_upload") or {}).get("url", "")
    raw_name = body.get("name") or posixpath.basename(urllib.parse.urlsplit(url).path) or block.get("id", "file")
    name = urllib.parse.unquote(raw_name)
    name = sanitize(name)
    if not name or name == "." or name == "..":
        name = block.get("id", "file")
    dest = posixpath.join(folder_for(page_path), name.replace(" ", "_"))
    if url:
        attachments.append((url, dest))
    return name, rel_link(page_path, dest)


def _caption(body: dict, links: Links, page_path: str) -> str:
    return render_rich_text(body.get("caption"), links, page_path)


def render_blocks(blocks: List[dict], links: Links, attachments: list, page_path: str, depth: int = 0) -> str:
    """Render a block list. Consecutive list items stay tight; other blocks get a blank
    line after them; children indent four spaces per level."""
    pieces: List[str] = []
    number = 0
    prev_list_kind = None

    def add(text: str, list_kind: Optional[str]) -> None:
        nonlocal prev_list_kind
        if pieces and prev_list_kind and list_kind != prev_list_kind:
            pieces.append("\n")
        pieces.append(text)
        prev_list_kind = list_kind

    def kids(block: dict) -> str:
        children = block.get("children") or []
        if not children:
            return ""
        inner = render_blocks(children, links, attachments, page_path, depth + 1)
        return "".join(INDENT + line + "\n" if line else "\n" for line in inner.rstrip("\n").split("\n"))

    for block in blocks:
        kind = block.get("type", "")
        body = block.get(kind) or {}
        text = render_rich_text(body.get("rich_text"), links, page_path)
        if kind != "numbered_list_item":
            number = 0
        if kind == "paragraph":
            add((text + "\n\n") if text else "\n", None)
        elif kind in ("heading_1", "heading_2", "heading_3"):
            add("%s %s\n\n" % ("#" * int(kind[-1]), text), None)
        elif kind == "bulleted_list_item":
            add("- %s\n%s" % (text, kids(block)), "bulleted_list_item")
        elif kind == "toggle":
            add("- %s\n%s" % (text, kids(block)), "toggle")
        elif kind == "numbered_list_item":
            number += 1
            add("%d. %s\n%s" % (number, text, kids(block)), "numbered_list_item")
        elif kind == "to_do":
            add("- [%s] %s\n%s" % ("x" if body.get("checked") else " ", text, kids(block)), "to_do")
        elif kind == "quote":
            add("> %s\n\n%s" % (text, kids(block)), None)
        elif kind == "callout":
            icon = body.get("icon") or {}
            emoji = icon.get("emoji", "") if icon.get("type") == "emoji" else ""
            head = ("%s %s" % (emoji, text)).strip()
            add("<aside>\n%s\n%s</aside>\n\n" % (head, kids(block)), None)
        elif kind == "code":
            add("```%s\n%s\n```\n\n" % (body.get("language", "") if body.get("language") != "plain text" else "", text), None)
        elif kind == "divider":
            add("---\n\n", None)
        elif kind == "equation":
            add("$$%s$$\n\n" % body.get("expression", ""), None)
        elif kind == "table":
            rows = [r for r in block.get("children") or [] if r.get("type") == "table_row"]
            lines = []
            for i, row in enumerate(rows):
                cells = [render_rich_text(c, links, page_path) for c in (row.get("table_row") or {}).get("cells", [])]
                lines.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    lines.append("| " + " | ".join("---" for _ in cells) + " |")
            add("\n".join(lines) + "\n\n" if lines else "", None)
        elif kind in ("image", "file", "pdf", "video", "audio"):
            label, href = _file_target(block, body, page_path, attachments)
            cap = _caption(body, links, page_path)
            line = ("![%s](%s)" if kind == "image" else "[%s](%s)") % (label, href)
            add(line + ("\n\n" + cap + "\n\n" if cap else "\n\n"), None)
        elif kind in ("bookmark", "embed", "link_preview"):
            url = body.get("url", "")
            cap = _caption(body, links, page_path)
            add("[%s](%s)\n\n" % (cap or url, url), None)
        elif kind == "child_page":
            href = links.href(page_path, block.get("id", ""))
            title = (body.get("title") or links.title(block.get("id", "")) or "Untitled")
            add(("[%s](%s)\n\n" % (title, href)) if href else ("%s\n\n" % title), None)
        elif kind == "child_database":
            href = links.href(page_path, block.get("id", ""))
            title = (body.get("title") or links.title(block.get("id", "")) or "Untitled")
            add(("[%s](%s)\n\n" % (title, href)) if href else ("%s\n\n" % title), None)
        elif kind == "link_to_page":
            target = body.get("page_id") or body.get("database_id") or body.get("data_source_id") or ""
            href = links.href(page_path, target)
            title = links.title(target) or "Untitled"
            add(("[%s](%s)\n\n" % (title, href)) if href else ("%s\n\n" % title), None)
        elif kind in ("column_list", "column", "synced_block"):
            add(render_blocks(block.get("children") or [], links, attachments, page_path, depth), None)
        elif kind in ("table_of_contents", "breadcrumb", "table_row"):
            continue
        else:
            add("<!-- unsupported: %s -->\n\n" % kind, None)
    out = "".join(pieces)
    return out.rstrip("\n") + "\n" if out.strip() else ""
