import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Dict


class SafetyError(RuntimeError):
    """A stable, sanitizable safety failure."""


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _open_private_parent(parent: Path, project_root: Path) -> int:
    root_abs = Path(os.path.abspath(str(project_root)))
    parent_abs = Path(os.path.abspath(str(parent)))
    if not _inside(parent_abs, root_abs):
        raise SafetyError("output_outside_project")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root_abs, flags)
    except OSError as exc:
        raise SafetyError("unsafe_output_parent") from exc
    try:
        for part in parent_abs.relative_to(root_abs).parts:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise SafetyError("unsafe_output_parent")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise SafetyError("output_parent_not_private")
        return fd
    except SafetyError:
        os.close(fd)
        raise
    except OSError as exc:
        os.close(fd)
        raise SafetyError("unsafe_output_parent") from exc


def read_json_private(path: Path, project_root: Path, max_bytes: int = 1024 * 1024) -> Any:
    path_abs = Path(os.path.abspath(str(path)))
    root_abs = Path(os.path.abspath(str(project_root)))
    parent_fd = _open_private_parent(path_abs.parent, root_abs)
    try:
        fd = os.open(path_abs.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
    except OSError as exc:
        raise SafetyError("unsafe_private_input") from exc
    finally:
        os.close(parent_fd)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise SafetyError("unsafe_private_input")
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SafetyError("private_input_too_large")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafetyError("invalid_private_json") from exc


def write_json_exclusive(path: Path, payload: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    path_abs = Path(os.path.abspath(str(path)))
    root_abs = Path(os.path.abspath(str(project_root)))
    parent_fd = _open_private_parent(path_abs.parent, root_abs)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path_abs.name, flags, 0o600, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise SafetyError("output_exists") from exc
    except OSError as exc:
        raise SafetyError("unsafe_output") from exc
    finally:
        os.close(parent_fd)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
