"""Bounded, read-only discovery of local tools from the existing connector catalog."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "connectors/harness/_lib/known-tools.json"


def discover(catalog, home, applications, executable_dirs):
    tools, warnings = {}, []
    def expand(value):
        return home / value[2:] if value.startswith("~/") else Path(value)
    def present(path, kind):
        try:
            stat = path.stat()
            if kind == "executable":
                return path.is_file() and os.access(path, os.X_OK)
            return path.is_dir() if kind == "application" else bool(stat)
        except (FileNotFoundError, NotADirectoryError):
            return False
        except OSError:
            warnings.append("Could not inspect " + str(path))
            return False
    for entry in catalog["tools"]:
        key = entry.get("connector") or entry["id"]
        tool = tools.setdefault(key, dict(id=key, name=entry["name"], connector=entry.get("connector"),
                                          cloud=bool(entry.get("cloud")), aliases=[], evidence=[]))
        if tool["name"] != entry["name"]:
            tool["aliases"].append(entry["name"])
        candidates = [(expand(p), "configuration") for p in entry.get("detect", []) if not p.endswith(".app")]
        apps = set(entry.get("apps", [])) | {Path(p).name for p in entry.get("detect", []) if p.endswith(".app")}
        candidates += [(directory / app, "application") for directory in applications for app in sorted(apps)]
        candidates += [(directory / command, "executable") for directory in executable_dirs for command in entry.get("commands", [])]
        seen = {e["path"] for e in tool["evidence"]}
        for path, kind in candidates:
            if str(path) not in seen and present(path, kind):
                tool["evidence"].append(dict(path=str(path), kind=kind))
                seen.add(str(path))
    for tool in tools.values():
        tool["detected"] = bool(tool["evidence"])
        tool["installed"] = any(e["kind"] in ("application", "executable") for e in tool["evidence"])
    return dict(scanned_at=datetime.now(timezone.utc).isoformat(), tools=list(tools.values()), warnings=sorted(set(warnings)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--applications", type=Path, action="append")
    parser.add_argument("--path", help="Directories to inspect for known commands; none are executed.")
    args = parser.parse_args()
    # Ignore relative PATH entries: discovery never depends on the working directory.
    paths = [Path(p) for p in (args.path if args.path is not None else os.environ.get("PATH", "")).split(os.pathsep) if p and Path(p).is_absolute()]
    paths += [args.home / ".local/bin", args.home / ".cargo/bin"] if args.path is None else []
    try:
        result = discover(json.loads(CATALOG.read_text()), args.home,
                          args.applications or [Path("/Applications"), args.home / "Applications"], paths)
    except (OSError, ValueError, KeyError):
        print(json.dumps({"error": "The tool catalog could not be read. Reinstall a complete copy of Sovereign."}))
        return 1
    print(json.dumps(result))
    return 0
