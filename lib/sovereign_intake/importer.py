"""Read independent intake history without checking out client-controlled paths."""
import hashlib
import json
from pathlib import Path
import re

from .collector import validate
from .common import IntakeError, MAX_ITEM, MAX_ITEMS, atomic, directory, exclusive, git, json_read, locked, now, read_under, remote, relative, slug


def source_approved(item, sources):
    approval = sources.get(item["source_id"])
    expected = {"path": approval, "exporter_version": "1"} if isinstance(approval, str) else approval
    if expected == {"path": item["source_path"], "exporter_version": item["exporter_version"]}:
        return True
    if item["exporter_version"] != "2":
        return False
    match = re.fullmatch(r"(.+?)(?:-b([0-9]{3}))?-p([0-9]{2})", item["source_id"])
    if not match:
        return False
    base, block, part = match.groups()
    approval = sources.get(base)
    if not isinstance(approval, dict) or set(approval) != {"path", "exporter_version", "max_parts", "max_blocks"}:
        return False
    return (approval["path"] == item["source_path"] and approval["exporter_version"] == "2"
            and 1 <= int(part) <= approval["max_parts"] <= 32
            and ((block is None and approval["max_blocks"] == 0)
                 or (block is not None and 1 <= int(block) <= approval["max_blocks"] <= 50)))


def inspect_repo(repo, client_id, sources):
    head = git(repo, "rev-parse", "--verify", "FETCH_HEAD").stdout.strip()
    if not re.fullmatch(r"[a-f0-9]{40,64}", head):
        raise IntakeError("invalid_received_head")
    tree = git(repo, "ls-tree", "-r", "-z", head, binary=True).stdout.split(b"\0")
    if len(tree) > MAX_ITEMS + 1:
        raise IntakeError("intake_item_limit")
    accepted, rejected = [], []
    for entry in filter(None, tree):
        key = hashlib.sha256(entry).hexdigest()
        try:
            meta, name = entry.split(b"\t", 1)
            mode, kind, oid = meta.decode("ascii").split()
            name = name.decode("utf-8")
            if mode != "100644" or kind != "blob" or not re.fullmatch(r"items/[a-f0-9]{64}\.json", name):
                raise IntakeError("unexpected_path_or_type")
            size = int(git(repo, "cat-file", "-s", oid).stdout)
            if size > MAX_ITEM:
                raise IntakeError("intake_item_too_large")
            raw = git(repo, "cat-file", "blob", oid, binary=True).stdout
            item = validate(json.loads(raw), client_id)
            if name != "items/" + item["capture_id"] + ".json":
                raise IntakeError("item_filename_mismatch")
            if not source_approved(item, sources):
                raise IntakeError("source_not_allowed_by_hub")
            accepted.append(item)
        except (IntakeError, ValueError, UnicodeError, KeyError, TypeError) as exc:
            rejected.append({"item": key, "reason": str(exc) if isinstance(exc, IntakeError) else "malformed_item"})
    return head, accepted, rejected


def note(item):
    labels = {"type": "capture", "source": "client:" + item["client_id"] + "/" + item["source_path"], "created": item["collected_at"][:10], "title": item["title"], "topics": item["topics"], "client_id": item["client_id"], "source_id": item["source_id"], "capture_id": item["capture_id"], "source_observed_at": item["source_observed_at"], "collected_at": item["collected_at"], "exporter_version": item["exporter_version"]}
    # JSON scalar quoting is also valid YAML and cannot inject frontmatter fields.
    return ("---\n" + "".join(k + ": " + json.dumps(v, ensure_ascii=False) + "\n" for k, v in labels.items()) + "---\n\n" + item["body"]).encode()


