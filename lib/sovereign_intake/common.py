"""Small shared boundaries for the contribution wire."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import signal
import tempfile

MAX_BODY = 12288
MAX_ITEM = 32768
MAX_SOURCE = 2 * 1024 * 1024
MAX_ITEMS = 10000
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
HEX = re.compile(r"[a-f0-9]{64}\Z")


class IntakeError(ValueError):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise IntakeError("invalid_timestamp")
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise IntakeError("invalid_timestamp") from None
    return value


def slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise IntakeError("invalid_identifier")
    return value


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 300:
        raise IntakeError("invalid_relative_path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")) or "\\" in value or any(ord(c) < 32 for c in value):
        raise IntakeError("invalid_relative_path")
    return p


def directory(path, create=False):
    """No linked components in owner-controlled state or output paths."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    for p in [*reversed(path.parents), path]:
        if p.is_symlink():
            raise IntakeError("linked_directory")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise IntakeError("missing_directory")
    return path


def read_under(root, name, limit):
    """Walk directory descriptors without following links; bound before reading."""
    parts = relative(name).parts
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(directory(root), flags | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        item = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(item, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise IntakeError("input_type_or_size")
        raw = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    if len(raw) > limit or (info.st_mtime_ns, info.st_size) != (after.st_mtime_ns, after.st_size):
        raise IntakeError("input_changed_or_too_large")
    return raw, info


def json_read(path, default=None):
    path = Path(path).expanduser().absolute()
    try:
        raw, _ = read_under(path.parent, path.name, 8 * 1024 * 1024)
    except FileNotFoundError:
        return default
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise IntakeError("invalid_json") from None


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def atomic(path, value):
    path = Path(path)
    directory(path.parent, create=True)
    if path.is_symlink():
        raise IntakeError("linked_output")
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def exclusive(path, raw):
    """Publish a complete file atomically, refusing any existing destination."""
    directory(path.parent)
    fd, temp = tempfile.mkstemp(prefix=".intake-tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path, follow_symlinks=False)
    finally:
        os.unlink(temp)


@contextlib.contextmanager
def locked(path):
    directory(path.parent, create=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IntakeError("writer_busy") from None
        yield
    finally:
        os.close(fd)


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def git(repo, *args, check=True, timeout=30, binary=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=7 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=yes", LC_ALL="C")
    try:
        process = subprocess.Popen(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never", "-C", str(repo), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=not binary, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise IntakeError("git_timeout") from None
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    except FileNotFoundError:
        raise IntakeError("git_not_installed") from None
    if check and result.returncode:
        # Remote stderr can contain credentials, URLs or submitted text.
        raise IntakeError("git_" + args[0] + "_failed")
    return result


def remote(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise IntakeError("invalid_intake_remote")
    if value.startswith("/"):
        directory(value)  # local, owner-selected disposable repositories are supported
    elif not re.fullmatch(r"(?:[a-zA-Z0-9_-]+@)?[a-zA-Z0-9][a-zA-Z0-9._-]*:[a-zA-Z0-9][a-zA-Z0-9._/-]*", value) or "/../" in value or value.endswith("/.."):
        raise IntakeError("use_ssh_intake_or_local_repository")
    return value
