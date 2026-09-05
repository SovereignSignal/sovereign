"""The runs. Everything that touches the lane goes through here.

check   prove the token, list reachable roots against the required ones, count items
full    walk everything, reconcile moves and deletions, requery every database
delta   search since the cursor with overlap, rewrite only what changed

Writes are atomic and hash-compared, so an unchanged page keeps its mtime. Errors on one
item never stop the run; they are reported, the status says FAILED, and the cursor does
not advance, so the next run retries. A run that would delete more than the shrink
floor allows refuses before touching anything.
"""
import os
import posixpath
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .api import NotionError
from .config import Config, norm_id
from .model import item_from, title_of
from .paths import folder_for, resolve_paths
from .render import Links, csv_from_cells, property_order, render_csv, render_page, row_cells
from .state import Manifest, State, atomic_write, write_if_changed

CHILD_KINDS = ("child_page", "child_database")
ITEM_FIELDS = ("id", "kind", "title", "parent_kind", "parent_id", "last_edited", "ds_id", "db_id", "inline")
HEX = set("0123456789abcdef")
OVERLAP_MINUTES = 10


def _minus_minutes(stamp: str, minutes: int) -> str:
    """Notion stamps look like 2026-09-01T16:00:00.000Z. Subtract and keep the shape."""
    try:
        dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return stamp
    return (dt - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@dataclass
class Report:
    mode: str
    dry_run: bool
    written: int = 0
    unchanged: int = 0
    moved: int = 0
    deleted: int = 0
    attachments: int = 0
    orphans: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    refused: Optional[str] = None
    oracle_total: int = 0
    oracle_matched: int = 0
    mismatches: List[Tuple[str, str, str]] = field(default_factory=list)
    would_write: List[str] = field(default_factory=list)
    would_move: List[Tuple[str, str]] = field(default_factory=list)
    would_delete: List[str] = field(default_factory=list)

    def summary(self) -> str:
        text = "%s%s: wrote %d, unchanged %d, moved %d, deleted %d, attachments %d, orphans %d, errors %d, warnings %d" % (
            self.mode, " (dry run)" if self.dry_run else "", self.written, self.unchanged, self.moved, self.deleted,
            self.attachments, self.orphans, len(self.errors), len(self.warnings))
        if self.oracle_total:
            text += "; oracle %d/%d" % (self.oracle_matched, self.oracle_total)
        if self.refused:
            text += "; REFUSED: " + self.refused
        return text


def _entry_from(item: dict, path: str, old: Optional[dict]) -> dict:
    entry = dict(old or {})
    for key in ITEM_FIELDS:
        entry[key] = item.get(key, entry.get(key, ""))
    entry["path"] = path
    return entry


class Mirror:
    def __init__(self, client, cfg: Config, state: State):
        self.client = client
        self.cfg = cfg
        self.state = state
        self.manifest = Manifest(state.state / "manifest.json")
        self.manifest.load()
        self._schemas: Dict[str, dict] = {}
        self._block_parents: Dict[str, str] = {}
        self._requeried: Set[str] = set()
        self._folder_renames: List[Tuple[str, str]] = []

    # -- discovery ------------------------------------------------------------------

    def _walk(self, since: Optional[str] = None) -> Dict[str, dict]:
        """Every page and data source search returns, newest edit first. With `since`,
        stop at the first item older than it (search is sorted, so the rest are older too)."""
        items: Dict[str, dict] = {}
        for obj in self.client.search():
            it = item_from(obj)
            if since and it["last_edited"] < since:
                break
            if it["in_trash"] or not it["id"]:
                continue
            it["_obj"] = obj
            items[it["id"]] = it
        return items

    def _resolve_block(self, block_id: str) -> str:
        """A page whose parent is a block (a column, a synced block): climb to the page."""
        if block_id in self._block_parents:
            return self._block_parents[block_id]
        current = block_id
        for _ in range(20):
            try:
                parent = (self.client.block(current) or {}).get("parent") or {}
            except NotionError:
                break
            if parent.get("type") == "page_id":
                self._block_parents[block_id] = norm_id(parent["page_id"])
                return self._block_parents[block_id]
            if parent.get("type") == "block_id":
                current = norm_id(parent["block_id"])
                continue
            break
        self._block_parents[block_id] = ""
        return ""

    def _paths_for(self, items: Dict[str, dict]) -> Tuple[Dict[str, str], List[str]]:
        return resolve_paths(items, self.cfg.default_root, self.cfg.required_roots, resolve_block=self._resolve_block)

    def _schema(self, ds_id: str) -> dict:
        if ds_id not in self._schemas:
            self._schemas[ds_id] = (self.client.data_source(ds_id) or {}).get("properties") or {}
        return self._schemas[ds_id]

    def _disk_index(self) -> Dict[str, str]:
        """id -> lane-relative path for every file on disk that carries a 32-hex id."""
        index: Dict[str, str] = {}
        lane = str(self.cfg.lane_dir)
        for root, _dirs, files in os.walk(lane):
            for name in files:
                if name.endswith("_all.csv"):
                    base = name[:-8]
                elif name.endswith(".md"):
                    base = name[:-3]
                else:
                    continue
                candidate = base.rsplit(" ", 1)[-1]
                if len(candidate) == 32 and set(candidate) <= HEX:
                    index[candidate] = os.path.relpath(os.path.join(root, name), lane)
        return index

    def _inside_lane(self, target: Path) -> bool:
        """Every path the mirror writes or removes is computed from titles, so prove it
        lands under the lane before touching it."""
        return os.path.realpath(str(target)).startswith(os.path.realpath(str(self.cfg.lane_dir)) + os.sep)

    def _refused(self, target: Path, rep: Report) -> bool:
        if self._inside_lane(target):
            return False
        rep.errors.append("refused, outside the lane: %s" % target)
        return True

    # -- check ----------------------------------------------------------------------

    def check(self) -> dict:
        me = self.client.request("GET", "/users/me")
        items = self._walk()
        roots = {i: it["title"] for i, it in items.items() if it["parent_kind"] == "workspace"}
        kinds: Dict[str, int] = {}
        for it in items.values():
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        return {
            "bot": me.get("name", ""),
            "workspace": (me.get("bot") or {}).get("workspace_name", ""),
            "items": len(items),
            "kinds": kinds,
            "roots": roots,
            "missing_roots": sorted(i for i in self.cfg.required_roots if i not in roots),
        }

    # -- full -----------------------------------------------------------------------

    def full(self, dry_run: bool = False) -> Report:
        rep = Report("full", dry_run)
        old = self.manifest.items
        items = self._walk()
        paths, orphans = self._paths_for(items)
        rep.orphans = len(orphans)

        deleted = [i for i in old if i not in items]
        allowed = len(old) * (100 - self.cfg.shrink_floor) // 100
        if old and len(deleted) > allowed and not self.cfg.allow_shrink:
            rep.refused = "would delete %d of %d tracked items, above the %d%% floor; set NOTION_ALLOW_SHRINK=1 if that is real" % (
                len(deleted), len(old), 100 - self.cfg.shrink_floor)
            self.state.fail(rep.refused)
            return rep

        disk = self._disk_index()
        for i, p in paths.items():
            rep.oracle_total += 1
            if (self.cfg.lane_dir / p).exists():
                rep.oracle_matched += 1
            elif len(rep.mismatches) < 200:
                rep.mismatches.append((i, p, disk.get(i, "")))

        changed = [i for i, it in items.items()
                   if it["kind"] == "database" or i not in old or old[i].get("last_edited") != it["last_edited"]
                   or not (self.cfg.lane_dir / paths[i]).exists()]
        moves = [(old[i]["path"], paths[i]) for i in items if i in old and old[i].get("path") and old[i]["path"] != paths[i]]
        rep.would_write = [paths[i] for i in changed]
        rep.would_move = moves
        rep.would_delete = [old[i].get("path", "") for i in deleted]
        if dry_run:
            return rep

        self.manifest.items = {i: _entry_from(it, paths[i], old.get(i)) for i, it in items.items()}
        self._apply_moves(moves, rep)
        self._render_and_write(items, changed, paths, rep)
        self._apply_deletes(deleted, old, rep)
        self._prune_empty_dirs()
        self.manifest.save()
        if rep.errors:
            # no last-full: tomorrow's run is a full walk again, so errored items outside the delta window are retried within a day instead of waiting for the weekly walk
            self.state.fail("full: %d error(s), first: %s" % (len(rep.errors), rep.errors[0]))
        else:
            newest = max((it["last_edited"] for it in items.values()), default="")
            if newest:
                self.state.write_cursor(newest)
            self.state.write_last_full()
            self.state.ok(rep.summary())
        return rep

    # -- delta ----------------------------------------------------------------------

    def _ensure_parents(self, items: Dict[str, dict], fresh: Dict[str, dict], rep: Report) -> None:
        """A changed page whose ancestors were not in the window: fetch the chain upward
        until it meets something we already know."""
        for it in list(fresh.values()):
            kind, pid = it["parent_kind"], it["parent_id"]
            while pid and pid not in items and kind in ("page", "database"):
                try:
                    if kind == "page":
                        parent = item_from(self.client.page(pid))
                    else:
                        db = self.client.database(pid)
                        sources = db.get("data_sources") or []
                        if not sources:
                            break
                        parent = item_from(self.client.data_source(norm_id(sources[0].get("id"))))
                except NotionError as exc:
                    rep.warnings.append("parent %s of %s unreachable: %s" % (pid, it["id"], exc))
                    break
                items[parent["id"]] = parent
                kind, pid = parent["parent_kind"], parent["parent_id"]

    def delta(self, dry_run: bool = False) -> Report:
        cursor = self.state.read_cursor()
        if not cursor or not self.manifest.items:
            return self.full(dry_run)
        rep = Report("delta", dry_run)
        old = self.manifest.items
        fresh = self._walk(since=_minus_minutes(cursor, OVERLAP_MINUTES))
        items: Dict[str, dict] = {i: dict(e) for i, e in old.items()}
        # Notion rounds last_edited_time to the minute, so an edit inside the same minute as the
        # cursor is invisible to a stamp compare. Re-render every page the window returned; the
        # hash compare keeps that free of spurious writes. A database whose own stamp did not
        # move is left out: its CSV is rebuilt from cached cells when a row changes, and the
        # weekly full walk requeries every one, so a delta never pays for a requery per run.
        changed = [i for i, it in fresh.items()
                   if it["kind"] != "database" or i not in old or old[i].get("last_edited") != it["last_edited"]]
        items.update(fresh)
        self._ensure_parents(items, fresh, rep)
        paths, orphans = self._paths_for(items)
        rep.orphans = len(orphans)
        moves = [(old[i]["path"], paths[i]) for i in items if i in old and old[i].get("path") and old[i]["path"] != paths[i]]
        rep.would_write = [paths[i] for i in changed]
        rep.would_move = moves
        if dry_run:
            return rep

        self.manifest.items = {i: _entry_from(it, paths[i], old.get(i)) for i, it in items.items()}
        self._apply_moves(moves, rep)
        new_parents = [i for i in items if i not in old and i not in fresh]
        self._render_and_write(items, changed + new_parents, paths, rep)
        self.manifest.save()
        if rep.errors:
            self.state.fail("delta: %d error(s), first: %s" % (len(rep.errors), rep.errors[0]))
        else:
            newest = max([it["last_edited"] for it in fresh.values()] + [cursor])
            self.state.write_cursor(newest)
            self.state.ok(rep.summary())
        return rep

    # -- shared apply steps -----------------------------------------------------------

    def _relocate(self, rel_path: str) -> str:
        """A folder rename this run already performed carried its children with it. Rewrite a
        path recorded before the rename to where the file actually sits now."""
        for old_folder, new_folder in sorted(self._folder_renames, key=lambda r: -len(r[0])):
            if rel_path == old_folder or rel_path.startswith(old_folder + "/"):
                return new_folder + rel_path[len(old_folder):]
        return rel_path

    def _apply_moves(self, moves: List[Tuple[str, str]], rep: Report) -> None:
        lane = self.cfg.lane_dir
        self._folder_renames = []
        for old_path, new_path in sorted(moves, key=lambda m: m[0].count("/")):
            old_path = self._relocate(old_path)
            if old_path == new_path:
                continue  # already carried along by a parent folder rename
            src, dst = lane / old_path, lane / new_path
            if self._refused(src, rep) or self._refused(dst, rep):
                continue
            if not src.exists():
                continue
            if dst.exists():
                rep.warnings.append("move skipped, target exists: %s -> %s" % (old_path, new_path))
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(src), str(dst))
            rep.moved += 1
            old_folder, new_folder = lane / folder_for(old_path), lane / folder_for(new_path)
            if old_folder.is_dir() and not new_folder.exists():
                if self._refused(old_folder, rep) or self._refused(new_folder, rep):
                    continue
                new_folder.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(old_folder), str(new_folder))
                self._folder_renames.append((folder_for(old_path), folder_for(new_path)))

    def _render_and_write(self, items: Dict[str, dict], changed: List[str], paths: Dict[str, str], rep: Report) -> None:
        titles = {i: it.get("title", "") for i, it in items.items()}
        links = Links(paths, titles)
        dirty: Set[str] = set()
        for i in changed:
            it = items[i]
            try:
                if it["kind"] == "database":
                    self._write_database(it, paths, links, rep)
                else:
                    self._write_page(it, paths, links, rep)
                    if it["kind"] == "row" and it.get("db_id"):
                        dirty.add(it["db_id"])
            except NotionError as exc:
                rep.errors.append("%s %s: %s" % (it["kind"], i, exc))
                entry = self.manifest.items.get(i)
                if entry is not None:
                    entry["last_edited"] = ""  # retry next run
        for db_id in sorted(dirty - self._requeried):
            if db_id in items:
                try:
                    self._rebuild_csv(items[db_id], paths, links, rep)
                except NotionError as exc:
                    rep.errors.append("database %s: %s" % (db_id, exc))

    def _fetch_blocks(self, block_id: str, rep: Optional[Report] = None) -> List[dict]:
        """The page's own block list is fatal: without it there is no page. One nested block
        that will not load is not, or a single bad toggle blocks the page every day and the
        dry run cannot say why. Note it on the block, warn, and render the rest."""
        blocks = self.client.children(block_id)
        for block in blocks:
            if block.get("has_children") and block.get("type") not in CHILD_KINDS:
                child_id = norm_id(block.get("id"))
                try:
                    block["children"] = self._fetch_blocks(child_id, rep)
                except NotionError as exc:
                    block["children"] = []
                    block["children_error"] = str(exc)
                    if rep is not None:
                        rep.warnings.append("children of %s %s: %s" % (block.get("type", ""), child_id, exc))
        return blocks

    def _write_page(self, it: dict, paths: Dict[str, str], links: Links, rep: Report) -> None:
        page_path = paths[it["id"]]
        obj = it.get("_obj") or self.client.page(it["id"])
        blocks = self._fetch_blocks(it["id"], rep)
        schema = self._schema(it["ds_id"]) if it["kind"] == "row" and it.get("ds_id") else None
        attachments: List[Tuple[str, str]] = []
        text = render_page(it, obj, blocks, links, attachments, page_path, schema_props=schema)
        if self._refused(self.cfg.lane_dir / page_path, rep):
            return
        if write_if_changed(self.cfg.lane_dir / page_path, text.encode("utf-8")):
            rep.written += 1
        else:
            rep.unchanged += 1
        entry = self.manifest.items.setdefault(it["id"], {})
        if schema is not None:
            entry["cells"] = row_cells(schema, obj, links)
        self._fetch_attachments(attachments, rep)

    def _write_database(self, it: dict, paths: Dict[str, str], links: Links, rep: Report) -> None:
        schema = self._schema(it["ds_id"])
        rows = sorted(self.client.query_rows(it["ds_id"]), key=lambda r: (title_of(r).lower(), norm_id(r.get("id"))))
        text = render_csv(schema, rows, links)
        if self._refused(self.cfg.lane_dir / paths[it["id"]], rep):
            return
        if write_if_changed(self.cfg.lane_dir / paths[it["id"]], text.encode("utf-8")):
            rep.written += 1
        else:
            rep.unchanged += 1
        entry = self.manifest.items.setdefault(it["id"], {})
        entry["header"] = property_order(schema)
        for row in rows:
            row_entry = self.manifest.items.get(norm_id(row.get("id")))
            if row_entry is not None:
                row_entry["cells"] = row_cells(schema, row, links)
        self._requeried.add(it["id"])

    def _rebuild_csv(self, it: dict, paths: Dict[str, str], links: Links, rep: Report) -> None:
        """A row changed: rebuild its database's CSV from cached cells, or requery when the
        schema no longer matches the cached header."""
        entry = self.manifest.items.get(it["id"]) or {}
        header = entry.get("header")
        schema = self._schema(it["ds_id"])
        rows = self.manifest.rows_of(it["id"])
        if not header or header != property_order(schema) or any("cells" not in r for r in rows):
            self._write_database(it, paths, links, rep)
            return
        text = csv_from_cells(header, [r["cells"] for r in rows])
        if self._refused(self.cfg.lane_dir / paths[it["id"]], rep):
            return
        if write_if_changed(self.cfg.lane_dir / paths[it["id"]], text.encode("utf-8")):
            rep.written += 1
        else:
            rep.unchanged += 1

    def _fetch_attachments(self, attachments: List[Tuple[str, str]], rep: Report) -> None:
        if self.cfg.files != "fetch":
            return
        for url, dest in attachments:
            target = self.cfg.lane_dir / dest
            if self._refused(target, rep):
                continue
            if target.exists():
                continue
            try:
                atomic_write(target, self.client.download(url))
                rep.attachments += 1
            except NotionError as exc:
                rep.warnings.append("attachment %s: %s" % (dest, exc))

    def _apply_deletes(self, deleted: List[str], old: Dict[str, dict], rep: Report) -> None:
        lane = self.cfg.lane_dir
        kept = [e.get("path", "") for e in self.manifest.items.values()]
        for i in deleted:
            path = old[i].get("path")
            if not path:
                continue
            path = self._relocate(path)
            target = lane / path
            if self._refused(target, rep):
                continue
            if target.exists():
                target.unlink()
                rep.deleted += 1
            folder_rel = folder_for(path)
            folder = lane / folder_rel
            if folder.is_dir() and not any(p.startswith(folder_rel + "/") for p in kept):
                if self._refused(folder, rep):
                    continue
                shutil.rmtree(str(folder))

    def _prune_empty_dirs(self) -> None:
        lane = str(self.cfg.lane_dir)
        for root, dirs, files in os.walk(lane, topdown=False):
            if root != lane and not dirs and not files:
                try:
                    os.rmdir(root)
                except OSError:
                    pass
