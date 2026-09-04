"""What the mirror remembers between runs, and how it writes files it never half-writes.

Layout of the instance state directory (default ~/.notion-mirror):
  mirror.env, roots.json      owner config (read by config.py)
  last-status                 OK <ts> <summary>  |  FAILED <ts> <reason>
  last-success                ISO-8601 stamp with offset of the last fully successful run (the console parses it; the watchdog reads its mtime)
  mirror.log                  append-only run log
  state/manifest.json         {"items": {id: entry}}
  state/cursor                newest last_edited_time seen by a successful run
  state/last-full             <ts> of the last successful full walk
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

STAMP = "%Y-%m-%d %H:%M:%S"


def iso_now() -> str:
    """Local time with its UTC offset, seconds precision: 2026-09-04T15:40:00-07:00."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    """Write beside the target and rename over it, so a reader never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            os.unlink(tmp)
        raise


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists():
        with open(path, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() == sha256_bytes(data):
                return False
    atomic_write(path, data)
    return True


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.items: Dict[str, dict] = {}

    def load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = data.get("items", {})
        else:
            self.items = {}

    def save(self) -> None:
        atomic_write(self.path, json.dumps({"items": self.items}, sort_keys=True, ensure_ascii=False).encode("utf-8"))

    def rows_of(self, db_id: str) -> List[dict]:
        rows = [e for e in self.items.values() if e.get("kind") == "row" and e.get("db_id") == db_id]
        return sorted(rows, key=lambda e: ((e.get("title") or "").lower(), e.get("id", "")))


class State:
    def __init__(self, state_dir: Path):
        self.root = Path(state_dir)
        self.state = self.root / "state"
        self.state.mkdir(parents=True, exist_ok=True)

    def _read(self, path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def read_cursor(self) -> Optional[str]:
        return self._read(self.state / "cursor")

    def write_cursor(self, ts: str) -> None:
        atomic_write(self.state / "cursor", (ts + "\n").encode("utf-8"))

    def read_last_full(self) -> Optional[str]:
        return self._read(self.state / "last-full")

    def write_last_full(self) -> None:
        atomic_write(self.state / "last-full", (time.strftime(STAMP) + "\n").encode("utf-8"))

    def full_due(self, days: int = 6) -> bool:
        path = self.state / "last-full"
        if not path.exists():
            return True
        return (time.time() - path.stat().st_mtime) > days * 86400

    def ok(self, summary: str) -> None:
        stamp = time.strftime(STAMP)
        atomic_write(self.root / "last-status", ("OK %s %s\n" % (stamp, summary)).encode("utf-8"))
        atomic_write(self.root / "last-success", (iso_now() + "\n").encode("utf-8"))
        self.log("OK " + summary)

    def fail(self, reason: str) -> None:
        stamp = time.strftime(STAMP)
        atomic_write(self.root / "last-status", ("FAILED %s %s\n" % (stamp, reason)).encode("utf-8"))
        self.log("FAILED " + reason)

    def log(self, line: str) -> None:
        stamp = time.strftime(STAMP)
        try:
            with open(self.root / "mirror.log", "a", encoding="utf-8") as fh:
                fh.write("[%s] %s\n" % (stamp, line))
        except OSError:
            print("could not write to mirror.log", file=sys.stderr)
        print("[%s] %s" % (stamp, line), file=sys.stderr)
