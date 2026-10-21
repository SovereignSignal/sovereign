import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class CardError(RuntimeError):
    """A stable, sanitizable card binding failure."""


@dataclass(frozen=True)
class BoundCard:
    slug: str
    relative_path: str
    content_sha256: str
    raw: bytes
    text: str


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _root_fd(root: Path) -> Tuple[Path, int]:
    root_abs = Path(os.path.abspath(str(root)))
    try:
        fd = os.open(root_abs, _DIR_FLAGS)
    except OSError as exc:
        raise CardError("unsafe_source") from exc
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise CardError("unsafe_source")
    return root_abs, fd


def _open_relative(root: Path, relative: Path) -> Tuple[Path, int]:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise CardError("unsafe_source")
    root_abs, fd = _root_fd(root)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        file_fd = os.open(relative.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
        os.close(fd)
        return root_abs, file_fd
    except OSError as exc:
        os.close(fd)
        raise CardError("unsafe_source") from exc


def _read_bound(root: Path, relative: Path, slug: str) -> BoundCard:
    root_abs, fd = _open_relative(root, relative)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CardError("source_not_regular")
        raw = handle.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CardError("invalid_utf8") from exc
    return BoundCard(
        slug=slug,
        relative_path=(root_abs / relative).relative_to(root_abs).as_posix(),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        raw=raw,
        text=text,
    )


def _listdir(fd: int) -> List[str]:
    try:
        return os.listdir(fd)
    except OSError as exc:
        raise CardError("source_scan_failed") from exc


def card_index(root: Path) -> Dict[str, List[Path]]:
    """Every knowledge/<lane>/<slug>.md by slug, scanned without following a symlinked directory."""
    _, root_fd = _root_fd(root)
    try:
        knowledge_fd = os.open("knowledge", _DIR_FLAGS, dir_fd=root_fd)
    except OSError as exc:
        os.close(root_fd)
        raise CardError("unsafe_source") from exc
    os.close(root_fd)
    index: Dict[str, List[Path]] = {}
    try:
        for lane in sorted(_listdir(knowledge_fd)):
            if lane in (".", "..") or "/" in lane:
                continue
            try:
                lane_fd = os.open(lane, _DIR_FLAGS, dir_fd=knowledge_fd)
            except OSError:
                continue
            try:
                for name in sorted(_listdir(lane_fd)):
                    if name.endswith(".md") and _SLUG.fullmatch(name[:-3]):
                        index.setdefault(name[:-3], []).append(Path("knowledge") / lane / name)
            finally:
                os.close(lane_fd)
    finally:
        os.close(knowledge_fd)
    return index


def _topic_candidates(root: Path, slug: str) -> List[Path]:
    return card_index(root).get(slug, [])


def _read_alias_file(parent_fd: int, name: str) -> Dict[str, str]:
    try:
        alias_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise CardError("unsafe_aliases") from exc
    with os.fdopen(alias_fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CardError("unsafe_aliases")
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise CardError("invalid_aliases")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CardError("invalid_aliases") from exc
    if not isinstance(payload, dict):
        raise CardError("invalid_aliases")
    aliases: Dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str) or not _SLUG.fullmatch(value):
            raise CardError("invalid_aliases")
        aliases[key] = value
    return aliases


def load_aliases(root: Path, user_alias_path: Optional[Path] = None) -> Dict[str, str]:
    _, root_fd = _root_fd(Path(root))
    try:
        aliases = _read_alias_file(root_fd, ".brain-aliases.json")
    finally:
        os.close(root_fd)
    user_path = Path.home() / ".brain-aliases.json" if user_alias_path is None else Path(user_alias_path)
    try:
        user_parent_fd = os.open(
            Path(os.path.abspath(str(user_path.parent))),
            _DIR_FLAGS,
        )
    except OSError as exc:
        raise CardError("unsafe_aliases") from exc
    try:
        aliases.update(_read_alias_file(user_parent_fd, user_path.name))
    finally:
        os.close(user_parent_fd)
    return aliases


def bind_overlay_reference(root: Path, overlay: Dict[str, dict], reference: str) -> BoundCard:
    root = Path(root)
    row = overlay.get(reference)
    if not isinstance(row, dict):
        raise CardError("reference_not_found")
    slug = row.get("slug")
    relative = row.get("relative_path")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise CardError("invalid_overlay")
    if not isinstance(relative, str):
        raise CardError("invalid_overlay")
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts or rel_path.parts[:1] != ("knowledge",):
        raise CardError("invalid_overlay_path")
    if rel_path.name != f"{slug}.md":
        raise CardError("binding_mismatch")
    expected_hash = row.get("content_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise CardError("invalid_overlay")
    card = _read_bound(root, rel_path, slug)
    if card.content_sha256 != expected_hash:
        raise CardError("stale_binding")
    return card


def bind_topic(root: Path, topic: str, aliases: Dict[str, str]) -> BoundCard:
    root = Path(root)
    slug = aliases.get(topic, topic)
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise CardError("invalid_topic")
    matches = _topic_candidates(root, slug)
    if not matches:
        raise CardError("card_not_found")
    if len(matches) != 1:
        raise CardError("ambiguous_card")
    return _read_bound(root, matches[0], slug)
