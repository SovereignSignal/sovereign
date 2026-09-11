"""Deterministic method selectors extracted from the existing lane exporter."""
import re
from brain_redact import redact_text

FORBIDDEN = re.compile(
    r"(CREDS|\.env|/secrets?/|ACCESS\.md|token|credential|"          # credentials
    r"protonmail-env|tastytrade-env|quarantine|api-key|handoff|"
    r"brief-context|/alerts?/|cron-logs|cron-locks|cron-snapshots|"  # ephemeral
    r"rejected|link-cache|research_runs|preflight|task-backups|"
    r"map-deltas|brief-archive|brain-map|edge-ledger|macro-views|"   # the rsync's
    r"x-signals|polymarket-signals|site-publish|health-history|"
    r"positions|theses|trade-journal|consensus-tracker|"             # market calls
    r"\.log$|\.json$|\.jsonl$|\.db$|\.sqlite|\.png$|\.html$|"        # not markdown
    r"\.sh$|\.py$|\.pem$|crontab|\.venv|node_modules)", re.I)


SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*(PRIVATE|PUBLIC) KEY-----",     "key block"),
    (r"\bssh-(ed25519|rsa|dss)\s+AAAA",                  "ssh public key"),
    (r"\bghp_[A-Za-z0-9]{20,}",                          "github token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}",                  "github fine-grained pat"),
    (r"\bsk-[A-Za-z0-9_\-]{20,}",                        "openai-style key"),
    (r"\bpat[A-Za-z0-9]{10,}\.[A-Za-z0-9]{40,}",         "airtable pat"),
    (r"\bre_[A-Za-z0-9_\-]{20,}",                        "resend key"),
    (r"\bntn_[A-Za-z0-9]{20,}",                          "notion token"),
    (r"\bxox[baprs]-[A-Za-z0-9\-]{10,}",                 "slack token"),
    (r"\bAKIA[0-9A-Z]{16}\b",                            "aws access key id"),
    (r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}",                "telegram bot token"),
    (r"\beyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{15,}",   "jwt"),
    (r"\bAIza[0-9A-Za-z_\-]{30,}",                       "google api key"),
    (r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token|bearer|pat)\b"
     r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{16,}",           "assigned credential value"),
    (r"(?i)postgres(?:ql)?://[^\s:@]+:[^\s@]+@",         "database url with password"),
]


