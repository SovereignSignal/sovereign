"""Which model may read a session excerpt on this Mac: the archive's own, or none.

The answer follows the archive, never the environment. A Mac that runs the hub uses the
hub's local model (the template hub's STATE/hub.json, or the packaged local Hub that
~/.sovereign-hub points at, which is always local-only). A client sends its work to a
hub whose model it cannot reach, so session capture stays off there. A hubless archive
uses the provider its owner chose, exactly as sov-curator does. CURATOR_ENDPOINT,
CURATOR_MODEL and CURATOR_ALLOW_REMOTE are never read; CURATOR_LOCAL_ONLY=1 is, because
it can only refuse more.

Each answer comes from the loader that owns it. sovereign_hub.core.config_path and
brain_discovery read the process HOME and SOV_STATE_DIR, so `home` and `state_dir`
must be the process's own; the tick passes exactly those. A loader that refuses its
file fails closed: the mode it was resolving, no config, and the loader's reason.
"""
from pathlib import Path

import brain_discovery
import curator_inference
from sovereign_hub import core, instance

CLIENT_REASON = ("This Mac sends its work to a hub archive. Session capture needs the archive's own "
                 "model, which runs on the hub, so it stays off here.")
GUARD_REASON = "needs a local model on this archive"


def _cfg(env, base):
    """A curator config from `base` alone, plus CURATOR_LOCAL_ONLY from `env`."""
    fixed = dict(base)
    if env.get("CURATOR_LOCAL_ONLY") == "1":
        fixed["CURATOR_LOCAL_ONLY"] = "1"
    return curator_inference.config_from_env(fixed)  # no CURATOR_ALLOW_REMOTE: always False


def _answer(mode, cfg=None, reason=""):
    distiller = ""
    if cfg is not None:
        distiller = "%s/%s" % (cfg.get("provider") or "local", cfg["model"])
    return {"mode": mode, "cfg": cfg, "reason": reason, "distiller": distiller}


def _failed(mode, exc):
    return _answer(mode, reason=str(exc)[:300] or type(exc).__name__)


def resolve(state_dir, env, home):
    """{"mode": "hub"|"client"|"hubless", "cfg", "reason", "distiller"}. cfg is a
    curator_inference config or None; distiller is "<provider or local>/<model>"."""
    if instance.path(state_dir).exists():
        try:
            inst = instance.load(state_dir)
        except Exception as exc:
            return _failed("hub", exc)
        return _answer("hub", _cfg(env, {"CURATOR_ENDPOINT": inst["endpoint"], "CURATOR_MODEL": inst["model"]}))
    if (Path(home) / ".sovereign-hub").exists():
        try:
            config = core.load(core.config_path())
        except Exception as exc:
            return _failed("hub", exc)
        return _answer("hub", _cfg(env, {"CURATOR_ENDPOINT": config["endpoint"], "CURATOR_MODEL": config["model"],
                                         "CURATOR_LOCAL_ONLY": "1"}))
    try:
        role = (brain_discovery.manifest().get("machine") or {}).get("role")
        client = role == "client" or bool(brain_discovery.pointer(".brain-hub"))
    except Exception as exc:
        return _failed("client", exc)
    if client:
        return _answer("client", reason=CLIENT_REASON)
    provider = curator_inference.chosen_provider(str(state_dir))
    return _answer("hubless", _cfg(env, {"CURATOR_PROVIDER": provider,
                                         "CURATOR_BACKEND": curator_inference.PROVIDERS[provider]["backend"]}))


def ready(res):
    """(True, "") when the resolved model may be called, else (False, why)."""
    cfg = res.get("cfg")
    if cfg is None:
        return False, res.get("reason") or "no model for session capture"
    if curator_inference.violations(cfg):
        return False, GUARD_REASON
    return True, ""


def key(res):
    """The API key for the resolved model: the owner's Keychain item for a chosen
    provider, as sov-curator reads it, and none for a local model. No CURATOR_KEY or
    CURATOR_KEYFILE from the environment is read."""
    cfg = res.get("cfg")
    if cfg is None or not cfg.get("provider"):
        return ""
    return curator_inference.load_key(cfg, {})
