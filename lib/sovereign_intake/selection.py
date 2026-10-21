"""Deterministic method selectors extracted from the existing lane exporter."""
import re
from brain_redact import SHAPES, redact_text

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


# Detector-side shapes, (pattern, name, check). The detector is the fail-closed gate, so it
# is strict: it runs these plus every brain_redact.SHAPES pattern (with the shape's own check,
# never the redactor's glued leniency), and a token-shaped string the redactor let through
# still trips it. The boundary rule is brain_redact's: a vendor token matches wherever it
# starts, and \b stays only on the short prefixes that end ordinary words (bare sk-, pat, re_).


def _jwt_pair(value):
    """A run of the JWT alphabet with an eyJ header of 18+ (from any eyJ in a segment to its
    dot) followed by a segment of 15+. Earlier fragments in the run are skipped."""
    segs = value.split(".")
    for i in range(len(segs) - 1):
        j = segs[i].find("eyJ")
        if j >= 0 and len(segs[i]) - j >= 18 and len(segs[i + 1]) >= 15:
            return True
    return False


SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*(PRIVATE|PUBLIC) KEY-----",     "key block", None),
    (r"ssh-(ed25519|rsa|dss)\s+AAAA",                    "ssh public key", None),
    (r"ghp_[A-Za-z0-9]{20,}",                            "github token", None),
    (r"github_pat_[A-Za-z0-9_]{20,}",                    "github fine-grained pat", None),
    (r"(?:sk-(?=proj-|ant-|svcacct-)|\bsk-)[A-Za-z0-9_\-]{20,}", "openai-style key", None),
    (r"\bpat[A-Za-z0-9]{10,}\.[A-Za-z0-9]{40,}",         "airtable pat", None),
    (r"\bre_[A-Za-z0-9_\-]{20,}",                        "resend key", None),
    (r"ntn_[A-Za-z0-9]{20,}",                            "notion token", None),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}",                   "slack token", None),
    (r"A(?:KIA|SIA)[0-9A-Z]{16}(?![0-9A-Z])",            "aws access key id", None),
    (r"\d{8,10}:AA[A-Za-z0-9_\-]{30,}",                  "telegram bot token", None),
    (r"eyJ[A-Za-z0-9_.\-]*[A-Za-z0-9_\-]",               "jwt", _jwt_pair),
    (r"AIza[0-9A-Za-z_\-]{30,}",                         "google api key", None),
    (r"(?i)(?<![a-z0-9])(api[_-]?key|secret|password|passwd|access[_-]?token|bearer|pat)\b"
     r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{16,}",           "assigned credential value", None),
    (r"(?i)postgres(?:ql)?(?:\+[a-z0-9]+)?://[^\s:@/]+:(?:(?![^\s@/]{0,512}/[^\s@]{0,512}[?#])[^\s@]{1,512}|[^\s@/]+)@",
     "database url with password", None),
]
# The detector's full list: its own shapes, then every redactor shape, strict.
DETECTOR = ([(re.compile(pat), name, check) for pat, name, check in SECRET_PATTERNS]
            + [(rx, kind, check) for kind, rx, check, _glued in SHAPES])


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


def _found(rx, check, text):
    return any(check is None or check(m.group(0)) for m in rx.finditer(text))


def detector_hits(text):
    """The kinds the strict DETECTOR list finds, without redact_text's lenient judgement."""
    return sorted({name for rx, name, check in DETECTOR if _found(rx, check, text)})


def scrub_detected(text):
    """Replace every DETECTOR hit with [redacted <name>]. Returns (text, names)."""
    hits = []
    for rx, name, check in DETECTOR:
        def sub(m, name=name, check=check):
            if check is not None and not check(m.group(0)):
                return m.group(0)
            hits.append(name)
            return "[redacted " + name + "]"
        text = rx.sub(sub, text)
    return text, hits


def secret_hits(text):
    return sorted(set(detector_hits(text) + redact_text(text)[1]))


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
