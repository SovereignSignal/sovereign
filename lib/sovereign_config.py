"""Read instance pointers without migrating or writing the owner's configuration."""
import os
from pathlib import Path


def pointer(path, env=None):
    env = os.environ if env is None else env
    path = Path(os.path.expanduser(str(path)))
    name = path.name
    key = name[len(".brain-"):].upper().replace("-", "_") if name.startswith(".brain-") else None
    if key:
        legacy = env.get("BRAIN_" + key)
        if key == "ROOT":
            legacy = legacy or env.get("SOVS_VAULT")
        if legacy:
            return legacy
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = None
    if value:
        return value
    if key:
        return env.get("SOVEREIGN_" + key) or (env.get("SOVEREIGN_VAULT") if key == "ROOT" else None)
    return None