ADDRESS = re.compile(
    r"(\b(?:\d{1,3}\.){3}\d{1,3}\b"                       # IPv4
    r"|\b[0-9a-f]{1,4}(:[0-9a-f]{1,4}){4,}\b"             # IPv6
    r"|\bssh-(ed25519|rsa|dss)\b"
    r"|\b[\w.-]+\.ts\.net\b"
    r"|-----BEGIN\b"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")  # email


MONEY = re.compile(
    r"(\$\s?\d[\d,]*(\.\d+)?\s?[KkMmBb]?\b"
    r"|\b\d[\d,]*(\.\d+)?\s?[KkMmBb]?\s?(USD|USDC|USDT|DAI|ETH|BTC|UNI)\b)")


FORENSIC = re.compile(
    r"(\b(?=[0-9a-f]{7,40}\b)(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b"
    r"|(?i:\bpid\b)\s*:?\s*\d{3,}"
    r"|\b\d{9,}\b)")


def secret_hits(text):
    return sorted(set([name for pat, name in SECRET_PATTERNS if re.search(pat, text)] + redact_text(text)[1]))


def filter_lines(lines):
    """A tripped line is dropped whole, not redacted: a half-scrubbed sentence
    is worse than a missing one. The drop leaves a visible marker rather than
    closing the gap — silently splicing the neighbours produces a sentence that
    reads as complete and is not, the worst failure mode for material headed to
    a trusted layer."""
    kept, dropped = [], {"secret": 0, "address": 0, "money": 0, "forensic": 0}
    for ln in lines:
        why = None
        if secret_hits(ln):
            why = "secret"
        elif ADDRESS.search(ln):
            why = "address"
        elif MONEY.search(ln):
            why = "money"
        elif FORENSIC.search(ln):
            why = "forensic"
        if why:
            dropped[why] += 1
            indent = ln[:len(ln) - len(ln.lstrip())]
            kept.append(f"{indent}[... line withheld: {why} ...]")
            continue
        kept.append(ln)
    return kept, dropped


def _head_text(line):
    """A heading's own text: no `#`, no leading emoji or punctuation."""
    return re.sub(r"^[^\w]+", "", line.lstrip("#").strip()).strip()


def _find_heading(lines, want):
    """The heading whose OWN text starts with `want`. A substring match is not
    good enough: it would let a section name match the document title and lift
    the whole file, including what the allow-list meant to leave behind."""
    w = want.lower()
    for i, ln in enumerate(lines):
        if ln.startswith("#") and re.match(re.escape(w) + r"(?:$|[^\w])", _head_text(ln).lower()):
            return i
    return None


def x_whole(txt, _arg):
    return txt.splitlines()


def x_sections(txt, headings):
    """The body of each named heading, in the order declared. A section stops at
    the NEXT heading of any level, so it never carries its subtree along by
    accident: a subsection that belongs in the capture is declared by name."""
    lines = txt.splitlines()
    out = []
    for want in headings:
        start = _find_heading(lines, want)
        if start is None:
            continue
        out.append(f"## {_head_text(lines[start])}")
        out.append("")
        for ln in lines[start + 1:]:
            if ln.startswith("#"):
                break
            out.append(ln)
        out.append("")
    return out


def x_open_commitments(txt, _arg):
    """The unfinished entries and the settled ownership rulings.

    A completed commitment is a run record: it says what happened once, and the
    macro pipeline's history is not this lane's subject. An OPEN entry is a
    standing constraint ("do not remove X until Y"), and a CANCELLED entry is a
    boundary ruling about what this box owns. Both outlive their task.
    """
    open_items, cancelled = [], []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("- [ ]"):
            open_items.append("- " + s[5:].strip())
        elif s.startswith("- [x]") and re.search(r"\|\s*Cancelled\b", s):
            cancelled.append("- " + s[5:].strip())
    out = []
    if open_items:
        out += ["## Open constraints", "",
                "Each is a standing rule until its blocker clears.", ""]
        out += open_items + [""]
    if cancelled:
        out += ["## Settled ownership rulings", "",
                "Work deliberately dropped or handed to another lane. The ruling "
                "is the durable part.", ""]
        out += cancelled + [""]
    return out


def x_learnings(txt, areas):
    """The Summary and Suggested Action of each logged lesson in the declared
    areas, grouped by area, newest first within each.

    Details and Metadata never travel: Details is the incident (one run, one
    day, one file path) and Metadata is bookkeeping. The lesson is the pair.
    """
    wanted = [a.lower() for a in areas]
    blocks = re.split(r"^## \[LRN-", txt, flags=re.M)[1:]
    by_area = {a: [] for a in wanted}
    for b in blocks:
        m = re.search(r"^\*\*Area\*\*:\s*(.+)$", b, flags=re.M)
        area = (m.group(1).strip().lower() if m else "")
        if area not in by_area:
            continue

        def sec(name):
            mm = re.search(r"^### " + name + r"\s*\n(.*?)(?=^###|\Z)",
                           b, flags=re.M | re.S)
            return mm.group(1).strip() if mm else ""

        summary, action = sec("Summary"), sec("Suggested Action")
        if not summary:
            continue
        by_area[area].append((summary, action))

    out = []
    for area in wanted:
        items = by_area[area]
        if not items:
            continue
        out += [f"## {area}", ""]
        for summary, action in items:
            out.append(f"**{' '.join(summary.split())}**")
            if action:
                out += ["", " ".join(action.split())]
            out.append("")
    return out


EXTRACTORS = {"whole": x_whole, "sections": x_sections,
              "open-commitments": x_open_commitments, "learnings": x_learnings}
