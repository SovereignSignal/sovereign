"""Credentials never enter the archive: recognise them by shape in any text and redact them.

The archive is plain text under git, mirrored off-machine and synced to every device. A
secret that lands in a lane is copied everywhere before anyone reads it, so the fence
sits at the write boundary: every producer runs its output through redact_text (or the
sov-redact command over its lane) before the bytes exist in the vault. The vault's
own commit-time scan remains the check behind it.

What is recognised: the fixed-shape credentials (vendor API keys, cloud and VCS tokens,
private key blocks, bot tokens, JWTs, passwords inside connection URLs), plus a value
that follows a credential label (api key: ..., password = ...) when it looks like one:
long, mixed character classes, not a hex address, not a URL, not a placeholder. Prose,
contract addresses, hashes and ordinary words pass through untouched. A miss is
possible (a short plain-word password has no shape); a wrong hit costs one value in a
backup, so the rules lean towards catching.

A token is recognised by its own shape, never by what precedes it. A key pasted onto a
word, a path, a URL or a bot endpoint (`bot<id>:<secret>`) has no word boundary in front,
so a fixed vendor prefix with a fixed-alphabet body matches wherever it starts; the body's
alphabet stops the match at the first separator. A leading boundary stays only where the
prefix is short enough to end ordinary words and the body is ordinary text: bare `sk-`
(task-, risk-, desk-), Stripe's `sk_`/`rk_` (snake_case test names), SendGrid's `SG.`
(MSG.member chains) and Firecrawl's `fc-` plus hex (hex-joined ids). A match glued onto a
word character must also look like a key (a 20-character run, mixed classes, a digit), so
`laughs_LoudlyAtTheEnd...` is not a `ghs_` token; an AWS id must not sit inside a longer
uppercase run. Every open-ended body that a later part must follow is capped, so a long
run of a prefix costs linear time. Credential labels count after an underscore, so
`DB_PASSWORD=` and `OPENAI_API_KEY=` are labels.

Each hit becomes `[redacted <kind>]`. Idempotent: redacted text has no shapes left.
"""
import os
import re
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

REDACTED = "[redacted %s]"

_ALNUM_RUN = re.compile(r"[A-Za-z0-9]{20,}")


def _keylike(value: str) -> bool:
    """A key has a long run without separators and mixes cases or digits. A slug does not:
    "sk-hynix-q2-memory-demand-2026" is SK hynix in a macro brief, not a credential."""
    if not _ALNUM_RUN.search(value):
        return False
    classes = sum(1 for test in (str.islower, str.isupper, str.isdigit) if any(test(c) for c in value))
    return classes >= 2


def _glued_keylike(value: str) -> bool:
    """A token glued onto a word has no boundary to vouch for it, so it must look random:
    a camelCase or snake_case identifier ending in a vendor prefix has no digit."""
    return _keylike(value) and any(c.isdigit() for c in value)


def shape_accepts(m: "re.Match[str]", check: Optional[Callable[[str], bool]], glued_check: bool) -> bool:
    """Whether a shape match is a credential. Shared with sovereign_intake.selection."""
    value = m.group(0)
    if check is not None and not check(value):
        return False
    if glued_check and m.start() > 0:
        before = m.string[m.start() - 1]
        if (before.isalnum() or before == "_") and not _glued_keylike(value):
            return False
    return True


# (kind, pattern, check, glued_check). Fixed-alphabet runs, never "prefix plus anything", so
# ordinary prose and identifiers do not trip them; a check, when given, judges the match itself.
# No leading \b unless the module docstring names the shape: a glued token is still a token,
# and glued_check makes a glued match prove it looks random (shape_accepts).
# sovereign_intake.selection.SECRET_PATTERNS mirrors these prefixes; change both together.
SHAPES: List[Tuple[str, "re.Pattern[str]", Optional[Callable[[str], bool]], bool]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:(?!-----BEGIN )[\s\S])*?-----END [A-Z ]*PRIVATE KEY-----"), None, False),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[^\n]{0,256}(?:\n[A-Za-z0-9+/=]+)+"), None, False),
    ("api key", re.compile(r"(?:sk-(?:proj-|ant-(?:api\d\d-)?|svcacct-)|\bsk-(?:or-)?)[A-Za-z0-9_-]{24,}"), _keylike, True),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), None, True),
    ("github token", re.compile(r"github_pat_[A-Za-z0-9_]{40,}"), None, True),
    ("gitlab token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}"), None, True),
    ("aws key", re.compile(r"(?<![0-9A-Z])A(?:KIA|SIA)[0-9A-Z]{16}(?![0-9A-Z])"), None, False),
    ("slack token", re.compile(r"xox[baprse]-[0-9A-Za-z]{8,}-[0-9A-Za-z-]{8,}"), None, True),
    ("google key", re.compile(r"AIza[0-9A-Za-z_-]{35}"), None, True),
    ("oauth secret", re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"), None, True),
    ("notion token", re.compile(r"(?:ntn|secret)_[A-Za-z0-9]{40,}"), None, True),
    ("stripe key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{20,}"), None, False),
    ("sendgrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"), None, False),
    ("xai key", re.compile(r"xai-[A-Za-z0-9]{40,}"), None, True),
    ("perplexity key", re.compile(r"pplx-[A-Za-z0-9]{40,}"), None, True),
    ("huggingface token", re.compile(r"hf_[A-Za-z0-9]{34,}"), None, True),
    ("firecrawl key", re.compile(r"\bfc-[a-f0-9]{32}\b"), None, False),
    ("telegram bot token", re.compile(r"[0-9]{8,10}:AA[A-Za-z0-9_-]{33}"), None, True),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,2048}\.eyJ[A-Za-z0-9_-]{10,8192}\.[A-Za-z0-9_-]{10,}"), None, True),
]

