from collections import Counter
from datetime import date
from typing import Any, Dict, Iterable, List, Set


WINDOWS = {"operational": 30, "active-project": 60, "relationship": 180}
ALLOWED_STATUS = {"current", "superseded", "historical"}
BLOCKING_CODES = {
    "invalid_freshness_class",
    "invalid_status",
    "invalid_as_of",
    "invalid_verified_at",
    "future_as_of",
    "future_verified_at",
    "as_of_after_verified_at",
    "missing_supersession_target",
}


def _add(findings: List[Dict[str, Any]], reference: Any, code: str) -> None:
    findings.append({"opaque_ref": reference, "code": code, "blocking": code in BLOCKING_CODES})


def _date(value: Any):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value)
    except ValueError:
        return False


def evaluate_freshness(rows: Iterable[Dict[str, Any]], today: date, known_paths: Set[str]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("enrolled") is not True:
            continue
        reference = row.get("opaque_ref")
        for field in ("as_of", "verified_at", "freshness_class"):
            if row.get(field) in (None, ""):
                _add(findings, reference, f"missing_{field}")
        as_of = _date(row.get("as_of"))
        verified = _date(row.get("verified_at"))
        if as_of is False:
            _add(findings, reference, "invalid_as_of")
        elif as_of and as_of > today:
            _add(findings, reference, "future_as_of")
        if verified is False:
            _add(findings, reference, "invalid_verified_at")
        elif verified and verified > today:
            _add(findings, reference, "future_verified_at")
        if as_of not in (None, False) and verified not in (None, False) and as_of > verified:
            _add(findings, reference, "as_of_after_verified_at")
        freshness_class = row.get("freshness_class")
        if freshness_class not in (None, "") and freshness_class not in WINDOWS:
            _add(findings, reference, "invalid_freshness_class")
        status_value = row.get("status")
        if status_value not in (None, "") and status_value not in ALLOWED_STATUS:
            _add(findings, reference, "invalid_status")
        supersedes = row.get("supersedes", [])
        if not isinstance(supersedes, list):
            _add(findings, reference, "missing_supersession_target")
        else:
            for target in supersedes:
                if not isinstance(target, str) or target not in known_paths:
                    _add(findings, reference, "missing_supersession_target")
        if (
            freshness_class in WINDOWS
            and verified not in (None, False)
            and row.get("status", "current") == "current"
            and (today - verified).days > WINDOWS[freshness_class]
        ):
            _add(findings, reference, "overdue_verification")
    counts = Counter(item["code"] for item in findings)
    return {
        "findings": findings,
        "counts": dict(sorted(counts.items())),
        "blocking": any(item["blocking"] for item in findings),
    }
