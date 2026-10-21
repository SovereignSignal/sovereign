"""Model-free pre-filter: which quiet sessions are worth one distiller call.

The default answer is no. A session must come from an interactive CLI, carry no
sidechain lines, hold enough typed prompts, have run after capture was enabled, and
show signal: a score of min_score or more, or any explicit memory phrase. Points come
from the human's typed prompts only, one per turn per category, plus at most one for a
new name (a capitalised term, not sentence-initial, with no matching card under
knowledge/). Phrase lists are generic English; an instance extends them in its config.
"""
import datetime
import os
import re

DEFAULT_PHRASES = {
    "memory": ("remember", "from now on", "always", "never again", "note that"),
    "decision": ("let's go with", "decided", "switch to"),
    "correction": ("that's wrong", "actually", "not what I asked"),
}
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
# A capitalised word with at least one lowercase letter: excludes "I" and acronyms.
_NAME = re.compile(r"\b[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?:;]\s+|\n\s*)$")


def quiet(size, mtime, row, now, quiet_min):
    """Untouched for quiet_min minutes and, when a row exists, the size it recorded."""
    if now - mtime < quiet_min * 60:
        return False
    return row is None or row.get("size") == size


def card_stems(vault):
    """Lowercased filename stems of every card under knowledge/, links skipped."""
    stems = set()
    for folder, dirs, files in os.walk(os.path.join(str(vault), "knowledge")):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(folder, d))]
        for name in files:
            if name.endswith(".md") and not os.path.islink(os.path.join(folder, name)):
                stems.add(name[:-3].lower())
    return stems


def _patterns(cfg):
    extra = cfg.get("phrases") or {}
    out = {}
    for category, defaults in DEFAULT_PHRASES.items():
        phrases = list(defaults) + [p for p in extra.get(category, ()) if p not in defaults]
        out[category] = re.compile(
            "|".join(r"(?<!\w)%s(?!\w)" % re.escape(p.translate(_APOSTROPHES)) for p in phrases),
            re.IGNORECASE)
    return out


def _epoch(ts):
    if not isinstance(ts, str) or not ts:
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when.timestamp()


def _new_name(text, known):
    for m in _NAME.finditer(text):
        if _SENTENCE_START.search(text[:m.start()]):
            continue
        word = m.group(0).lower()
        if any(word == stem or word in stem.split("-") for stem in known):
            continue
        return True
    return False


def check(s, cfg, floor_epoch, card_stems):
    """(verdict or None, score, hit_turns) for one scanned session. A verdict is a skip
    reason, or the privacy gate's answer when scan() stopped; None means distil it.
    A None floor means capture was never enabled, so nothing is after it."""
    nothing = frozenset()
    if s.get("stopped"):
        return s["stopped"], 0, nothing
    if s.get("entrypoint") not in cfg.get("entrypoints", ["cli"]):
        return "skipped:entrypoint", 0, nothing
    if s.get("sidechain"):
        return "skipped:sidechain", 0, nothing
    turns = s.get("turns") or []
    if len(turns) < cfg.get("min_prompts", 3):
        return "skipped:few-prompts", 0, nothing
    last = _epoch(s.get("last_ts"))
    if floor_epoch is None or last is None or last <= floor_epoch:
        return "skipped:before-enable", 0, nothing

    patterns = _patterns(cfg)
    known = {str(x).lower() for x in card_stems or ()}
    score, memory, hits, named = 0, False, set(), False
    for turn in turns:
        text = (turn.get("prompt") or "").translate(_APOSTROPHES)
        for category, pattern in patterns.items():
            if pattern.search(text):
                score += 1
                hits.add(turn["n"])
                memory = memory or category == "memory"
        if not named and _new_name(text, known):
            named = True
            score += 1
            hits.add(turn["n"])
    if score < cfg.get("min_score", 2) and not memory:
        return "skipped:low-signal", score, frozenset(hits)
    return None, score, frozenset(hits)
