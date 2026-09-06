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
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from brain_redact import redact_text

from .api import NotionError
from .config import Config, norm_id
from .exclude import apply_excludes, marker_text
from .model import item_from, title_of
from .paths import folder_for, resolve_paths
from .render import Links, csv_from_cells, property_order, render_csv, render_page, row_cells
from .scan import ScanError, run_scan
from .state import Manifest, State, atomic_write, write_if_changed

CHILD_KINDS = ("child_page", "child_database")
ITEM_FIELDS = ("id", "kind", "title", "parent_kind", "parent_id", "last_edited", "ds_id", "db_id", "inline", "excluded")
HEX = set("0123456789abcdef")
OVERLAP_MINUTES = 10


CHILDREN_ERROR_MAX = 120


def _vanished(exc: NotionError) -> bool:
    """A 404 (object_not_found) between the walk and the render means the item disappeared
    mid-run, not that the mirror is broken. Match on the string: the fake and real clients
    both fold the status into the message rather than exposing a typed code."""
    return "HTTP 404" in str(exc)


def _short_error(exc: NotionError) -> str:
    """A marker embedded in a rendered page must never be able to close the comment early or
    churn the file on every run over a volatile detail (a request id, say) in the body. Keep
    only the first line, capped short, with any run of dashes collapsed to one so `-->` cannot
    appear inside it. The full text still goes in the warning."""
    line = str(exc).splitlines()[0] if str(exc) else ""
    line = re.sub(r"-{2,}", "-", line)
    return line[:CHILDREN_ERROR_MAX]


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
    vanished: int = 0
    excluded: int = 0
    excluded_paths: List[str] = field(default_factory=list)
    written_paths: List[str] = field(default_factory=list)
    secrets: List[str] = field(default_factory=list)
    redacted: int = 0
    redacted_paths: List[str] = field(default_factory=list)
    refused: Optional[str] = None
    oracle_total: int = 0
    oracle_matched: int = 0
    mismatches: List[Tuple[str, str, str]] = field(default_factory=list)
    would_write: List[str] = field(default_factory=list)
    would_move: List[Tuple[str, str]] = field(default_factory=list)
    would_delete: List[str] = field(default_factory=list)
    unclaimed: List[str] = field(default_factory=list)

    def summary(self) -> str:
        text = "%s%s: wrote %d, unchanged %d, moved %d, deleted %d, attachments %d, orphans %d, errors %d, warnings %d" % (
            self.mode, " (dry run)" if self.dry_run else "", self.written, self.unchanged, self.moved, self.deleted,
            self.attachments, self.orphans, len(self.errors), len(self.warnings))
        if self.vanished:
            text += ", vanished %d" % self.vanished
        if self.excluded:
            text += ", excluded %d" % self.excluded
        if self.redacted:
            text += ", redacted %d value(s) in %d file(s)" % (self.redacted, len(self.redacted_paths))
        if self.secrets:
            text += "; SECRETS flagged in %d file(s), first: %s" % (len(self.secrets), self.secrets[0])
        if self.oracle_total:
            text += "; oracle %d/%d" % (self.oracle_matched, self.oracle_total)
        if self.unclaimed:
            text += "; unclaimed on disk %d" % len(self.unclaimed)
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

    def _exclude(self, items: Dict[str, dict], rep: Optional[Report] = None) -> Dict[str, dict]:
        """Mark excluded roots and drop everything under them, before any path is computed
        or any content fetched. Returns the dropped descendants."""
        dropped = apply_excludes(items, self.cfg.exclude_titles, self.cfg.exclude_ids, resolve_block=self._resolve_block)
        if rep is not None:
            rep.excluded = sum(1 for it in items.values() if it.get("excluded"))
        return dropped

    def _moves(self, items: Dict[str, dict], old: Dict[str, dict], paths: Dict[str, str]) -> Tuple[List[Tuple[str, str]], List[str]]:
        """Items whose recorded path differs from today's. A change in excluded state is not a
        move (a CSV does not become a marker by renaming, nor a marker a page): the old file
        is removed and the new one written. Returns (moves, stale paths to remove)."""
        moves: List[Tuple[str, str]] = []
        stale: List[str] = []
        for i in items:
            entry = old.get(i)
            if not entry or not entry.get("path") or entry["path"] == paths[i]:
                continue
            if bool(entry.get("excluded")) != bool(items[i].get("excluded")):
                stale.append(entry["path"])
            else:
                moves.append((entry["path"], paths[i]))
        return moves, stale

    def _schema(self, ds_id: str) -> dict:
        if ds_id not in self._schemas:
            self._schemas[ds_id] = (self.client.data_source(ds_id) or {}).get("properties") or {}
        return self._schemas[ds_id]

    def _index_dir(self, root: Path) -> Dict[str, str]:
        """id -> path relative to root for every file under it that carries a 32-hex id."""
        index: Dict[str, str] = {}
        root_str = str(root)
        for dirpath, _dirs, files in os.walk(root_str):
            for name in files:
                if name.endswith("_all.csv"):
                    base = name[:-8]
                elif name.endswith(".md"):
                    base = name[:-3]
                else:
                    continue
                candidate = base.rsplit(" ", 1)[-1]
                if len(candidate) == 32 and set(candidate) <= HEX:
                    index[candidate] = os.path.relpath(os.path.join(dirpath, name), root_str)
        return index

    def _disk_index(self) -> Dict[str, str]:
        """id -> lane-relative path for every file on disk that carries a 32-hex id."""
        return self._index_dir(self.cfg.lane_dir)

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
        self._exclude(items)
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
            "excluded": sum(1 for it in items.values() if it.get("excluded")),
        }

    # -- coverage -------------------------------------------------------------------

    def _fold(self, name: str) -> str:
        """The stem of a file name with its trailing 32-hex id stripped, or the name
        unchanged when it is a plain folder name (no id-bearing extension)."""
        if name.endswith("_all.csv"):
            name = name[:-8]
        elif name.endswith(".md"):
            name = name[:-3]
        else:
            return name
        return name.rsplit(" ", 1)[0]

    def coverage(self, export_dir: Path) -> dict:
        """What a full export holds that the walk cannot see, grouped by top folder. Read-only."""
        export = self._index_dir(Path(export_dir))
        items = self._walk()
        dropped = self._exclude(items)
        excluded_ids = set(dropped) | {i for i, it in items.items() if it.get("excluded")}
        unreachable = {i: p for i, p in export.items() if i not in items and i not in dropped}
        groups: Dict[str, List[str]] = {}
        for path in sorted(unreachable.values()):
            parts = path.split("/")
            # A file sitting directly under a top folder (no folder of its own between them)
            # still belongs to that top folder's group: fold its own stem, id stripped, in as
            # the second key component, the same as a real subfolder name would be.
            key = self._fold(parts[0]) if len(parts) < 2 else "%s/%s" % (parts[0], self._fold(parts[1]))
            groups.setdefault(key, []).append(self._fold(posixpath.basename(path)))
        ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        return {
            "export_total": len(export),
            "reachable": len(export) - len(unreachable),
            "unreachable": len(unreachable),
            "excluded": sum(1 for i in export if i in excluded_ids),
            "groups": [(key, len(stems), sorted(stems)[:3]) for key, stems in ordered],
            "new_since_export": sum(1 for i in items if i not in export),
        }

    # -- full -----------------------------------------------------------------------

    def full(self, dry_run: bool = False) -> Report:
        rep = Report("full", dry_run)
        old = self.manifest.items
        items = self._walk()
        dropped = self._exclude(items, rep)
        paths, orphans = self._paths_for(items)
        rep.orphans = len(orphans)
        rep.excluded_paths = sorted(paths[i] for i, it in items.items() if it.get("excluded"))

        # includes what an exclude dropped: a subtree mirrored before the rule came in goes now
        deleted = [i for i in old if i not in items]
        # the floor guards against a walk that shrank for no known reason (a disconnected root);
        # what an exclude rule dropped is explained, and does not count against it
        unexplained = [i for i in deleted if i not in dropped]
        allowed = len(old) * (100 - self.cfg.shrink_floor) // 100
        if old and len(unexplained) > allowed and not self.cfg.allow_shrink:
            rep.refused = "would delete %d of %d tracked items, above the %d%% floor; set NOTION_ALLOW_SHRINK=1 if that is real" % (
                len(unexplained), len(old), 100 - self.cfg.shrink_floor)
            self.state.fail(rep.refused)
            return rep

        disk = self._disk_index()
        for i, p in paths.items():
            rep.oracle_total += 1
            if (self.cfg.lane_dir / p).exists():
                rep.oracle_matched += 1
            elif len(rep.mismatches) < 200:
                rep.mismatches.append((i, p, disk.get(i, "")))
        # files carrying an id the walk never produced: a legacy export, or a page the token
        # can no longer see. The operator decides; the mirror only names them. A live run's
        # own delete step removes exactly these paths a few lines down, so this is only
        # informative on a dry run; computing it on a live run would report files the run
        # itself just cleaned up as if they were left behind.
        if dry_run:
            rep.unclaimed = sorted(path for i, path in disk.items() if i not in items)

        changed = [i for i, it in items.items()
                   if it.get("excluded") or it["kind"] == "database" or i not in old
                   or old[i].get("last_edited") != it["last_edited"] or not (self.cfg.lane_dir / paths[i]).exists()]
        moves, stale = self._moves(items, old, paths)
        rep.would_write = [paths[i] for i in changed]
        rep.would_move = moves
        rep.would_delete = [old[i].get("path", "") for i in deleted] + stale
        if dry_run:
            return rep

        self.manifest.items = {i: _entry_from(it, paths[i], old.get(i)) for i, it in items.items()}
        self._apply_moves(moves, rep)
        self._unlink(stale, rep)
        self._render_and_write(items, changed, paths, rep)
        self._apply_deletes(deleted, old, rep)
        self._prune_empty_dirs()
        self.manifest.save()
        if not rep.errors:
            self._scan_secrets(rep, whole_lane=True)
        # the cursor covers what the walk saw, dropped items included: an excluded page edited
        # daily must not hold the window open
        self._finish(rep, list(items.values()) + list(dropped.values()), cursor_floor="", full=True)
        return rep

    def _finish(self, rep: Report, items, cursor_floor: str, full: bool) -> None:
        """Write the status the run earned. Errors: FAILED, nothing advances, so the next
        run retries. Secrets flagged: the mirror itself is complete, so the cursor (and the
        full stamp) advance, but the status is FAILED and last-success is not touched, so
        the watchdog and the console both say so until the page is excluded or cleaned."""
        if rep.errors:
            # no last-full on a full run: tomorrow walks again, so errored items outside the delta window are retried within a day
            self.state.fail("%s: %d error(s), first: %s" % (rep.mode, len(rep.errors), rep.errors[0]))
            return
        newest = max([it["last_edited"] for it in items] + [cursor_floor])
        if newest:
            self.state.write_cursor(newest)
        if full:
            self.state.write_last_full()
        if rep.secrets:
            self.state.fail("%s: SECRETS flagged in %d file(s), first: %s; see secret-scan.log; exclude the page or rotate the secret" % (
                rep.mode, len(rep.secrets), rep.secrets[0]))
        else:
            self.state.ok(rep.summary())

    def _scan_secrets(self, rep: Report, whole_lane: bool) -> None:
        """A delta scans what it wrote; a full walk scans every file in the lane, so a secret
        that arrived before the scanner did is still found within the week."""
        if not self.cfg.secret_scan:
            return
        lane_rel = os.path.relpath(str(self.cfg.lane_dir), str(self.cfg.brain_root)).replace(os.sep, "/")
        if whole_lane:
            rel = sorted(posixpath.join(lane_rel, os.path.relpath(os.path.join(d, f), str(self.cfg.lane_dir)).replace(os.sep, "/"))
                         for d, _dirs, files in os.walk(str(self.cfg.lane_dir)) for f in files)
        else:
            rel = sorted(set(posixpath.join(lane_rel, p) for p in rep.written_paths))
        try:
            rep.secrets = run_scan(self.cfg.secret_scan, self.cfg.brain_root, rel, self.cfg.state_dir)
        except ScanError as exc:
            rep.errors.append(str(exc))

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
        items.update(fresh)
        self._ensure_parents(items, fresh, rep)
        dropped = self._exclude(items, rep)
        changed = [i for i, it in fresh.items() if i in items and (
            it.get("excluded") or it["kind"] != "database" or i not in old or old[i].get("last_edited") != it["last_edited"])]
        paths, orphans = self._paths_for(items)
        rep.orphans = len(orphans)
        rep.excluded_paths = sorted(paths[i] for i, it in fresh.items() if i in items and it.get("excluded"))
        moves, stale = self._moves(items, old, paths)
        # a page that moved under an excluded one, or a rule that now covers it: its file goes now, not at the weekly walk
        stale += [old[i]["path"] for i in dropped if i in old and old[i].get("path")]
        rep.would_write = [paths[i] for i in changed]
        rep.would_move = moves
        rep.would_delete = stale
        if dry_run:
            return rep

        self.manifest.items = {i: _entry_from(it, paths[i], old.get(i)) for i, it in items.items()}
        self._apply_moves(moves, rep)
        self._unlink(stale, rep)
        new_parents = [i for i in items if i not in old and i not in fresh]
        self._render_and_write(items, changed + new_parents, paths, rep)
        self._prune_empty_dirs()
        self.manifest.save()
        if not rep.errors:
            self._scan_secrets(rep, whole_lane=False)
        self._finish(rep, fresh.values(), cursor_floor=cursor, full=False)
        return rep

    # -- shared apply steps -----------------------------------------------------------

    def _relocate(self, rel_path: str) -> str:
        """A folder rename this run already performed carried its children with it. Rewrite a
        path recorded before the rename to where the file actually sits now. Two renames
        nested in the same walk (a folder, and beneath it a child folder) each shift the path
        by one prefix, so repeat the longest-prefix rewrite to a fixed point, capped at one
        pass per recorded rename so a swap cannot ping-pong forever."""
        renames = sorted(self._folder_renames, key=lambda r: -len(r[0]))
        for _ in range(len(self._folder_renames)):
            for old_folder, new_folder in renames:
                if rel_path == old_folder or rel_path.startswith(old_folder + "/"):
                    rel_path = new_folder + rel_path[len(old_folder):]
                    break
            else:
                break
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

    def _mark_vanished(self, it: dict, paths: Dict[str, str], rep: Report) -> None:
        """The item was there for the walk and gone by the time we tried to render it: a
        normal event on a churning workspace, not a run failure. Warn, drop it from the
        manifest so it is not retried daily, and clean up any file a prior run left behind."""
        path = paths.get(it["id"], "")
        rep.vanished += 1
        rep.warnings.append("vanished during the run: %s %s (%s)" % (it["kind"], it["id"], path))
        self.manifest.items.pop(it["id"], None)
        if path:
            target = self.cfg.lane_dir / path
            if not self._refused(target, rep) and target.exists():
                target.unlink()
                rep.deleted += 1

    def _render_and_write(self, items: Dict[str, dict], changed: List[str], paths: Dict[str, str], rep: Report) -> None:
        titles = {i: it.get("title", "") for i, it in items.items()}
        links = Links(paths, titles)
        dirty: Set[str] = set()
        vanished: Set[str] = set()
        for i in changed:
            it = items[i]
            try:
                if it.get("excluded"):
                    self._write_marker(it, paths, rep)
                elif it["kind"] == "database":
                    self._write_database(it, paths, links, rep)
                else:
                    self._write_page(it, paths, links, rep)
                    if it["kind"] == "row" and it.get("db_id"):
                        dirty.add(it["db_id"])
            except NotionError as exc:
                if _vanished(exc):
                    self._mark_vanished(it, paths, rep)
                    vanished.add(i)
                else:
                    rep.errors.append("%s %s: %s" % (it["kind"], i, exc))
                    entry = self.manifest.items.get(i)
                    if entry is not None:
                        entry["last_edited"] = ""  # retry next run
        for db_id in sorted(dirty - self._requeried - vanished):
            if db_id in items:
                try:
                    self._rebuild_csv(items[db_id], paths, links, rep)
                except NotionError as exc:
                    if _vanished(exc):
                        self._mark_vanished(items[db_id], paths, rep)
                    else:
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
                    block["children_error"] = _short_error(exc)
                    if rep is not None:
                        rep.warnings.append("children of %s %s: %s" % (block.get("type", ""), child_id, exc))
        return blocks

    def _put_text(self, rel_path: str, text: str, rep: Report) -> None:
        """Every rendered text goes through here: credential-shaped values are redacted before
        the bytes exist in the vault (brain_redact, the same rules as every lane), then the
        hash-compared write."""
        text, hits = redact_text(text)
        if hits:
            rep.redacted += len(hits)
            rep.redacted_paths.append(rel_path)
            rep.warnings.append("redacted %d value(s) in %s (%s)" % (len(hits), rel_path, ", ".join(sorted(set(hits)))))
        self._put(rel_path, text.encode("utf-8"), rep)

    def _cells(self, schema: dict, obj: dict, links: Links) -> List[str]:
        """Row cells cached in the manifest for CSV rebuilds: redacted before they are kept."""
        return [redact_text(cell)[0] for cell in row_cells(schema, obj, links)]

    def _put(self, rel_path: str, data: bytes, rep: Report) -> None:
        """Every content write goes through here: hash-compared, counted, and remembered for the scan."""
        if write_if_changed(self.cfg.lane_dir / rel_path, data):
            rep.written += 1
            rep.written_paths.append(rel_path)
        else:
            rep.unchanged += 1

    def _write_marker(self, it: dict, paths: Dict[str, str], rep: Report) -> None:
        """An excluded item: nothing is fetched, one line stands in for it on disk."""
        path = paths[it["id"]]
        if self._refused(self.cfg.lane_dir / path, rep):
            return
        self._put(path, marker_text(it["excluded"]).encode("utf-8"), rep)
        self.manifest.items.setdefault(it["id"], {}).pop("cells", None)

    def _write_page(self, it: dict, paths: Dict[str, str], links: Links, rep: Report) -> None:
        page_path = paths[it["id"]]
        obj = it.get("_obj") or self.client.page(it["id"])
        blocks = self._fetch_blocks(it["id"], rep)
        schema = self._schema(it["ds_id"]) if it["kind"] == "row" and it.get("ds_id") else None
        attachments: List[Tuple[str, str]] = []
        text = render_page(it, obj, blocks, links, attachments, page_path, schema_props=schema)
        if self._refused(self.cfg.lane_dir / page_path, rep):
            return
        self._put_text(page_path, text, rep)
        entry = self.manifest.items.setdefault(it["id"], {})
        if schema is not None:
            entry["cells"] = self._cells(schema, obj, links)
        self._fetch_attachments(attachments, rep)

    def _write_database(self, it: dict, paths: Dict[str, str], links: Links, rep: Report) -> None:
        schema = self._schema(it["ds_id"])
        # a row that is itself an excluded root has a marker for a page; its cells stay out of the CSV too
        rows = sorted((r for r in self.client.query_rows(it["ds_id"])
                       if not (self.manifest.items.get(norm_id(r.get("id"))) or {}).get("excluded")),
                      key=lambda r: (title_of(r).lower(), norm_id(r.get("id"))))
        text = render_csv(schema, rows, links)
        if self._refused(self.cfg.lane_dir / paths[it["id"]], rep):
            return
        self._put_text(paths[it["id"]], text, rep)
        entry = self.manifest.items.setdefault(it["id"], {})
        entry["header"] = property_order(schema)
        for row in rows:
            row_entry = self.manifest.items.get(norm_id(row.get("id")))
            if row_entry is not None:
                row_entry["cells"] = self._cells(schema, row, links)
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
        self._put_text(paths[it["id"]], text, rep)

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
                rep.written_paths.append(dest)
            except NotionError as exc:
                rep.warnings.append("attachment %s: %s" % (dest, exc))

    def _unlink(self, rel_paths: List[str], rep: Report) -> None:
        """Remove files a run no longer claims (a stale CSV under a marker, a page dropped
        under an exclude). Folders are left to _apply_deletes and the empty-dir prune."""
        for path in rel_paths:
            target = self.cfg.lane_dir / self._relocate(path)
            if self._refused(target, rep):
                continue
            if target.exists():
                target.unlink()
                rep.deleted += 1

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
