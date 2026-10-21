"""Which model may read a session excerpt on this Mac: the archive's own, or none.

The answer follows the archive, never the environment. A Mac that runs the hub uses the
hub's local model (the template hub's STATE/hub.json, or the packaged local Hub that
~/.sovereign-hub points at); both are loopback by law, so both are local-only. Every
mode's call takes no proxy and follows no redirect (strict_wire). A client sends its work to a hub whose model it
cannot reach, so session capture stays off there. A hubless archive uses the provider
its owner chose, exactly as sov-curator does, and needs that provider's key saved in
the Keychain. CURATOR_ENDPOINT, CURATOR_MODEL, CURATOR_ALLOW_REMOTE, CURATOR_KEY and
CURATOR_KEYFILE are never read; CURATOR_LOCAL_ONLY=1 is, because it can only refuse more.

Where to look is read once, from the process: Path.home() and state.state_dir(), the
same HOME and SOV_STATE_DIR that sovereign_hub.core.config_path and brain_discovery
read, so no argument can point one check somewhere the others do not look. Each answer
comes from the loader that owns it, and a loader that refuses its file fails closed:
the mode it was resolving, no config, and the loader's reason.
"""
from pathlib import Path
import subprocess

import brain_discovery
import curator_inference
from sovereign_hub import core, instance

from . import state

CLIENT_REASON = ("This Mac sends its work to a hub archive. Session capture needs the archive's own "
                 "model, which runs on the hub, so it stays off here.")
GUARD_REASON = "needs a local model on this archive"
NO_HOST_REASON = ("Session capture cannot use %s until it has a fixed API host. Pick another provider "
                  "in Settings \u203a Curator, or leave capture off.")
NO_KEY_REASON = "No key is saved for %s. Add one in Settings \u203a Curator."


def _cfg(env, base):
    """A curator config from `base` alone, plus CURATOR_LOCAL_ONLY from `env`. Every
    session call, in every mode, is strict on the wire (no proxy from the environment or
    the system, no redirect) and makes one attempt: a timeout is retried by a later tick."""
    fixed = dict(base)
    if env.get("CURATOR_LOCAL_ONLY") == "1":
        fixed["CURATOR_LOCAL_ONLY"] = "1"
    cfg = curator_inference.config_from_env(fixed)  # no CURATOR_ALLOW_REMOTE: always False
    cfg.update(strict_wire=True, no_retry=True)
    return cfg


def _answer(mode, cfg=None, reason=""):
    distiller = ""
    if cfg is not None:
        distiller = "%s/%s" % (cfg.get("provider") or "local", cfg["model"])
    return {"mode": mode, "cfg": cfg, "reason": reason, "distiller": distiller}


def _failed(mode, exc):
    return _answer(mode, reason=str(exc)[:300] or type(exc).__name__)


def resolve(env):
    """{"mode": "hub"|"client"|"hubless", "cfg", "reason", "distiller"}. cfg is a
    curator_inference config or None; distiller is "<provider or local>/<model>".
    `env` is read for CURATOR_LOCAL_ONLY alone."""
    home, state_dir = Path.home(), state.state_dir()
    if instance.path(state_dir).exists():
        try:
            inst = instance.load(state_dir)
        except Exception as exc:
            return _failed("hub", exc)
        return _answer("hub", _cfg(env, {"CURATOR_ENDPOINT": inst["endpoint"], "CURATOR_MODEL": inst["model"],
                                         "CURATOR_LOCAL_ONLY": "1"}))
    if (home / ".sovereign-hub").exists():
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
    spec = curator_inference.PROVIDERS[provider]
    if not spec["endpoint"]:
        return _answer("hubless", reason=NO_HOST_REASON % spec["name"])
    return _answer("hubless", _cfg(env, {"CURATOR_PROVIDER": provider, "CURATOR_BACKEND": spec["backend"]}))


def ready(res, probe=False):
    """(True, "") when the resolved model may be called, else (False, why). With
    probe=True a chosen provider's key is only checked for, by has_key(), never read:
    for status and the dry plan, which Settings polls. --on and the tick read it."""
    cfg = res.get("cfg")
    if cfg is None:
        return False, res.get("reason") or "no model for session capture"
    if curator_inference.violations(cfg):
        return False, GUARD_REASON
    if cfg.get("provider") and not (has_key(res) if probe else key(res)):
        return False, NO_KEY_REASON % curator_inference.PROVIDERS[cfg["provider"]]["name"]
    return True, ""


def has_key(res):
    """Whether the owner's Keychain item for the resolved provider exists. An attribute
    lookup, `security find-generic-password -s <service>` without -w, as sov-curator's
    key_saved() does: it neither asks for the secret nor prompts. True for a local model."""
    cfg = res.get("cfg")
    if cfg is None or not cfg.get("provider"):
        return True
    try:
        return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", cfg["keychain_service"]],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def key(res):
    """The API key for the resolved model: the owner's Keychain item for a chosen
    provider, as sov-curator reads it, and none for a local model. No CURATOR_KEY or
    CURATOR_KEYFILE from the environment is read."""
    cfg = res.get("cfg")
    if cfg is None or not cfg.get("provider"):
        return ""
    return curator_inference.load_key(cfg, {})
