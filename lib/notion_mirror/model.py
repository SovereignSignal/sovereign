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
from typing import Optional, Tuple

from .config import norm_id


def plain_text(rich) -> str:
    return "".join(str(seg.get("plain_text", "")) for seg in (rich or []))


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