def import_client(config, state_dir, root, apply=False, receive_only=False):
    client_id = slug(config["client_id"])
    lane_id = slug(config["lane"])
    sources = {}
    for key, value in config["sources"].items():
        if isinstance(value, str):
            sources[slug(key)] = str(relative(value))
        elif isinstance(value, dict) and value.get("exporter_version") == "2":
            if set(value) not in ({"path", "exporter_version"}, {"path", "exporter_version", "max_parts", "max_blocks"}):
                raise IntakeError("invalid_source_approval")
            if "max_parts" in value and (type(value["max_parts"]) is not int or type(value["max_blocks"]) is not int or not 1 <= value["max_parts"] <= 32 or not 0 <= value["max_blocks"] <= 50):
                raise IntakeError("invalid_source_approval_bounds")
            sources[slug(key)] = dict(value, path=str(relative(value["path"])))
        else:
            raise IntakeError("invalid_source_approval")
    if not sources:
        raise IntakeError("hub_source_allowlist_required")
    if not apply:
        return {"state": "dry-run", "client_id": client_id, "lane": "raw/workspaces/" + lane_id, "sources": sources, "action": "receive-only" if receive_only else "receive-and-import", "writes": False, "network": False}
    root = directory(root)
    lane = directory(root / "raw" / "workspaces" / lane_id)
    # Owner-written contract must pre-exist; clients never author it.
    read_under(lane, "LANE.md", 65536)
    state_dir = directory(state_dir, create=True)
    with locked(state_dir / ("intake-" + client_id + ".lock")):
        cache = state_dir / "intake-repos" / client_id
        if not cache.exists():
            directory(cache, create=True)
            git(cache, "init", "--bare", "-b", "main")
        directory(cache)
        if git(cache, "rev-parse", "--is-bare-repository").stdout.strip() != "true" or (cache / "objects/info/alternates").exists():
            raise IntakeError("intake_cache_must_be_independent_bare_repo")
        state_path = state_dir / ("intake-" + client_id + ".json")
        state = json_read(state_path, {})
        if state.get("archive_root") and state["archive_root"] != str(root):
            raise IntakeError("receipt_belongs_to_another_archive")
        records = state.setdefault("records", {})
        state.update(client_id=client_id, role="client", client_mode="contribute-only", lane=lane_id, archive_root=str(root), attempted_at=now())
        try:
            git(cache, "fetch", "--no-tags", remote(config["remote"]), "refs/heads/main", timeout=45)
            head, items, rejected = inspect_repo(cache, client_id, sources)
            state.pop("reason", None)
            state.update(head=head, received_at=now(), rejections=rejected, received=len(items), state="received")
            # Record receipt before materialization, retaining imported history separately.
            atomic(state_path, state)
            imported = 0
            for item in items:
                cid = item["capture_id"]
                rec = records.setdefault(cid, {"source_id": item["source_id"], "received_at": state["received_at"], "collected_at": item["collected_at"], "source_observed_at": item["source_observed_at"]})
                if receive_only:
                    continue
                name = item["source_id"] + "-" + cid + ".md"
                body = note(item)
                if (lane / name).exists() or (lane / name).is_symlink():
                    current, _ = read_under(lane, name, MAX_ITEM)
                    if current != body:
                        raise IntakeError("existing_capture_changed")
                else:
                    exclusive(lane / name, body)
                rec.setdefault("imported_at", now())
                rec["path"] = "raw/workspaces/" + lane_id + "/" + name
                imported += 1
                atomic(state_path, state)  # Crash recovery matches bytes before acknowledging.
            state.update(state="rejected" if rejected else "received" if receive_only else "imported", imported_current=imported, promotion="not-evaluated")
            imported_times = [r["imported_at"] for r in records.values() if r.get("imported_at")]
            state["imported_at"] = max(imported_times) if imported_times else None
            state["collected_at"] = max((i["collected_at"] for i in items), default=None)
            # A deleted intake file never deletes historical hub captures or receipts.
        except (IntakeError, OSError, ValueError) as exc:
            state.update(state="error", reason=str(exc) if isinstance(exc, IntakeError) else "intake_io_failed")
            atomic(state_path, state)
            raise
        atomic(state_path, state)
        if state["rejections"]:
            raise IntakeError("intake_rejections_see_status")
        return {k: v for k, v in state.items() if k != "records"}
