"""A single writer and an independent Git spool. Never fetches brain context."""
from pathlib import Path

from .collector import assess, identity, validate
from .common import IntakeError, atomic, directory, encoded, exclusive, git, json_read, locked, now, remote


def init_spool(config, name, email):
    if not name or not email or any(c in name + email for c in "\n\r\x00"):
        raise IntakeError("explicit_git_identity_required")
    spool = Path(config["spool"]).expanduser().absolute()
    directory(spool.parent, create=True)
    spool.mkdir(mode=0o700)  # Existing state is never silently adopted.
    git(spool, "init", "-b", "main")
    git(spool, "config", "--local", "user.name", name)
    git(spool, "config", "--local", "user.email", email)
    (spool / "items").mkdir(mode=0o700)
    (spool / ".git/sovereign-intake").write_text("1\n")
    return {"state": "initialized", "spool": str(spool)}


def check_spool(path):
    spool = directory(path)
    directory(spool / ".git")
    if not (spool / ".git/sovereign-intake").is_file():
        raise IntakeError("spool_not_initialized_by_contribution_tool")
    if git(spool, "rev-parse", "--show-toplevel").stdout.strip() != str(spool):
        raise IntakeError("not_independent_spool")
    if git(spool, "symbolic-ref", "--short", "HEAD").stdout.strip() != "main":
        raise IntakeError("wrong_spool_branch")
    if (spool / ".git/objects/info/alternates").exists():
        raise IntakeError("shared_object_database")
    for key in ("user.name", "user.email"):
        if not git(spool, "config", "--local", "--get", key, check=False).stdout.strip():
            raise IntakeError("explicit_local_git_identity_required")
    tracked = git(spool, "ls-files", "-z").stdout.split("\0")
    if any(p and not (p.startswith("items/") and p.count("/") == 1 and p.endswith(".json")) for p in tracked):
        raise IntakeError("unexpected_spool_files")
    return spool


def run(config, state_dir):
    state_dir = directory(state_dir, create=True)
    with locked(state_dir / "contribute.lock"):
        spool = check_spool(config["spool"])
        destination = remote(config["remote"])
        state_path = state_dir / "contribution.json"
        state = json_read(state_path, {})
        state.update(client_id=config["client_id"], role="client", client_mode="contribute-only")
        result = assess(config)
        state["collection"] = {"attempted_at": result["collected_at"], "state": "ok" if result["ok"] else "partial", "observations": result["observations"]}
        if result["ok"]:
            state["collection"]["succeeded_at"] = result["collected_at"]
        atomic(state_path, state)
        directory(spool / "items", create=True)
        try:
            for item in result["items"]:
                path = spool / "items" / (item["capture_id"] + ".json")
                if path.exists() or path.is_symlink():
                    old = validate(json_read(path), config["client_id"])
                    if identity(old) != identity(item):
                        raise IntakeError("spool_content_collision")
                else:
                    exclusive(path, encoded(item))
            # Validate every staged/untracked payload before any commit or retry.
            for path in (spool / "items").iterdir():
                if path.name.startswith(".intake-tmp-"):
                    continue  # A killed writer may leave an unpublished temporary file.
                item = validate(json_read(path), config["client_id"])
                if path.name != item["capture_id"] + ".json":
                    raise IntakeError("unexpected_spool_item")
            if any((spool / "items").glob("*.json")):
                git(spool, "add", "--", "items/*.json")
            changed = git(spool, "diff", "--cached", "--quiet", check=False)
            if changed.returncode not in (0, 1):
                raise IntakeError("spool_diff_failed")
            if changed.returncode == 1:
                git(spool, "commit", "-m", "Collect selected method contributions")
            head = git(spool, "rev-parse", "--verify", "HEAD", check=False)
            if head.returncode:
                state["delivery"] = {"state": "empty", "attempted_at": now()}
            else:
                # Always push, even if collection was unchanged or previously failed.
                state["delivery"] = {"state": "pending", "head": head.stdout.strip(), "attempted_at": now()}
                atomic(state_path, state)
                git(spool, "push", destination, "HEAD:refs/heads/main")
                observed = git(spool, "ls-remote", destination, "refs/heads/main").stdout.split()
                if not observed or observed[0] != head.stdout.strip():
                    raise IntakeError("remote_head_unconfirmed")
                state["delivery"].update(state="delivered", succeeded_at=now())
        except (IntakeError, OSError, ValueError) as exc:
            state.setdefault("delivery", {}).update(state="error", attempted_at=now(), reason=str(exc) if isinstance(exc, IntakeError) else "spool_io_failed")
            atomic(state_path, state)
            raise
        atomic(state_path, state)
        if not result["ok"]:
            raise IntakeError("collection_partial_see_status")
        return state
