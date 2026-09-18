"""The instance file: what is the owner's, kept out of the template.

`hub.json` lives in the state directory. `sov hub init` writes it once (from flags, or
from the export lines of the scripts a hand-built hub already runs) and refuses to
overwrite; the owner edits it by hand after. `sov hub env` prints it as shell exports,
which is how the hub scripts read their settings without a rewrite.
"""
import json
import os
import re
import urllib.parse
from pathlib import Path

from sovereign_intake.common import atomic, json_read

FILE = "hub.json"
REQUIRED = ("vault", "lane", "model", "endpoint")
DEFAULTS = {
    "version": 1, "audit_model": None, "exclude": [], "pending_limit": 50,
    "burndown": {"since_days": 400, "max": 120, "pending_limit": 200, "keep_floor_pct": 2},
    "remotes": [], "snapshot": {"folder": None, "keep": 30},
    "notify": {"archive": None, "alerts": None},
    "kit": {"include": [], "key_file": None, "targets": [], "keep": 7, "template_publications": []},
    "offsite": {"vault": None, "template": None},
    "exchange": None, "digest_hook": None,
    "instance_jobs": {},
}
# export NAME in the scripts  ->  field in hub.json
EXPORT_FIELDS = {
    "SOVS_VAULT": "vault", "CURATOR_LANE": "lane", "CURATOR_MODEL": "model",
    "CURATOR_AUDIT_MODEL": "audit_model", "CURATOR_ENDPOINT": "endpoint", "CURATOR_EXCLUDE": "exclude",
}


def path(state_dir):
    return Path(os.path.expanduser(str(state_dir))) / FILE


def validate(inst):
    if not isinstance(inst, dict):
        raise ValueError("hub.json must be an object")
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in inst.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    for k in REQUIRED:
        if not out.get(k):
            raise ValueError("hub.json: '%s' is required" % k)
    if not out.get("audit_model"):
        out["audit_model"] = out["model"]
    url = urllib.parse.urlsplit(out["endpoint"])
    if url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("hub.json: endpoint must be loopback (sovereign inference)")
    if not isinstance(out["exclude"], list):
        raise ValueError("hub.json: exclude must be a list")
    if not isinstance(out["pending_limit"], int) or out["pending_limit"] < 1:
        raise ValueError("hub.json: pending_limit must be a positive integer")
    from .manifest import all_jobs
    all_jobs(out)                      # raises on a bad instance job
    return out


def load(state_dir):
    p = path(state_dir)
    if not p.is_file():
        raise ValueError("no hub.json at %s; run: sov hub init" % p)
    return validate(json_read(p, {}))


def write(state_dir, inst):
    p = path(state_dir)
    if p.exists():
        raise ValueError("%s exists; edit it by hand, or move it aside first" % p)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic(p, validate(inst))
    return p


def env_exports(inst):
    """Shell export lines. Names are the ones the hub scripts already read."""
    b = inst["burndown"]; s = inst["snapshot"]; n = inst["notify"]
    pairs = [
        ("SOVS_VAULT", inst["vault"]), ("CURATOR_LANE", inst["lane"]),
        ("CURATOR_MODEL", inst["model"]), ("CURATOR_AUDIT_MODEL", inst["audit_model"]),
        ("CURATOR_ENDPOINT", inst["endpoint"]), ("CURATOR_EXCLUDE", ":".join(inst["exclude"])),
        ("ARCHIVIST_PENDING_LIMIT", inst["pending_limit"]),
        ("BURNDOWN_SINCE_DAYS", b["since_days"]), ("BURNDOWN_MAX", b["max"]),
        ("BURNDOWN_PENDING_LIMIT", b["pending_limit"]), ("BURNDOWN_KEEP_FLOOR_PCT", b["keep_floor_pct"]),
        ("SOV_HUB_REMOTES", " ".join(inst["remotes"])),
        ("SOV_HUB_EXCHANGE", inst.get("exchange") or (inst["remotes"][-1] if inst["remotes"] else "")),
        ("SOV_HUB_DIGEST", inst.get("digest_hook") or ""),
        ("SOV_HUB_SNAPSHOT_DIR", s.get("folder") or ""), ("SOV_HUB_SNAPSHOT_KEEP", s.get("keep") or 30),
        ("TG_ENV_FILE", n.get("archive") or ""), ("SOV_HUB_ALERTS_ENV", n.get("alerts") or ""),
    ]
    # Always single-quoted, so the runner can parse the lines back without a shell.
    return "\n".join("export %s='%s'" % (k, str(v).replace("'", "'\\''")) for k, v in pairs) + "\n"


_EXPORT = re.compile(r'^\s*export\s+([A-Z_][A-Z0-9_]*)=(.*?)\s*$')


def from_scripts(files, home=None):
    """Read `export NAME=value` lines out of existing hub scripts. Quotes are stripped and a
    leading $HOME is expanded; nothing else is interpreted. Later files win."""
    home = home or str(Path.home())
    found = {}
    for f in files:
        for line in Path(f).read_text(errors="ignore").splitlines():
            m = _EXPORT.match(line)
            if not m or m.group(1) not in EXPORT_FIELDS:
                continue
            raw = m.group(2).strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                raw = raw[1:-1]
            raw = raw.replace("$HOME", home).replace("${HOME}", home)
            found[EXPORT_FIELDS[m.group(1)]] = raw
    if "exclude" in found:
        found["exclude"] = [x for x in found["exclude"].split(":") if x]
    return found
