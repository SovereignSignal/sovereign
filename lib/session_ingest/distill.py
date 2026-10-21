"""One distillation call: a session excerpt in, at most three validated captures out.

The call goes through curator_inference.chat, which runs the sovereign-inference guard
on every request, so nothing here builds a request or opens a connection. Validation is
strict and per candidate: a bad candidate is dropped alone, and a reply with no usable
JSON object, or a model that refuses or runs out on the excerpt, is a failed attempt.
A guard refusal at call time is `refused`, its REFUSING sentence the error. Every other
fault is `unreachable`, since none of them says anything about the session: a refused
connection, a timeout, an HTTP error, and also the ValueErrors chat raises for a
response body that is not JSON or a local-only redirect it refuses.
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
_TURN = re.compile(r"T([0-9]{1,6})")
REFUSING = "REFUSING - sovereign-inference law"


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
        m = _TURN.fullmatch(e) if isinstance(e, str) else None
        if not m or int(m.group(1)) not in known:
            return None
        turn = "T%d" % int(m.group(1))
        if turn not in cited:
            cited.append(turn)
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


def _result(status, captures=(), error=None, **extra):
    out = {"status": status, "captures": list(captures), "error": error}
    out.update(extra)
    return out


def distill(res, key, session, excerpt, turn_ids, timeout=90):
    """Ask the resolved model (inference.resolve) about one excerpt. Returns
    {"status": "ok"|"failed"|"unreachable"|"refused", "captures", "error"}. An
    unreachable result also carries `responded`: True when the model host answered with
    an HTTP error (it rejected this excerpt), False when no answer came at all (an
    outage: refused connection, DNS, a timeout after the retry)."""
    cfg = res.get("cfg")
    if cfg is None:
        return _result("unreachable", error=res.get("reason") or "no model for session capture", responded=False)
    provider = cfg.get("provider")
    if provider and not key:
        # A hosted provider without its key would only fail at the provider, after the
        # excerpt had left this Mac; refuse here, before any request is built.
        name = (curator_inference.PROVIDERS.get(provider) or {}).get("name") or provider
        return _result("refused", error="No key is saved for %s." % name)
    messages = [{"role": "system", "content": prompt.SYSTEM},
                {"role": "user", "content": prompt.user_message(session, excerpt)}]
    try:
        raw = curator_inference.chat(cfg, key, cfg["model"], TEMPERATURE, messages, timeout)
    except Exception as exc:
        error = str(exc)[:300] or type(exc).__name__
        # The model refusing or running out on this excerpt is about the session; the
        # guard's refusal is its own status. Every other fault (refused connection,
        # timeout, HTTP error, refused redirect, a response body of the wrong shape) is
        # about the road to the model.
        if isinstance(exc, ValueError) and str(exc).startswith("Claude stopped"):
            return _result("failed", error=error)
        if isinstance(exc, RuntimeError) and str(exc).startswith(REFUSING):
            return _result("refused", error=str(exc))
        # curator_inference._post_json turns an HTTP error response into "HTTP <code>: ...".
        responded = isinstance(exc, RuntimeError) and str(exc).startswith("HTTP ")
        return _result("unreachable", error=error, responded=responded)
    captures = validate(raw, turn_ids)
    if captures is None:
        return _result("failed", error="the reply held no captures object")
    return _result("ok", captures)
