"""The rebuild kit: what only exists on the hub machine, sealed and copied off-site nightly.

Contents: hub.json, the machine pointers (~/.brain-*), the notify env files, and every
path the owner lists under kit.include. Never the recovery key, never anything under the
vault (the vault has its own copies). Sealed with hub-crypto like the recovery capsule,
so one key opens both. Targets are copied with scp (host:path) or cp (a local path); the
same run mirror-pushes the vault and the template to the offsite remotes and writes a
receipt with each target's state.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from sovereign_intake.common import atomic
from .core import crypto_tool
from .recovery import check_key

MAX_TOTAL = 64 * 1024 * 1024


def _under(p, root):
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _files(path):
    p = Path(os.path.expanduser(str(path)))
    if p.is_dir():
        return [q for q in sorted(p.rglob("*")) if q.is_file() and not q.is_symlink()]
    return [p] if p.is_file() else []


def inventory(inst, state, home):
    state = Path(state); home = Path(home); k = inst.get("kit") or {}
    key = Path(os.path.expanduser(k["key_file"])).resolve() if k.get("key_file") else None
    entries = []

    def add(name, p):
        entries.append((name, Path(p).read_bytes()))

    add("state/hub.json", state / "hub.json")
    for p in sorted(home.glob(".brain-*")):
        if p.is_file():
            add("pointers/" + p.name, p)
    for label, envp in (inst.get("notify") or {}).items():
        if envp and Path(os.path.expanduser(envp)).is_file():
            add("notify/" + Path(envp).name, os.path.expanduser(envp))
    for item in k.get("include") or []:
        base = Path(os.path.expanduser(item))
        if _under(base, inst["vault"]):
            raise ValueError("the vault has its own copies; not in the kit: " + str(base))
        for f in _files(item):
            if key and f.resolve() == key:
                raise ValueError("the recovery key never goes in the kit: " + str(f))
            if _under(f, inst["vault"]):
                raise ValueError("the vault has its own copies; not in the kit: " + str(f))
            rel = f.relative_to(base.parent) if base.is_dir() else Path(f.name)
            add("include/" + str(rel), f)
    if sum(len(r) for _, r in entries) > MAX_TOTAL:
        raise ValueError("kit exceeds %d MiB" % (MAX_TOTAL // (1024 * 1024)))
    return entries


def _seal(entries, key, out):
    with tempfile.TemporaryDirectory(prefix="sov-kit-", dir=str(Path(out).parent)) as tmp:
        plain = Path(tmp) / "kit.tar.gz"; hashes = {}
        with tarfile.open(plain, "w:gz") as tar:
            for name, raw in entries:
                h = tarfile.TarInfo(name); h.size = len(raw); h.mode = 0o600; h.mtime = int(time.time())
                tar.addfile(h, io.BytesIO(raw)); hashes[name] = hashlib.sha256(raw).hexdigest()
            payload = json.dumps({"version": 1, "hashes": hashes, "created": time.time()}, sort_keys=True).encode()
            h = tarfile.TarInfo("manifest.json"); h.size = len(payload); h.mode = 0o600; tar.addfile(h, io.BytesIO(payload))
        sealed = Path(tmp) / "sealed"
        subprocess.run([str(crypto_tool()), "seal", str(key), str(plain), str(sealed)], check=True, capture_output=True, timeout=120)
        shutil.move(str(sealed), str(out))
    return hashes


def _copy(target, capsule):
    if ":" in target:
        r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", str(capsule), target.rstrip("/") + "/" + capsule.name],
                           capture_output=True, text=True, timeout=300)
        return {"state": "copied" if r.returncode == 0 else "failed", "detail": (r.stderr or "").strip()[:200]}
    dest = Path(os.path.expanduser(target)); dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(capsule, dest / capsule.name)
    return {"state": "copied", "detail": ""}


def _prune(folder, keep, targets):
    """Keep the newest `keep` kits locally and on every target that is a local path (a
    remote target is pruned by name with a bounded rm over ssh)."""
    old = sorted(folder.glob("*.kit"))[:-keep] if keep > 0 else []
    for p in old:
        p.unlink()
    for target in targets:
        for p in old:
            if ":" in target:
                host, path = target.split(":", 1)
                subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, "rm -f -- " + json.dumps(path.rstrip("/") + "/" + p.name)],
                               capture_output=True, text=True, timeout=60)
            else:
                q = Path(os.path.expanduser(target)) / p.name
                if q.exists():
                    q.unlink()


def _mirror(repo, remote):
    r = subprocess.run(["git", "-C", str(repo), "push", "--mirror", "-q", remote], capture_output=True, text=True, timeout=600)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"state": "pushed" if r.returncode == 0 else "failed", "head": head, "detail": (r.stderr or "").strip()[:200]}


def build(inst, state, home, template, apply=False):
    state = Path(state); k = inst.get("kit") or {}; snap = (inst.get("snapshot") or {}).get("folder")
    if not snap or not k.get("key_file"):
        raise ValueError("hub.json needs snapshot.folder and kit.key_file before a kit can be built")
    key = check_key(Path(os.path.expanduser(k["key_file"])), Path(inst["vault"]))
    folder = Path(os.path.expanduser(snap)) / "hub-kit"
    entries = inventory(inst, state, home)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()); out = folder / (stamp + ".kit")
    n = 0
    while out.exists():
        n += 1; out = folder / ("%s-%d.kit" % (stamp, n))
    result = {"applied": apply, "output": str(out), "files": [name for name, _ in entries], "targets": {}, "offsite": {}}
    if not apply:
        return result
    folder.mkdir(parents=True, exist_ok=True)
    _seal(entries, key, out)
    result["sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    targets = k.get("targets") or []
    for target in targets:
        result["targets"][target] = _copy(target, out)
    _prune(folder, int(k.get("keep") or 7), targets)
    off = inst.get("offsite") or {}
    if off.get("vault"):
        result["offsite"]["vault"] = _mirror(inst["vault"], off["vault"])
    if off.get("template"):
        result["offsite"]["template"] = _mirror(template, off["template"])
    result["finished"] = time.time()
    (state / "hub").mkdir(parents=True, exist_ok=True); atomic(state / "hub" / "kit.json", result)
    failed = [t for t, r in result["targets"].items() if r["state"] != "copied"] + [n for n, r in result["offsite"].items() if r["state"] != "pushed"]
    if failed:
        raise ValueError("kit built locally but these targets failed: " + ", ".join(failed))
    return result


def restore(capsule, destination, key):
    destination = Path(destination); key = check_key(Path(os.path.expanduser(str(key))))
    if destination.exists():
        raise ValueError("restore destination exists: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sov-kit-restore-", dir=str(destination.parent)) as tmp:
        plain = Path(tmp) / "kit.tar.gz"
        subprocess.run([str(crypto_tool()), "open", str(key), str(capsule), str(plain)], check=True, capture_output=True, timeout=120)
        names = []
        with tarfile.open(plain, "r:gz") as tar:
            members = tar.getmembers()
            manifest = json.loads(tar.extractfile("manifest.json").read())
            staged = Path(tmp) / "out"; staged.mkdir()
            for m in members:
                if m.name == "manifest.json":
                    continue
                if not m.isreg() or m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise ValueError("unsafe entry in kit: " + m.name)
                raw = tar.extractfile(m).read()
                if hashlib.sha256(raw).hexdigest() != manifest["hashes"].get(m.name):
                    raise ValueError("hash mismatch in kit: " + m.name)
                p = staged / m.name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw); p.chmod(0o600); names.append(m.name)
        shutil.move(str(staged), str(destination))
    return names
