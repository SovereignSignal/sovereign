"""Flatten Notion API objects into the one shape the rest of the mirror reasons about.

An item is a plain dict so it round-trips through the JSON manifest unchanged:
  id           32 hex, no dashes. For a database this is the DATABASE id (the export
               names the CSV by it); ds_id holds the data source that carries the rows.
  kind         page | row | database
  title        plain text, may be empty (the path layer decides what Untitled looks like)
  parent_kind  workspace | page | database | block | unknown
  parent_id    32 hex or empty; for rows this is the database id
  last_edited  ISO timestamp as Notion sends it
  in_trash     bool
  ds_id, db_id 32 hex or empty
  inline       bool, databases only
"""
import re
from datetime import datetime
from typing import Optional, Tuple

from .config import norm_id

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})")


def date_mention_text(mention: dict, plain_text_: str) -> str:
    """The export's rendering of a date mention: `@` + full month name + day (no
    leading zero) + `, ` + year, and a time when the mention's start carries one
    (`@June 18, 2026` or `@August 13, 2026 3:00 PM`). The mention's own plain_text
    is ignored when the start parses; `end` is ignored throughout. When the start
    does not parse, fall back to `@` + plain_text, prefixing only when not already
    present."""
    start = str((mention.get("date") or {}).get("start", ""))
    m = _DATE_ONLY.match(start)
    if m:
        dt = _safe_date(start, "%Y-%m-%d")
        if dt:
            return "@%s %d, %d" % (dt.strftime("%B"), dt.day, dt.year)
    else:
        m = _DATE_TIME.match(start)
        if m:
            date_part, hour_s, minute_s = m.groups()
            dt = _safe_date(date_part, "%Y-%m-%d")
            if dt:
                hour, minute = int(hour_s), int(minute_s)
                ampm = "AM" if hour < 12 else "PM"
                hour12 = hour % 12 or 12
                return "@%s %d, %d %d:%02d %s" % (dt.strftime("%B"), dt.day, dt.year, hour12, minute, ampm)
    text = plain_text_ or ""
    return text if text.startswith("@") else "@" + text


def _safe_date(value: str, fmt: str):
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def plain_text(rich) -> str:
    out = []
    for seg in rich or []:
        mention = seg.get("mention") or {}
        text = str(seg.get("plain_text", ""))
        if seg.get("type") == "mention":
            if mention.get("type") == "date":
                out.append(date_mention_text(mention, text))
            else:
                out.append(text if not text or text.startswith("@") else "@" + text)
        else:
            out.append(text)
    return "".join(out)


def title_of(obj: dict) -> str:
    if obj.get("object") in ("data_source", "database"):
        return plain_text(obj.get("title"))
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            return plain_text(prop.get("title"))
    return ""


def parent_of(parent: Optional[dict]) -> Tuple[str, str]:
    kind = (parent or {}).get("type")
    if kind == "workspace":
        return "workspace", ""
    if kind == "page_id":
        return "page", norm_id(parent.get("page_id"))
    if kind == "data_source_id":
        return "database", norm_id(parent.get("database_id"))
    if kind == "database_id":
        return "database", norm_id(parent.get("database_id"))
    if kind == "block_id":
        return "block", norm_id(parent.get("block_id"))
    return "unknown", ""


def item_from(obj: dict) -> dict:
    if obj.get("object") == "data_source":
        db_id = norm_id((obj.get("parent") or {}).get("database_id"))
        parent_kind, parent_id = parent_of(obj.get("database_parent"))
        return {
            "id": db_id or norm_id(obj.get("id")),
            "kind": "database",
            "title": title_of(obj),
            "parent_kind": parent_kind,
            "parent_id": parent_id,
            "last_edited": obj.get("last_edited_time", ""),
            "in_trash": bool(obj.get("in_trash")),
            "ds_id": norm_id(obj.get("id")),
            "db_id": db_id,
            "inline": bool(obj.get("is_inline")),
        }
    parent = obj.get("parent") or {}
    parent_kind, parent_id = parent_of(parent)
    is_row = parent.get("type") == "data_source_id"
    return {
        "id": norm_id(obj.get("id")),
        "kind": "row" if is_row else "page",
        "title": title_of(obj),
        "parent_kind": parent_kind,
        "parent_id": parent_id,
        "last_edited": obj.get("last_edited_time", ""),
        "in_trash": bool(obj.get("in_trash") or obj.get("archived")),
        "ds_id": norm_id(parent.get("data_source_id")) if is_row else "",
        "db_id": parent_id if is_row else "",
        "inline": False,
    }
