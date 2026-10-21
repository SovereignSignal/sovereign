"""The privacy gate: which working directories a session may have run in.

A session that ran inside an archive saw that archive, so its transcript carries the
archive's own text; distilling it would launder knowledge back in through raw/. Such a
session is refused, and the allow list cannot override that. "Inside an archive" means
inside this vault, or under any folder shaped like one: CLAUDE.md beside knowledge/ and
raw/. A PermissionError while probing counts as an archive, because on macOS a folder
the runner may not read (a protected folder without Full Disk Access) could be one.

After that the owner's deny prefixes apply, and temporary roots are off unless allowed.
"""
import errno
import hashlib
import json
import os
import stat
import sys

REFUSED = "refused-archive"
DENIED = "denied"
_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


class _Blocked(Exception):
    pass


def _kind(path):
    """S_IFMT of path, None when absent; raises _Blocked when it cannot be probed."""
    try:
        return stat.S_IFMT(os.stat(path).st_mode)
    except PermissionError:
        raise _Blocked()
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG):
            return None
        raise _Blocked()


def archive_like(path):
    """True when `path` or any ancestor holds CLAUDE.md beside knowledge/ and raw/, or
    when probing one of them is refused (fail closed)."""
    here = os.path.realpath(os.path.abspath(str(path)))
    while True:
        try:
            if (_kind(os.path.join(here, "CLAUDE.md")) == stat.S_IFREG
                    and _kind(os.path.join(here, "knowledge")) == stat.S_IFDIR
                    and _kind(os.path.join(here, "raw")) == stat.S_IFDIR):
                return True
        except _Blocked:
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def _norm(path):
    return os.path.realpath(os.path.expanduser(str(path))).rstrip("/") or "/"


def _fold(path):
    """The form a prefix compare uses. macOS volumes are usually case-insensitive and
    realpath keeps the case it was given, so there both sides are casefolded, which errs
    toward a match (a deny or a refusal); elsewhere the compare is exact."""
    path = os.path.normcase(path)
    return path.casefold() if sys.platform == "darwin" else path


def _under(p, x):
    p, x = _fold(p), _fold(x)
    return x == "/" or p == x or p.startswith(x + "/")


def make_cwd_check(vault, cfg):
    """A cwd_check for claude_code.scan: realpath -> "refused-archive", "denied" or None.
    Lists and the temporary roots are resolved once, here.

    Only the archive and what lies under it are refused. A cwd that is an ancestor of
    the archive, such as the home folder holding ~/<archive>, is not: a home-folder
    archive is the default, and refusing ancestors would exclude every session run
    from the home directory. The owner's deny list covers such a folder when wanted."""
    vault_root = _norm(vault) if vault else None
    allow = [_norm(x) for x in cfg.get("allow", [])]
    deny = [_norm(x) for x in cfg.get("deny", [])]
    temp = set(_TEMP_ROOTS) | {_norm(x) for x in _TEMP_ROOTS}
    if os.environ.get("TMPDIR"):
        temp.add(_norm(os.environ["TMPDIR"]))

    def check(cwd):
        p = _norm(cwd)
        if (vault_root and _under(p, vault_root)) or archive_like(p):
            return REFUSED
        if any(_under(p, x) for x in deny):
            return DENIED
        if any(_under(p, x) for x in temp) and not any(_under(p, x) for x in allow):
            return DENIED
        return None

    return check


def policy_hash(cfg):
    """sha1 of the sorted allow and deny lists: a change re-opens denied and refused rows."""
    body = json.dumps({"allow": sorted(cfg.get("allow", [])), "deny": sorted(cfg.get("deny", []))},
                      sort_keys=True)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()
