"""Local product introduction and role configuration, without probes or writes."""
import json
import os
from pathlib import Path
import shlex
import socket


def state_dir():
    return Path(os.environ.get("SOV_STATE_DIR", "~/.local/state/sovereign")).expanduser()


def manifest():
    path = state_dir() / "connectors.json"
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError("Connector configuration cannot be read safely.")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Connector configuration is invalid.")
    machine = value.get("machine", {})
    if not isinstance(machine, dict) or machine.get("role") not in (None, "hub", "client") or machine.get("mode") not in (None, "contribute-only", "read-and-contribute"):
        raise ValueError("Machine role configuration is invalid.")
    if machine.get("role") == "hub" and machine.get("mode"):
        raise ValueError("Client modes apply only to clients.")
    return value


def pointer(name):
    from sovereign_config import pointer as instance_pointer
    value = instance_pointer(Path.home() / name)
    return value[:4096] if value else None


def describe():
    config = manifest()
    machine = config.get("machine", {})
    hub = pointer(".brain-hub")
    root = os.environ.get("BRAIN_ROOT") or pointer(".brain-root")
    root = str(Path(root).expanduser()) if root else None
    role = machine.get("role") or ("client" if hub else None)
    mode = machine.get("mode")
    warnings = []
    if not role:
        warnings.append("Hub or Client role has not been declared on this installation.")
    if role == "client" and not mode:
        warnings.append("Client mode has not been declared; existing connector observations remain separate.")
    if mode == "contribute-only" and root:
        warnings.append("A legacy archive pointer remains. Contribute-only migration is incomplete until access and retained copies are checked.")
    rules = str(Path(root) / "CLAUDE.md") if root and mode != "contribute-only" else None
    installed = next((str(p) for p in (Path.home() / "Applications/Sovereign.app", Path("/Applications/Sovereign.app")) if p.is_dir()), None)
    cli = Path.home() / "brain-bin/sov"
    next_commands = [shlex.quote(str(cli)) + " status --json"] if cli.exists() else []
    return {"product": "Sovereign", "description": "Your owned archive: selected work becomes reusable context through a hub and its review gate.", "roles": {"hub": "One active authority maintains the archive, imports contributions, curates and records decisions.", "client": "A connected machine contributes selected work. Read-and-contribute clients also receive trusted context."}, "machine": {"host": os.environ.get("BRAIN_HOST") or pointer(".brain-host") or socket.gethostname().split(".")[0], "role": role, "client_mode": mode, "role_basis": "declared" if machine.get("role") else "hub-pointer" if hub else "unassigned", "vault": root, "hub_pointer": hub}, "rules": rules, "installed_app": installed, "next_commands": next_commands, "warnings": warnings, "health": "Not probed. Request status separately for timestamped observations.", "writes": False, "network": False}


def read_enabled():
    # Fail closed on invalid configuration; a stale hook must not inject context.
    try:
        return manifest().get("machine", {}).get("mode") != "contribute-only"
    except (ValueError, OSError):
        return False


def bootstrap():
    info = describe()
    if info["machine"]["client_mode"] == "contribute-only":
        return ""
    candidates = [Path.home() / "brain-bin/sov"]
    if info["installed_app"]:
        candidates.append(Path(info["installed_app"]) / "Contents/MacOS/sov")
    candidates.append(Path(__file__).resolve().parents[1] / "bin/sov")
    cli = next((p for p in candidates if p.is_file()), candidates[0])
    command = shlex.quote(str(cli)) + " about --json"
    return "[Sovereign discovery] Sovereign is the installed archive system. For questions about this installation or archive, start with " + command + ". It explains this installation and safe status entry points without GUI or network access. Context below may be dated; current operational status and source timestamps govern health claims."


def main():
    import sys
    try:
        if "--help" in sys.argv or "-h" in sys.argv:
            print("Usage: sov-about [--json | --read-enabled]\nRead-only local installation information.")
            return 0
        if "--read-enabled" in sys.argv:
            return 0 if read_enabled() else 1
        value = describe()
        if "--json" in sys.argv:
            print(json.dumps(value, indent=2))
        else:
            m = value["machine"]
            print("Sovereign\n" + value["description"])
            print("Machine: " + m["host"] + " | " + (m["role"] or "role unassigned") + " | " + (m["client_mode"] or "no client mode"))
            print("Instance: " + (m["vault"] or "no local archive configured"))
            print("Rules: " + (value["rules"] or "not configured for local reading"))
            print(value["health"])
            for line in value["warnings"] + value["next_commands"]:
                print(line)
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"product": "Sovereign", "error": "Local connector configuration is unreadable or invalid.", "writes": False, "network": False}))
        return 1
