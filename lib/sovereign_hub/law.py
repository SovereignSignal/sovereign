"""Part 1 of the law is the standard any instance copies. When the vault's and the template's
Part 1 differ, one of them is behind; say which lines.

Rules are compared, examples are not: fenced code blocks (the label example) may carry a
archive's own values, and a heading's parenthetical aside ("copy this into any instance") is
commentary. Everything else in Part 1 must match line for line.
"""
import difflib
import re
from pathlib import Path

_START = re.compile(r"^# Part 1\b", re.M)
_END = re.compile(r"^# Part 2\b", re.M)
_HEADING_ASIDE = re.compile(r"^(#+ [^(]*?)\s*\(.*\)\s*$")


def part1(text):
    """The comparable lines of Part 1: no fenced blocks, no blank lines, headings without
    their asides. Empty string when the text has no Part 1."""
    s = _START.search(text)
    if not s:
        return ""
    e = _END.search(text, s.end())
    body = text[s.start():e.start() if e else len(text)]
    out, fenced = [], False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or not line.strip():
            continue
        out.append(_HEADING_ASIDE.sub(r"\1", line.rstrip()))
    return "\n".join(out)


def drift(vault_law, template_law):
    """Differing lines, vault as '-' and template as '+'. Empty when Part 1 matches."""
    a = part1(Path(vault_law).read_text(errors="ignore")).splitlines()
    b = part1(Path(template_law).read_text(errors="ignore")).splitlines()
    return [l for l in difflib.unified_diff(a, b, "vault", "template", lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]
