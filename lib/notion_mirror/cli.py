"""Front door for bin/brain-mirror-notion.

  --check      prove the token, list reachable roots against roots.json, count items; writes nothing
  --full       walk everything and reconcile moves and deletions
  (default)    delta since the cursor; promoted to full when the last full walk is older than six days
  --dry-run    with either run: print what would change and the oracle match rate; writes nothing
  --status     print the resolved configuration and the state files
  --coverage DIR   compare a full Notion export folder with what the token can see; writes nothing

Exit codes: 0 ok, 1 errors or a refused run, 2 check found missing roots, 64 configuration.
"""
import argparse
import sys
from pathlib import Path

from .api import NotionClient
from .config import ConfigError, load_config
from .mirror import Mirror
from .state import State

LIST_LIMIT = 50


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="brain-mirror-notion", description="Mirror connected Notion pages into a brain lane.")
    ap.add_argument("--state-dir", help="instance state directory (default ~/.notion-mirror)")
    ap.add_argument("--check", action="store_true", help="prove the token and list roots, write nothing")
    ap.add_argument("--full", action="store_true", help="walk everything, reconcile moves and deletions")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument("--status", action="store_true", help="print configuration and state, run nothing")
    ap.add_argument("--coverage", metavar="DIR", help="compare a full Notion export folder with what the token can see; writes nothing")
    return ap


def _print_status(cfg) -> None:
    print("vault:      %s" % cfg.brain_root)
    print("lane:       %s" % cfg.lane_dir)
    print("state:      %s" % cfg.state_dir)
    print("version:    %s" % cfg.version)
    print("files:      %s" % cfg.files)
    print("floor:      %d%%" % cfg.shrink_floor)
    print("roots:      %d required, default folder %r" % (len(cfg.required_roots), cfg.default_root))
    for name in ("last-status", "last-success", "state/cursor", "state/last-full"):
        path = cfg.state_dir / name
        print("%-16s %s" % (name + ":", path.read_text(encoding="utf-8").strip() if path.exists() else "(none)"))


def _print_check(result: dict) -> None:
    print("bot: %s" % result["bot"])
    print("workspace: %s" % result["workspace"])
    kinds = ", ".join("%s %d" % (k, v) for k, v in sorted(result["kinds"].items()))
    print("items: %d (%s)" % (result["items"], kinds))
    print("roots reachable:")
    for root_id, title in sorted(result["roots"].items(), key=lambda kv: kv[1].lower()):
        print("  %s  %s" % (root_id, title or "(untitled)"))
    missing = result["missing_roots"]
    print("missing roots: %s" % (", ".join(missing) if missing else "none"))


def _print_coverage(result: dict) -> None:
    print("coverage: export %d, reachable %d, unreachable %d, new since export %d" % (
        result["export_total"], result["reachable"], result["unreachable"], result["new_since_export"]))
    for folder, count, samples in result["groups"]:
        print("  %5d  %s  e.g. %s" % (count, folder, "; ".join(samples)))


def _print_list(label: str, rows) -> None:
    rows = list(rows)
    if not rows:
        return
    print("%s (%d):" % (label, len(rows)))
    for row in rows[:LIST_LIMIT]:
        print("  " + (" -> ".join(row) if isinstance(row, tuple) else str(row)))
    if len(rows) > LIST_LIMIT:
        print("  ... %d more" % (len(rows) - LIST_LIMIT))


def main(argv=None, client_factory=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.state_dir)
    except ConfigError as exc:
        print("brain-mirror-notion: %s" % exc, file=sys.stderr)
        return 64
    if args.status:
        _print_status(cfg)
        return 0

    client = client_factory(cfg) if client_factory else NotionClient(cfg.token, cfg.version)
    state = State(cfg.state_dir)
    try:
        return _run(args, cfg, client, state)
    except Exception as exc:  # a crash must land as a FAILED status, never as a silent traceback
        reason = "crashed: %s: %s" % (type(exc).__name__, str(exc)[:300])
        try:
            state.fail(reason)
        except Exception:
            print("brain-mirror-notion: " + reason, file=sys.stderr)
        return 1


def _run(args, cfg, client, state) -> int:
    mirror = Mirror(client, cfg, state)

    if args.coverage:
        _print_coverage(mirror.coverage(Path(args.coverage)))
        return 0

    if args.check:
        result = mirror.check()
        _print_check(result)
        return 2 if result["missing_roots"] else 0

    run_full = args.full or state.full_due() or not state.read_cursor()
    rep = mirror.full(dry_run=args.dry_run) if run_full else mirror.delta(dry_run=args.dry_run)
    print(rep.summary())
    if args.dry_run:
        _print_list("would write", rep.would_write)
        _print_list("would move", rep.would_move)
        _print_list("would delete", rep.would_delete)
        _print_list("on disk, not in walk", rep.unclaimed)
        _print_list("oracle mismatches (id, expected, on disk)", [(i, p, d or "(absent)") for i, p, d in rep.mismatches])
    _print_list("warnings", rep.warnings)
    _print_list("errors", rep.errors)
    return 1 if (rep.errors or rep.refused) else 0
