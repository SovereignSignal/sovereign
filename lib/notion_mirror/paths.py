"""Where an item lives on disk, in the layout Notion's own export uses.

Rules, as observed on a real export (2026-09-04) and pinned by the oracle run:
  page file      <stem> <32hex>.md
  database file  <stem> <32hex>_all.csv
  child folder   <stem>            (no id; the export never puts ids on folders)
  untitled       Untitled <first4>-<last4>   (also a title that sanitizes to nothing, . or ..)
  excluded       <stem> <32hex>.md for a database too: a one-line marker, never a CSV
  stem           sanitized title cut at 50 characters, a trailing space at the cut kept
  top level      the folder roots.json maps the root to, else the default root

Pure functions. No disk, no network.
"""
import posixpath
import re
from typing import Callable, Dict, List, Optional, Tuple

MAX_STEM = 50
# Unsafe for a title-derived path stem: the path-reserved characters, plus a dot (the
# export renders a dot in a title as a space, observed on ston.fi, Google.org, Inc.).
_UNSAFE = str.maketrans({c: " " for c in ':/\\?*"<>|.'})
# Unsafe for an attachment file name: the path-reserved characters only, no dot, so an
# extension (or any other dot the file legitimately carries) survives sanitizing.
_FILE_UNSAFE = str.maketrans({c: " " for c in ':/\\?*"<>|'})
_SPACES = re.compile(r"\s+")


def sanitize(title: str) -> str:
    return _SPACES.sub(" ", (title or "").translate(_UNSAFE)).strip()


def sanitize_filename(name: str) -> str:
    """Like sanitize(), for a file name rather than a title: keeps dots so an
    attachment's extension (or any other dot it carries) is not lost."""
    return _SPACES.sub(" ", (name or "").translate(_FILE_UNSAFE)).strip()


def short_id(id32: str) -> str:
    return "%s-%s" % (id32[:4], id32[-4:])


def stem(title: str, id32: str) -> str:
    s = sanitize(title)
    if s in ("", ".", ".."):  # a dot-only name is a path component, never a title
        s = "Untitled %s" % short_id(id32)
    return s[:MAX_STEM]


def file_name(item: dict) -> str:
    s = stem(item.get("title", ""), item["id"])
    if item["kind"] == "database" and not item.get("excluded"):
        return "%s %s_all.csv" % (s, item["id"])
    return "%s %s.md" % (s, item["id"])


def folder_name(item: dict) -> str:
    return stem(item.get("title", ""), item["id"])


def folder_for(path: str) -> str:
    """The folder that holds a file's children: same directory, the stem without the id."""
    head, name = posixpath.split(path)
    base = name[: -len("_all.csv")] if name.endswith("_all.csv") else name[: -len(".md")]
    base = base.rsplit(" ", 1)[0] if " " in base else base
    return posixpath.join(head, base) if head else base


def resolve_paths(items: Dict[str, dict], default_root: str, required_roots: Dict[str, str],
                  resolve_block: Optional[Callable[[str], str]] = None) -> Tuple[Dict[str, str], List[str]]:
    """Map every item to its lane-relative file path. Orphans (parent chain unreachable
    or cyclic) go under the default root and are reported so the run can say so."""
    dir_cache: Dict[str, Optional[str]] = {}
    orphans: List[str] = []

    def directory(item_id: str, trail: frozenset) -> Optional[str]:
        if item_id in dir_cache:
            return dir_cache[item_id]
        it = items.get(item_id)
        if it is None:
            return None
        kind, pid = it["parent_kind"], it["parent_id"]
        if kind == "block" and resolve_block:
            pid = resolve_block(pid) or ""
            kind = "page"
        if kind == "workspace":
            out = required_roots.get(item_id, default_root)
        elif kind in ("page", "database") and pid and pid not in trail and pid in items:
            parent_dir = directory(pid, trail | {pid})
            out = None if parent_dir is None else posixpath.join(parent_dir, folder_name(items[pid]))
        else:
            out = None
        dir_cache[item_id] = out
        return out

    paths: Dict[str, str] = {}
    for item_id, it in items.items():
        d = directory(item_id, frozenset({item_id}))
        if d is None:
            orphans.append(item_id)
            d = default_root
        path = posixpath.join(d, file_name(it))
        if posixpath.normpath(path) != path or ".." in path.split("/"):
            # a path that walks anywhere but down is not a location, it is an escape
            orphans.append(item_id)
            path = posixpath.join(default_root, file_name(it))
        paths[item_id] = path
    return paths, sorted(set(orphans))
