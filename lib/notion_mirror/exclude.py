"""Subtrees the owner keeps out of the mirror by name: opt-in, off by default.

Secrets are handled by content, not by title: every rendered page and CSV passes through
brain_redact before it is written, so a credential-shaped value never lands whatever the
page is called. This module is the owner's own fence on top of that, for a subtree that
should not be backed up at all (a database of credentials, a private area): a page or
database whose title matches a phrase in NOTION_EXCLUDE_TITLES, or whose id is in
NOTION_EXCLUDE_IDS, is an excluded root. Its content is never fetched; a one-line marker
file takes its place on disk so the layout stays honest, and everything beneath it is
dropped from the walk entirely (rows of an excluded database, children of an excluded
page, and their children).

Matching is on whole words, case-insensitive: "creds" matches "Keys and Creds" and not
"credscore". Nothing is excluded until the owner names it: on a real workspace a
name-based default matched Secret Network, Team Secret and The Book of Secret Knowledge
before it matched a credential page. SUGGESTED_EXCLUDE_TITLES is the list to start
from when a workspace does keep credential pages by name.
"""
import re
from typing import Callable, Dict, List, Optional, Set

DEFAULT_EXCLUDE_TITLES: List[str] = []
SUGGESTED_EXCLUDE_TITLES = [
    "key management", "credentials", "creds", "secrets", "passwords", "api keys", "private keys", "seed phrases",
]

_SPACES = re.compile(r"\s+")


def _fold(text: str) -> str:
    return _SPACES.sub(" ", (text or "").casefold()).strip()


def title_rule(title: str, phrases: List[str]) -> Optional[str]:
    """The first phrase the title contains as whole words, or None."""
    folded = _fold(title)
    if not folded:
        return None
    for phrase in phrases:
        p = _fold(phrase)
        if p and re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", folded):
            return phrase
    return None


def marker_text(reason: str) -> str:
    """The whole content of an excluded item's file: one line, no secrets, no children."""
    return "Excluded by the Notion mirror (%s): this page and everything under it stay in Notion, unmirrored.\n" % reason


def apply_excludes(items: Dict[str, dict], phrases: List[str], ids: Set[str],
                   resolve_block: Optional[Callable[[str], str]] = None) -> Dict[str, dict]:
    """Set item["excluded"] to the reason (or "") on every item, then remove everything that
    sits under an excluded item from `items`. Returns what was removed, id -> item.
    Recomputed on every run so a phrase added or removed takes effect on the next walk."""
    for it in items.values():
        if it["id"] in ids:
            it["excluded"] = "id listed in NOTION_EXCLUDE_IDS"
        else:
            hit = title_rule(it.get("title", ""), phrases)
            it["excluded"] = 'title matched "%s"' % hit if hit else ""
    gone: Set[str] = {i for i, it in items.items() if it["excluded"]}
    dropped: Dict[str, dict] = {}
    changed = True
    while changed:
        changed = False
        for i, it in list(items.items()):
            if i in dropped:
                continue
            kind, pid = it.get("parent_kind", ""), it.get("parent_id", "")
            if kind == "block" and pid and resolve_block:
                pid = resolve_block(pid) or ""
            if pid and pid in gone:
                dropped[i] = items.pop(i)
                gone.add(i)
                changed = True
    return dropped
