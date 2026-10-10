"""Retire or restore a lane by its contract, LANE.md, and keep its history.

A lane's LANE.md is what every machine reads to decide whether a source is live. Retiring
is the owner's answer to a source they no longer use: the files stay as provenance, and
`status: retired` tells status, the hub and every mirror to stop expecting deliveries.

On a machine that stages, the same lane has a staging copy that status reads
first and the relay never carries. Both copies change together, or one machine keeps
alerting on a source the owner retired.
"""
import datetime
import os
import re
import tempfile
from pathlib import Path

LANE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
FIELD = re.compile(r"^(status|retired|retired_from):[^\n]*\n", re.M)


def contracts(lane, root, stage=None):
    """Every LANE.md for this lane: the archive's copy first, then a staging copy."""
    if not LANE_NAME.fullmatch(lane or ""):
        raise ValueError("Unknown lane name")
    bases = [Path(root) / "raw" / "tools", Path(root) / "raw" / "workspaces"]
    if stage:
        bases.append(Path(stage) / "raw" / "tools")
    found = []
    for base in bases:
        path = base / lane / "LANE.md"
        if path.is_symlink():
            raise ValueError("Refusing a linked lane contract: " + str(path))
        if path.is_file():
            found.append(path)
    if not found:
        raise ValueError("No lane contract for " + lane)
    return found


def _split(text):
    if not text.startswith("---\n"):
        raise ValueError("Lane contract has no frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("Lane contract frontmatter is not closed")
    return text[4:end + 1], text[end + 1:]


def _status(fm):
    m = re.search(r"^status:([^\n#]*)", fm, re.M)
    return m.group(1).strip() if m else ""


def retired_text(text, reason, day=None):
    """The contract with status: retired, the date and reason, and the status it had."""
    fm, rest = _split(text)
    was = _status(fm)
    if was == "retired":
        return text
    day = day or datetime.date.today().isoformat()
    reason = " ".join(str(reason or "retired by the owner").split())
    fm = FIELD.sub("", fm)
    fm += "status: retired\nretired: %s (%s)\n" % (day, reason)
    if was:
        fm += "retired_from: %s\n" % was
    return "---\n" + fm + rest


def restored_text(text):
    """The contract back at the status it had before it was retired."""
    fm, rest = _split(text)
    if _status(fm) != "retired":
        return text
    m = re.search(r"^retired_from:([^\n#]*)", fm, re.M)
    was = (m.group(1).strip() if m else "") or "onboarded"
    fm = FIELD.sub("", fm) + "status: %s\n" % was
    return "---\n" + fm + rest


def plan(lane, root, stage=None, restore=False, reason=None, day=None):
    """[(path, before, after)] for each copy that would change."""
    out = []
    for path in contracts(lane, root, stage):
        before = path.read_text()
        after = restored_text(before) if restore else retired_text(before, reason, day)
        if after != before:
            out.append((path, before, after))
    return out


def write(edits):
    """Write each copy atomically, refusing one that changed since it was planned."""
    for path, before, after in edits:
        if path.read_text() != before:
            raise ValueError("Lane contract changed while it was being updated: " + str(path))
        mode = path.stat().st_mode & 0o777
        fd, temp = tempfile.mkstemp(prefix=".lane-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w") as out:
                out.write(after)
            os.chmod(temp, mode)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