# postgres://user:PASSWORD@host (or postgresql+psycopg2://...): only the password goes; user
# and host stay readable.
_URL_PASSWORD = re.compile(
    r"((?:postgres|postgresql|mysql|mongodb|mongodb\+srv|redis|rediss|amqp|amqps)(?:\+[a-z0-9]+)?://[A-Za-z0-9_.%-]+:)([^@\s/]{6,})(@)")

# "api key: VALUE", "password = VALUE": the value is judged by _looks_secret. "token" alone is
# not a label: in a workspace about crypto it names public things all day long. A label may
# follow an underscore (DB_PASSWORD=). The value stops at whitespace or a quote, and at an
# escaped newline or tab only when what follows ends the value too (a new NAME=, a quote,
# another backslash, whitespace, the end): "KEY=k\nROOT=%s\n" in quoted source is the value
# "k", while a password that happens to contain the two characters \n stays whole.
_LABELED = re.compile(
    r"(?i)(?<![a-z0-9])(api[ _-]?key|secret[ _-]?key|client[ _-]?secret|access[ _-]?token|auth[ _-]?token|refresh[ _-]?token|bearer|"
    r"password|passwd|passphrase|private[ _-]?key|secret)\b\s*[:=]\s*[\"'`]?((?:(?!\\[nrt](?:[A-Za-z_][A-Za-z0-9_]*=|[\"'`\\]|\s|$))[^\s\"'`,;|]){12,})")

# a value that is code, not a credential: a call, an index, a member access, a path
_CODE = re.compile(r"[()\[\]{}]|\.[A-Za-z_]|^[~./]|^(?:this|self|process|os|env|ENV|config|settings|import)\b")
_PLACEHOLDER = re.compile(r"^(?:<.*>|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|x{6,}|X{6,}|\*{6,}|\.{3,}|your[-_].*|changeme|change-me|redacted.*|\[redacted.*)$", re.I)
_HEX = re.compile(r"^(?:0x)?[0-9a-fA-F]+$")


def _looks_secret(value: str) -> bool:
    if _PLACEHOLDER.match(value) or _HEX.match(value) or _CODE.search(value):
        return False
    if "://" in value or value.startswith("www."):
        return False
    classes = sum(1 for test in (str.islower, str.isupper, str.isdigit) if any(test(c) for c in value))
    if any(not c.isalnum() for c in value):
        classes += 1
    return classes >= 3 or (classes >= 2 and len(value) >= 20)


def redact_text(text: str) -> Tuple[str, List[str]]:
    """Return (redacted text, kinds hit, one per value). Unchanged text returns ([])."""
    hits: List[str] = []

    def shape_sub(kind, check, glued_check):
        def sub(m):
            if not shape_accepts(m, check, glued_check):
                return m.group(0)
            hits.append(kind)
            return REDACTED % kind
        return sub

    for kind, pattern, check, glued_check in SHAPES:
        text = pattern.sub(shape_sub(kind, check, glued_check), text)

    def url_sub(m):
        if _PLACEHOLDER.match(m.group(2)) or m.group(2).lower() in ("password", "passwd", "pass", "secret"):
            return m.group(0)
        hits.append("password")
        return m.group(1) + (REDACTED % "password") + m.group(3)

    text = _URL_PASSWORD.sub(url_sub, text)

    def labeled_sub(m):
        value = m.group(2)
        if not _looks_secret(value):
            return m.group(0)
        hits.append(m.group(1).lower().replace("_", " ").replace("-", " "))
        return m.group(0)[: m.start(2) - m.start(0)] + (REDACTED % "value")

    text = _LABELED.sub(labeled_sub, text)
    return text, hits


TEXT_MAX = 20 * 1024 * 1024
SKIP_DIRS = {".git", ".obsidian", "node_modules", "__pycache__"}


def is_text_file(path: Path) -> bool:
    try:
        if path.stat().st_size > TEXT_MAX:
            return False
        with open(path, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return False
    return b"\x00" not in head


def redact_file(path: Path) -> List[str]:
    """Redact one file in place (atomic rewrite, only when something changed). Returns the kinds hit."""
    if not is_text_file(path):
        return []
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="surrogateescape")
    new, hits = redact_text(text)
    if hits and new != text:
        tmp = path.with_name(path.name + ".redact.part")
        tmp.write_bytes(new.encode("utf-8", errors="surrogateescape"))
        os.replace(tmp, path)
    return hits


def walk_files(root: Path) -> Iterable[Path]:
    for dirpath, dirs, files in os.walk(str(root)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield Path(dirpath) / name


def redact_paths(paths: Iterable[Path]) -> List[Tuple[Path, List[str]]]:
    """Redact every file given (directories are walked). Returns [(path, kinds)] for the files that had hits."""
    out: List[Tuple[Path, List[str]]] = []
    for p in paths:
        files = walk_files(p) if p.is_dir() else [p]
        for f in files:
            hits = redact_file(f)
            if hits:
                out.append((f, hits))
    return out
