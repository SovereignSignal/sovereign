"""Pure assessment and deterministic payloads; no logging, network or writes."""
import datetime
import json

from .common import IntakeError, MAX_BODY, MAX_ITEM, MAX_SOURCE, digest, encoded, read_under, relative, slug, stamp, now
from .selection import EXTRACTORS, FORBIDDEN, ADDRESS, MONEY, FORENSIC, filter_lines, secret_hits

KEYS = {"schema_version", "exporter_version", "client_id", "source_id", "source_path", "title", "topics", "body", "source_observed_at", "collected_at", "capture_id"}


def identity(item):
    return {k: item[k] for k in sorted(KEYS - {"source_observed_at", "collected_at", "capture_id"})}


def validate(item, client_id):
    if not isinstance(item, dict) or set(item) != KEYS:
        raise IntakeError("invalid_item_fields")
    if item["schema_version"] != 1 or item["exporter_version"] not in ("1", "2"):
        raise IntakeError("unsupported_item_version")
    if slug(item["client_id"]) != slug(client_id):
        raise IntakeError("wrong_client")
    slug(item["source_id"])
    p = str(relative(item["source_path"]))
    from .evidence import permitted
    if (item["exporter_version"] == "1" and (not p.endswith(".md") or FORBIDDEN.search(p))) or (item["exporter_version"] == "2" and not permitted(p)):
        raise IntakeError("forbidden_source")
    if not isinstance(item["title"], str) or not 1 <= len(item["title"]) <= 200 or any(ord(c) < 32 for c in item["title"]):
        raise IntakeError("invalid_title")
    if not isinstance(item["topics"], list) or len(item["topics"]) > 20:
        raise IntakeError("invalid_topics")
    for topic in item["topics"]:
        slug(topic)
    body = item["body"]
    if not isinstance(body, str) or not body.strip() or len(body.encode()) > MAX_BODY or "\x00" in body:
        raise IntakeError("invalid_body")
    stamp(item["source_observed_at"])
    stamp(item["collected_at"])
    # Scan descriptive fields as well as the body. Digests and timestamps are metadata.
    content = json.dumps({k: item[k] for k in ("source_path", "title", "topics", "body")})
    if secret_hits(content):
        raise IntakeError("credential_shaped_content")
    if item["exporter_version"] == "1" and (ADDRESS.search(body) or MONEY.search(body) or FORENSIC.search(body)):
        raise IntakeError("method_boundary_failed")
    if item["capture_id"] != digest(identity(item)) or len(encoded(item)) > MAX_ITEM:
        raise IntakeError("invalid_capture_digest_or_size")
    return item


def assess(config):
    client_id = slug(config["client_id"])
    selectors = config["selectors"]
    if not isinstance(selectors, list) or not 1 <= len(selectors) <= 100:
        raise IntakeError("invalid_selectors")
    ids = [slug(s["id"]) for s in selectors]
    if len(set(ids)) != len(ids):
        raise IntakeError("duplicate_source_id")
    items, observations = [], []
    collected = now()
    for selector in selectors:
        observation = {"source_id": selector["id"], "state": "error"}
        observations.append(observation)
        try:
            path = str(relative(selector["path"]))
            if not path.endswith(".md") or FORBIDDEN.search(path):
                raise IntakeError("forbidden_source")
            how = selector["extractor"]
            if how not in EXTRACTORS:
                raise IntakeError("unknown_extractor")
            argument = selector.get("argument")
            if how in ("sections", "learnings") and (not isinstance(argument, list) or not argument or any(not isinstance(a, str) or not a for a in argument)):
                raise IntakeError("invalid_selector_argument")
            raw, info = read_under(config["source_root"], path, MAX_SOURCE)
            selected = EXTRACTORS[how](raw.decode("utf-8"), argument)
            if not selected or not any(line.strip() for line in selected):
                observation.update(state="empty", reason="no_selected_content")
                continue
            kept, dropped = filter_lines(selected)
            body = "\n".join(kept).strip() + "\n"
            truncated = len(body.encode()) > MAX_BODY
            if truncated:
                body = body.encode()[:MAX_BODY - 100].decode("utf-8", errors="ignore").rsplit("\n", 1)[0] + "\n\n[Capture truncated; remaining content stays at the source.]\n"
            item = dict(schema_version=1, exporter_version="1", client_id=client_id, source_id=selector["id"], source_path=path, title=selector["title"], topics=selector.get("topics", []), body=body, source_observed_at=datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat(), collected_at=collected)
            item["capture_id"] = digest(identity(item))
            validate(item, client_id)
            items.append(item)
            observation.update(state="selected", capture_id=item["capture_id"], bytes=len(body.encode()), dropped=dropped, truncated=truncated)
        except FileNotFoundError:
            observation["reason"] = "source_missing"
        except (IntakeError, OSError, UnicodeError, KeyError, TypeError) as exc:
            observation["reason"] = str(exc) if isinstance(exc, IntakeError) else "source_unreadable_or_invalid"
    if config.get("evidence_selectors"):
        from .evidence import assess_evidence
        extra, checks = assess_evidence(config, collected, validate, identity, digest)
        items.extend(extra)
        observations.extend(checks)
    return {"collected_at": collected, "items": items, "observations": observations, "ok": all(o["state"] != "error" for o in observations)}
