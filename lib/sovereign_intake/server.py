"""Forced SSH command for one independently initialized intake repository."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from .common import IntakeError, directory


def command(repo, name, original):
    repo = directory(repo)
    if not name or "/" in name or name.startswith("-"):
        raise IntakeError("invalid_intake_name")
    try:
        words = shlex.split(original)
    except ValueError:
        raise IntakeError("command_denied") from None
    if len(words) != 2 or words[0] not in ("git-upload-pack", "git-receive-pack") or words[1] != name:
        raise IntakeError("command_denied")
    if not (repo / "sovereign-intake").is_file() or (repo / "objects/info/alternates").exists():
        raise IntakeError("not_an_independent_intake")
    executable = shutil.which(words[0])
    if not executable:
        raise IntakeError("git_service_missing")
    return [executable, str(repo)]


def serve(repo, name):
    argv = command(repo, name, os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    # No inherited Git configuration, alternate object path, shell, or forwarding.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    os.execve(argv[0], argv, env)


HOOK = '''#!/usr/bin/env python3
import subprocess, sys
zero = "0" * 40
for line in sys.stdin:
    old, new, ref = line.split()
    if ref != "refs/heads/main" or not new.strip("0"):
        sys.exit("Only append-only main updates are accepted")
    if old.strip("0") and subprocess.run(["git", "merge-base", "--is-ancestor", old, new]).returncode:
        sys.exit("History rewrites are refused")
'''


def init(repo):
    path = Path(repo).expanduser().absolute()
    directory(path.parent, create=True)
    path.mkdir(mode=0o700)  # Refuse an existing repo, including brain-derived history.
    subprocess.run(["git", "init", "--bare", "-b", "main", str(path)], check=True, capture_output=True)
    for key in ("receive.denyNonFastForwards", "receive.denyDeletes"):
        subprocess.run(["git", "--git-dir", str(path), "config", key, "true"], check=True)
    subprocess.run(["git", "--git-dir", str(path), "config", "receive.maxInputSize", "32m"], check=True)
    subprocess.run(["git", "--git-dir", str(path), "config", "transfer.fsckObjects", "true"], check=True)
    (path / "sovereign-intake").write_text("1\n")
    hook = path / "hooks/pre-receive"
    hook.write_text(HOOK)
    hook.chmod(0o700)
    return {"state": "initialized", "repository": str(path), "ssh_access": "not-configured"}
