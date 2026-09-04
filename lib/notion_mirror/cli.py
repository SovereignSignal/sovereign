"""Front door for bin/brain-mirror-notion."""
import argparse
import sys

from .config import ConfigError, load_config


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="brain-mirror-notion", description="Mirror connected Notion pages into a brain lane.")
    ap.add_argument("--state-dir", help="instance state directory (default ~/.notion-mirror)")
    ap.add_argument("--status", action="store_true", help="print the resolved configuration and state files, run nothing")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.state_dir)
    except ConfigError as exc:
        print("brain-mirror-notion: %s" % exc, file=sys.stderr)
        return 64
    if args.status:
        print("vault:      %s" % cfg.brain_root)
        print("lane:       %s" % cfg.lane_dir)
        print("state:      %s" % cfg.state_dir)
        print("version:    %s" % cfg.version)
        print("files:      %s" % cfg.files)
        print("floor:      %d%%" % cfg.shrink_floor)
        print("roots:      %d required, default folder %r" % (len(cfg.required_roots), cfg.default_root))
        for name in ("last-status", "last-success"):
            path = cfg.state_dir / name
            print("%-12s%s" % (name + ":", path.read_text(encoding="utf-8").strip() if path.exists() else "(none)"))
        return 0
    print("brain-mirror-notion: nothing to do (use --status)", file=sys.stderr)
    return 64
