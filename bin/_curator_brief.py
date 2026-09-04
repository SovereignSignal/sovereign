"""Per-document judge briefs: show the judge only the cards that could touch this source.

Why this exists. The judge's system prompt used to carry every knowledge slug (591 and
growing) plus every topic the owner ever rejected at the gate (538). That is ~13k tokens
of "here is everything that already exists, do not duplicate it, and here is everything
we said no to" in front of every single document. Measured 2026-09-03 on the hub: the
keep rate fell from 50% (July) to 3% (September), and re-judging skipped documents with
the same rules but without those two lists flipped 3 of 14 to keep, two of them clearly
right, at 22s a call instead of 92s. The lists were not making the judge precise; they
were making it timid, and slow.

The two lists still do a job: the slug list is how the judge links to existing cards and
recognises an update instead of drafting a near-duplicate, and the rejected list stops
re-proposing what the owner already refused. So they are not removed, they are targeted:
for each document, only the slugs and rejected topics whose words actually appear in the
text are shown, capped small. Everything else in the brief (rules, taste, exemplars, the
answer shape) is unchanged and shared.

Deterministic, no model calls, pure functions, so a harness can compare briefs offline.
"""

import glob
import io
import math
import os
import re

# Words that carry no subject. Kept short on purpose: an over-eager stoplist starts
# deleting the very tokens (fund, grant, vote) that distinguish this owner's cards.
STOP = frozenset("""
a an and are as at be by for from has have in into is it its of on or that the this to
was were will with what when where which who why how not no yes all any each more most
new one two via per over under about after before between during than then there here
""".split())

_WORD = re.compile(r"[a-z0-9][a-z0-9+.]*")


def tokens(text):
    """Lowercase word set of a text, minus stopwords and 1-2 letter fragments."""
    out = set()
    for w in _WORD.findall((text or "").lower()):
        w = w.strip(".")
        if len(w) >= 3 and w not in STOP:
            out.add(w)
    return out


def _frontmatter_title(path):
    try:
        with io.open(path, encoding="utf-8", errors="ignore") as f:
            head = f.read(1500)
    except OSError:
        return ""
    if not head.startswith("---"):
        return ""
    end = head.find("\n---", 3)
    m = re.search(r"^title:\s*(.+)$", head[3:end if end != -1 else len(head)], re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def card_terms(knowledge_dir):
    """{slug: term set} for every card under knowledge/. Terms are the slug's own words
    plus the frontmatter title's words, so a card named `ens-meta-gov-working-group`
    with title "ENS Meta-Governance Working Group, Term 7" matches a document that says
    either. Built once per run; ~600 cards read 1.5KB each."""
    terms = {}
    for p in glob.glob(os.path.join(knowledge_dir, "**", "*.md"), recursive=True):
        slug = os.path.basename(p)[:-3]
        t = set(w for w in slug.lower().split("-") if len(w) >= 3 and w not in STOP)
        t |= tokens(_frontmatter_title(p))
        if t:
            terms[slug] = t
    return terms


def rank(doc_tokens, text_lower, terms, n):
    """The n slugs most likely to be the same subject as the document.

    A slug whose full kebab form appears literally in the text (a wikilink, a path,
    the owner naming it) always wins. Otherwise score by how much of the CARD's own
    vocabulary the document covers, not the reverse: a long document mentions
    thousands of words, a card's identity is five. Ties break toward more hits."""
    scored = []
    for slug, tset in terms.items():
        if not tset:
            continue
        literal = slug in text_lower
        hit = len(doc_tokens & tset)
        if not literal and hit == 0:
            continue
        coverage = hit / len(tset)
        # a single shared common-ish word is noise; ask for either two hits or half
        # of the card's identity, unless the slug itself is written out in the text
        if not literal and hit < 2 and coverage < 0.5:
            continue
        score = (2.0 if literal else 0.0) + coverage + 0.05 * hit
        scored.append((score, hit, slug))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [s for _, _, s in scored[:n]]


def targeted_index(text, terms, n=30):
    """Slugs to show this document as 'already exists; link or update'."""
    return rank(tokens(text), (text or "").lower(), terms, n)


def targeted_rejected(text, rejected_slugs, n=15):
    """Rejected topics adjacent to this document. Same matching, built from the slug
    words alone (rejected proposals are not cards, so there is no title to read)."""
    terms = {}
    for slug in rejected_slugs:
        t = set(w for w in slug.lower().split("-") if len(w) >= 3 and w not in STOP)
        if t:
            terms[slug] = t
    return rank(tokens(text), (text or "").lower(), terms, n)


def index_clause(slugs):
    """The sentence the judge sees. Empty list = say so, so the model does not assume
    an empty archive and start inventing links."""
    if not slugs:
        return ("Existing knowledge slugs adjacent to this source (link with [[slug]]; never "
                "duplicate): none found by search, so treat this subject as new to the archive "
                "and do not invent [[links]]. ")
    return ("Existing knowledge slugs adjacent to this source (link with [[slug]]; never "
            "duplicate; if this item is within or beside one of these, set update_of to it "
            "or skip): " + ", ".join(slugs) + ". ")


def rejected_clause(slugs):
    if not slugs:
        return ""
    return ("Topics the OWNER HAS REJECTED at the gate that are adjacent to this source — do "
            "NOT propose these again unless the source holds materially NEW facts beyond what "
            "was rejected (then set update_of to a real card slug, or state the new facts in "
            "reason): " + ", ".join(slugs) + ". ")


if __name__ == "__main__":  # tiny self-check, no vault needed
    T = {"ens-meta-gov-working-group": {"ens", "meta", "gov", "working", "group"},
         "cardano-foundation": {"cardano", "foundation"},
         "polymarket-bot": {"polymarket", "bot"}}
    doc = "Notes from the ENS meta-governance working group call on Term 7 budgets."
    got = targeted_index(doc, T)
    assert got == ["ens-meta-gov-working-group"], got
    assert targeted_index("unrelated text about weather", T) == []
    assert "cardano-foundation" in targeted_index("see [[cardano-foundation]]", T)
    print("ok")
