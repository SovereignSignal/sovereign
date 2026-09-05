"""Instance configuration. Everything specific to one brain lives outside the template.

Reads <state_dir>/mirror.env (KEY=VALUE lines) and <state_dir>/roots.json.
The environment wins over the file so tests and one-off runs can override.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

DEFAULT_VERSION = "2026-03-11"
DEFAULT_LANE = "raw/tools/Notion"
DEFAULT_ROOT_FOLDER = "Private & Shared"
DEFAULT_SHRINK_FLOOR = 90
DEFAULT_MIN_INTERVAL = 0.34


class ConfigError(RuntimeError):
    """A configuration problem the owner has to fix. Always fatal, always explained."""


def norm_id(value: Optional[str]) -> str:
    """Notion ids arrive dashed or bare, any case. Store them as 32 lowercase hex chars."""
    return (value or "").replace("-", "").strip().lower()


def read_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def read_pointer(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass
class Config:
    token: str
    version: str
    brain_root: Path
    lane_dir: Path
    state_dir: Path
    files: str
    shrink_floor: int
    allow_shrink: bool
    default_root: str
    required_roots: Dict[str, str]
    min_interval: float = DEFAULT_MIN_INTERVAL


def load_config(state_dir=None, env=None) -> Config:
    env = dict(os.environ) if env is None else dict(env)
    state_dir = Path(state_dir or env.get("NOTION_STATE_DIR") or (Path.home() / ".notion-mirror"))
    file_env = read_env_file(state_dir / "mirror.env")

    def get(key: str, default: str = "") -> str:
        return env.get(key) or file_env.get(key) or default

    token = get("NOTION_API_KEY")
    if not token:
        raise ConfigError("NOTION_API_KEY is not set (put it in %s or the environment)" % (state_dir / "mirror.env"))
    brain_root = get("BRAIN_ROOT") or read_pointer(Path.home() / ".brain-root")
    if not brain_root:
        raise ConfigError("BRAIN_ROOT is not set and ~/.brain-root is missing")
    files = get("NOTION_FILES", "fetch")
    if files not in ("fetch", "skip"):
        raise ConfigError("NOTION_FILES must be fetch or skip, not %r" % files)
    try:
        shrink_floor = int(get("NOTION_SHRINK_FLOOR", str(DEFAULT_SHRINK_FLOOR)))
    except ValueError:
        raise ConfigError("NOTION_SHRINK_FLOOR must be an integer percent")
    allow_shrink = get("NOTION_ALLOW_SHRINK", "0") == "1"
    try:
        min_interval = float(get("NOTION_MIN_INTERVAL", str(DEFAULT_MIN_INTERVAL)))
    except ValueError:
        raise ConfigError("NOTION_MIN_INTERVAL must be a number greater than 0")
    if min_interval <= 0:
        raise ConfigError("NOTION_MIN_INTERVAL must be a number greater than 0")
    lane = get("NOTION_LANE", DEFAULT_LANE)
    # same rule the installer applies to --lane: the lane is a relative path inside the vault
    if lane.startswith("/") or ".." in lane.split("/"):
        raise ConfigError("NOTION_LANE must be a relative path inside the vault with no .. segments, not %r" % lane)
    lane = lane.strip("/")

    default_root = DEFAULT_ROOT_FOLDER
    required: Dict[str, str] = {}
    roots_path = state_dir / "roots.json"
    if roots_path.exists():
        try:
            data = json.loads(roots_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError("roots.json is not valid JSON: %s" % exc)
        default_root = str(data.get("default") or DEFAULT_ROOT_FOLDER).strip("/")
        for key, folder in (data.get("required") or {}).items():
            required[norm_id(key)] = str(folder).strip("/")

    root = Path(brain_root).expanduser()
    return Config(
        token=token,
        version=get("NOTION_VERSION", DEFAULT_VERSION),
        brain_root=root,
        lane_dir=root / lane,
        state_dir=state_dir,
        files=files,
        shrink_floor=shrink_floor,
        allow_shrink=allow_shrink,
        default_root=default_root,
        required_roots=required,
        min_interval=min_interval,
    )
