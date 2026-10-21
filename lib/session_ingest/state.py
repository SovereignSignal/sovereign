"""Session capture config, the per-tool watermark and the daily call counter.

Everything lives under $SOV_STATE_DIR (default ~/.local/state/sovereign), never in the
archive. The config holds the owner's switches and lists; nothing owner-specific lives
in code. A bad config raises instead of falling back, because a dropped deny list would
quietly widen what the distiller reads.

The watermark is two files. A tick stages rows into <tool>.json.pending; the step after
the publish commits them into <tool>.json, or discards them so every session retries.
The two steps may run in separate processes, so a new Watermark picks up the pending
file. Calls are counted in <tool>.calls.json the moment they are made and are never
staged, so a discarded tick still spends its budget.
"""
import copy
import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import time

CONFIG_NAME = "session-capture.json"
DEFAULT_CONFIG = {
    "version": 1,
    "tools": {"claude-code": {"enabled": False, "enabled_at": None}},
    "allow": [],
    "deny": [],
    "quiet_min": 45,
    "min_prompts": 3,
    "min_score": 2,
    "entrypoints": ["cli"],
    "budget": {"calls_per_tick": 3, "chars_per_tick": 60000, "calls_per_day": 30},
    "phrases": {"memory": [], "decision": [], "correction": []},
}
CALL_DAYS = 7
MAX_FAILURES = 3
_TOOL = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def state_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get("SOV_STATE_DIR") or "~/.local/state/sovereign").expanduser()


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def _read_json(path, default):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("%s is a link and is not read." % path.name)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return copy.deepcopy(default)
    try:
        return json.loads(raw)
    except ValueError:
        raise ValueError("%s is not valid JSON." % path.name) from None


