import re
from typing import Any, Dict, List, Tuple

import yaml

from .cards import BoundCard


class EvidenceError(RuntimeError):
    """A stable, sanitizable evidence failure."""


def _frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise EvidenceError("invalid_frontmatter")
    try:
        metadata = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise EvidenceError("invalid_frontmatter") from exc
    if not isinstance(metadata, dict):
        raise EvidenceError("invalid_frontmatter")
    return metadata, text[end + 5 :]


def _value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def _anchor(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return value or "section"


def _sections(body: str) -> List[Tuple[str, str]]:
    lines = body.splitlines()
    if lines and re.match(r"^#\s+", lines[0]):
        lines = lines[1:]
    sections: List[Tuple[str, List[str]]] = []
    current_title = "Overview"
    current_lines: List[str] = []
    for line in lines:
        match = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if match:
            text = "\n".join(current_lines).strip()
            if text:
                sections.append((current_title, current_lines))
            current_title = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    text = "\n".join(current_lines).strip()
    if text:
        sections.append((current_title, current_lines))
    return [(title, "\n".join(content).strip()) for title, content in sections]


def build_evidence(
    card: BoundCard,
    max_sections: int = 4,
    overlay_metadata: Dict[str, Any] = None,
) -> Dict[str, Any]:
    if max_sections < 1:
        raise EvidenceError("invalid_section_limit")
    metadata, body = _frontmatter(card.text)
    if overlay_metadata:
        metadata = dict(metadata)
        for field in (
            "status",
            "as_of",
            "verified_at",
            "freshness_class",
            "confidence",
            "source",
            "conflicts",
        ):
            if field in overlay_metadata:
                metadata[field] = overlay_metadata[field]
    sections = _sections(body)
    if not sections:
        raise EvidenceError("zero_records")
    records = []
    seen = {}
    for title, text in sections[:max_sections]:
        base = _anchor(title)
        seen[base] = seen.get(base, 0) + 1
        anchor = base if seen[base] == 1 else f"{base}-{seen[base]}"
        records.append(
            {
                "section": title,
                "anchor": anchor,
                "text": text,
                "status": _value(metadata.get("status", "unknown")),
                "as_of": _value(metadata.get("as_of")),
                "verified_at": _value(metadata.get("verified_at")),
                "freshness_class": _value(metadata.get("freshness_class")),
                "confidence": _value(metadata.get("confidence")),
                "source": _value(metadata.get("source")),
                "conflicts": _value(metadata.get("conflicts", [])),
                "relative_path": card.relative_path,
                "content_sha256": card.content_sha256,
            }
        )
    return {
        "topic": card.slug,
        "relative_path": card.relative_path,
        "content_sha256": card.content_sha256,
        "total_section_count": len(sections),
        "returned_section_count": len(records),
        "truncated": len(records) < len(sections),
        "records": records,
    }
