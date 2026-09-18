"""Instance configuration. Everything specific to one archive lives outside the template.

Reads <state_dir>/mirror.env (KEY=VALUE lines) and <state_dir>/roots.json.
The environment wins over the file so tests and one-off runs can override.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from .exclude import DEFAULT_EXCLUDE_TITLES

DEFAULT_VERSION = "2026-03-11"
DEFAULT_LANE = "raw/tools/Notion"
DEFAULT_ROOT_FOLDER = "Private & Shared"
DEFAULT_SHRINK_FLOOR = 90
DEFAULT_MIN_INTERVAL = 0.34
SCANNER_REL = "cron-wrappers/vault-secret-scan.sh"  # beside the mirror's own bin, when the archive ships one


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
    exclude_titles: List[str] = None  # type: ignore[assignment]
    exclude_ids: Set[str] = None  # type: ignore[assignment]
    secret_scan: str = ""

    def __post_init__(self) -> None:
        if self.exclude_titles is None:
            self.exclude_titles = list(DEFAULT_EXCLUDE_TITLES)
        if self.exclude_ids is None:
            self.exclude_ids = set()


def _phrases(value: str) -> List[str]:
    """NOTION_EXCLUDE_TITLES: comma-separated phrases; `off` turns the title rule off."""
    if value.strip().lower() in ("off", "none"):
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def load_config(state_dir=None, env=None, bin_dir=None) -> Config:
    env = dict(os.environ) if env is None else dict(env)
    state_dir = Path(state_dir or env.get("NOTION_STATE_DIR") or (Path.home() / ".notion-mirror"))
    file_env = read_env_file(state_dir / "mirror.env")

    def get(key: str, default: str = "") -> str:
        return env.get(key) or file_env.get(key) or default

    token = get("NOTION_API_KEY")
    if not token:
        raise ConfigError("NOTION_API_KEY is not set (put it in %s or the environment)" % (state_dir / "mirror.env"))
    brain_root = get("BRAIN_ROOT") or get("SOVS_VAULT") or read_pointer(Path.home() / ".brain-root") or get("SOVEREIGN_ROOT") or get("SOVEREIGN_VAULT")
    if not brain_root:
        raise ConfigError("Set SOVEREIGN_ROOT (legacy BRAIN_ROOT or ~/.brain-root also works)")
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
    exclude_titles = _phrases(get("NOTION_EXCLUDE_TITLES", ",".join(DEFAULT_EXCLUDE_TITLES)))
    exclude_ids = {norm_id(i) for i in get("NOTION_EXCLUDE_IDS", "").split(",") if norm_id(i)}
    for bad in [i for i in exclude_ids if len(i) != 32]:
        raise ConfigError("NOTION_EXCLUDE_IDS holds %r, not a Notion id" % bad)
    scan = get("NOTION_SECRET_SCAN", "")
    if scan.strip().lower() in ("off", "none"):
        scan = ""
    elif scan:
        scan = str(Path(scan).expanduser())
        if not os.access(scan, os.X_OK):
            raise ConfigError("NOTION_SECRET_SCAN is not an executable: %s" % scan)
    elif bin_dir and os.access(str(Path(bin_dir) / SCANNER_REL), os.X_OK):
        scan = str(Path(bin_dir) / SCANNER_REL)
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
        exclude_titles=exclude_titles,
        exclude_ids=exclude_ids,
        secret_scan=scan,
    )