def _write_json(path, value):
    """Atomic replace, mode 600, in a private directory."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("%s is a link and is not written." % path.name)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _strings(value, where, absolute=False):
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ValueError("%s must be a list of strings." % where)
    if absolute and not all(os.path.isabs(os.path.expanduser(v)) for v in value):
        raise ValueError("%s must hold absolute paths." % where)
    return list(value)


def _merge(raw):
    if not isinstance(raw, dict):
        raise ValueError("Session capture config must be an object.")
    cfg = default_config()
    for key, value in raw.items():
        if key == "version":
            if value != 1:
                raise ValueError("Unknown session capture config version.")
        elif key == "tools":
            if not isinstance(value, dict):
                raise ValueError("tools must be an object.")
            for tool, entry in value.items():
                if not isinstance(entry, dict):
                    raise ValueError("tools.%s must be an object." % tool)
                merged = {"enabled": False, "enabled_at": None}
                merged.update(entry)
                if not isinstance(merged["enabled"], bool):
                    raise ValueError("tools.%s.enabled must be true or false." % tool)
                at = merged["enabled_at"]
                if at is not None and not isinstance(at, str) and not _number(at):
                    raise ValueError("tools.%s.enabled_at must be a time or null." % tool)
                cfg["tools"][tool] = merged
        elif key in ("allow", "deny"):
            cfg[key] = _strings(value, key, absolute=True)
        elif key == "entrypoints":
            cfg[key] = _strings(value, key)
        elif key in ("quiet_min", "min_prompts", "min_score"):
            if not _number(value) or value < 0:
                raise ValueError("%s must be a number." % key)
            cfg[key] = value
        elif key == "budget":
            if not isinstance(value, dict):
                raise ValueError("budget must be an object.")
            for name, n in value.items():
                if not _number(n) or n < 0:
                    raise ValueError("budget.%s must be a number." % name)
                cfg["budget"][name] = n
        elif key == "phrases":
            if not isinstance(value, dict):
                raise ValueError("phrases must be an object.")
            for name, items in value.items():
                cfg["phrases"][name] = _strings(items, "phrases.%s" % name)
        else:
            cfg[key] = value  # unknown keys are kept so a newer writer's fields survive
    return cfg


def load_config(sd):
    """The config at <sd>/session-capture.json merged over the defaults. Raises
    ValueError on a link, invalid JSON or a value of the wrong shape."""
    return _merge(_read_json(Path(sd) / CONFIG_NAME, {}))


def save_config(sd, cfg):
    _write_json(Path(sd) / CONFIG_NAME, _merge(cfg))


def needs_look(row, size, policy):
    """Whether a session with this watermark row deserves another look at `size` bytes
    under the current privacy `policy` hash.

    A row carries two sizes. `row["size"]` is the size when the verdict was given, and
    this compares against it: a skipped, denied or refused session is re-checked once
    the file has changed since that verdict. `row["seen"]["size"]` is the size at the
    last tick, which only prefilter.quiet reads. A row with no verdict yet (one that
    observe() made) is always looked at."""
    if row is None:
        return True
    verdict = row.get("verdict") or ""
    if not verdict:
        return True  # a row that only tracks size and mtime has no verdict yet
    if verdict == "distilled":
        return False  # final, even when the file grows
    if verdict.startswith("failed:"):
        try:
            return int(verdict.split(":", 1)[1]) < MAX_FAILURES
        except ValueError:
            return False
    if verdict in ("denied", "refused-archive"):
        return row.get("size") != size or row.get("policy") != policy
    return row.get("size") != size


class Watermark:
    """Rows per session id for one tool. `.rows` is the committed state only; staged
    rows and a staged `waiting` reach it through commit(), while observe() writes the
    last-tick size at once. One runner per tool at a time (the connector runner's lane
    lock) is assumed: record_call, observe and commit read, change and replace their
    file without a lock of their own."""

    def __init__(self, sd, tool):
        if not isinstance(tool, str) or not _TOOL.match(tool):
            raise ValueError("Unknown tool name.")
        folder = Path(sd) / "sessions"
        self.path = folder / (tool + ".json")
        self.pending_path = folder / (tool + ".json.pending")
        self.calls_path = folder / (tool + ".calls.json")
        doc = self._doc(self.path)
        self.rows = doc["sessions"]
        self.waiting = doc["waiting"]
        pending = self._doc(self.pending_path, staged=True)  # no "waiting" key: not staged
        self._staged = pending["sessions"]
        self._staged_waiting = pending.get("waiting", _UNSET)

    @staticmethod
    def _doc(path, staged=False):
        doc = _read_json(path, {"sessions": {}} if staged else {"sessions": {}, "waiting": None})
        if not isinstance(doc, dict) or not isinstance(doc.get("sessions", {}), dict) \
                or not all(isinstance(r, dict) for r in doc.get("sessions", {}).values()):
            raise ValueError("%s is not a session watermark." % Path(path).name)
        doc.setdefault("sessions", {})
        if not staged:
            doc.setdefault("waiting", None)
        waiting = doc.get("waiting")
        if waiting is not None and not isinstance(waiting, dict):
            raise ValueError("%s has an invalid waiting entry." % Path(path).name)
        return doc

    def _write_pending(self):
        doc = {"sessions": self._staged}
        if self._staged_waiting is not _UNSET:
            doc["waiting"] = self._staged_waiting
        _write_json(self.pending_path, doc)

    def observe(self, sid, size, mtime):
        """Record the size and mtime seen this tick in rows[sid]["seen"] and write it now,
        unstaged, so the next tick's quiet test survives a discarded tick. Verdict fields
        are never touched; a session with no row gets a verdict-less one."""
        row = self.rows.setdefault(sid, {})
        row["seen"] = {"size": size, "mtime": mtime,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _write_json(self.path, {"sessions": self.rows, "waiting": self.waiting})

    def stage(self, sid, row):
        self._staged[sid] = dict(row)
        self._write_pending()

    def stage_waiting(self, waiting):
        """Stage {"reason", "since"} or None for the next commit."""
        self._staged_waiting = waiting
        self._write_pending()

    def commit(self):
        for sid, row in self._staged.items():
            seen = self.rows.get(sid, {}).get("seen")
            merged = dict(row)
            if seen is not None and "seen" not in merged:
                merged["seen"] = seen  # a verdict row keeps the last-tick size
            self.rows[sid] = merged
        if self._staged_waiting is not _UNSET:
            self.waiting = self._staged_waiting
        _write_json(self.path, {"sessions": self.rows, "waiting": self.waiting})
        self._clear()

    def discard(self):
        self._clear()

    def _clear(self):
        self._staged = {}
        self._staged_waiting = _UNSET
        try:
            os.unlink(str(self.pending_path))
        except FileNotFoundError:
            pass

    def _calls(self):
        calls = _read_json(self.calls_path, {})
        if not isinstance(calls, dict):
            raise ValueError("%s is not a call counter." % self.calls_path.name)
        return calls

    def calls_today(self, date):
        n = self._calls().get(date, 0)
        if not _number(n):
            raise ValueError("%s has an invalid count for %s." % (self.calls_path.name, date))
        return n

    def record_call(self, date):
        """Count one call on `date` (YYYY-MM-DD) now, keep the last 7 days, return the
        day's new total."""
        calls = self._calls()
        today = datetime.date.fromisoformat(date)
        oldest = today - datetime.timedelta(days=CALL_DAYS - 1)
        kept = {}
        for day, n in calls.items():
            try:
                when = datetime.date.fromisoformat(day)
            except (TypeError, ValueError):
                continue
            if when >= oldest and _number(n):
                kept[day] = n
        kept[date] = kept.get(date, 0) + 1
        _write_json(self.calls_path, kept)
        return kept[date]


class _Unset:
    def __repr__(self):
        return "<unset>"


_UNSET = _Unset()
