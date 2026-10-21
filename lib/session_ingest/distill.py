"""One distillation call: a session excerpt in, at most three validated captures out.

The call goes through curator_inference.chat, which runs the sovereign-inference guard
on every request, so nothing here builds a request or opens a connection. Validation is
strict and per candidate: a bad candidate is dropped alone, and a reply with no usable
JSON object, or a model that refuses or runs out on the excerpt, is a failed attempt.
A connection error, a timeout, an HTTP error or a guard refusal is `unreachable`, since
none of them says anything about the session.
"""
import json
import re

import curator_inference

from . import prompt

KINDS = ("decision", "preference", "correction", "fact", "entity", "howto")
CONFIDENCE = ("high", "med", "low")
MAX_CAPTURES = 3
TITLE_WORDS = 12
BODY_WORDS = 120
TEMPERATURE = 0.1
_TURN = re.compile(r"^T([0-9]{1,6})$")


def _first_object(raw):
    """The first {...} block in `raw` that parses as a JSON object, or None."""
    decoder = json.JSONDecoder()
    at = raw.find("{")
    while at != -1:
        try:
            value, _ = decoder.raw_decode(raw, at)
        except ValueError:
            value = None
        if isinstance(value, dict):
            return value
        at = raw.find("{", at + 1)
    return None


def _words(value, most):
    return isinstance(value, str) and 1 <= len(value.split()) <= most


def _candidate(c, known):
    if not isinstance(c, dict):
        return None
    title, body = c.get("title"), c.get("body")
    if not _words(title, TITLE_WORDS) or not _words(body, BODY_WORDS):
        return None
    if c.get("kind") not in KINDS or c.get("confidence") not in CONFIDENCE:
        return None
    evidence = c.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return None
    cited = []
    for e in evidence:
        m = _TURN.match(e) if isinstance(e, str) else None
        if not m or int(m.group(1)) not in known:
            return None
        if e not in cited:
            cited.append(e)
    return {"title": " ".join(title.split()), "body": body.strip(), "kind": c["kind"],
            "confidence": c["confidence"], "evidence": cited}


def validate(raw, turn_ids):
    """The valid captures in a model reply, first three kept. None when the reply holds
    no JSON object or its `captures` is not a list; [] is a valid empty answer."""
    doc = _first_object(raw) if isinstance(raw, str) else None
    if doc is None or not isinstance(doc.get("captures"), list):
        return None
    known = set(turn_ids)
    out = []
    for c in doc["captures"]:
        kept = _candidate(c, known)
        if kept is not None:
            out.append(kept)
            if len(out) == MAX_CAPTURES:
                break
    return out


def _result(status, captures=(), error=None):
    return {"status": status, "captures": list(captures), "error": error}


def distill(res, key, session, excerpt, turn_ids, timeout=90):
    """Ask the resolved model (inference.resolve) about one excerpt. Returns
    {"status": "ok"|"failed"|"unreachable", "captures", "error"}."""
    cfg = res.get("cfg")
    if cfg is None:
        return _result("unreachable", error=res.get("reason") or "no model for session capture")
    messages = [{"role": "system", "content": prompt.SYSTEM},
                {"role": "user", "content": prompt.user_message(session, excerpt)}]
    try:
        raw = curator_inference.chat(cfg, key, cfg["model"], TEMPERATURE, messages, timeout)
    except Exception as exc:
        error = str(exc)[:300] or type(exc).__name__
        # The model refusing or running out on this excerpt is about the session. Every
        # other fault (refused connection, timeout, HTTP error, guard refusal, refused
        # redirect, a response body of the wrong shape) is about the road to the model.
        if isinstance(exc, ValueError) and str(exc).startswith("Claude stopped"):
            return _result("failed", error=error)
        return _result("unreachable", error=error)
    captures = validate(raw, turn_ids)
    if captures is None:
        return _result("failed", error="the reply held no captures object")
    return _result("ok", captures)
