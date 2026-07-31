import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .cards import CardError, bind_overlay_reference, bind_topic, load_aliases
from .evidence import EvidenceError, build_evidence
from .freshness import evaluate_freshness
from .safeio import SafetyError, read_json_private, write_json_exclusive


class CliError(RuntimeError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("invalid_arguments")


def _parser() -> Parser:
    parser = Parser(add_help=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--topic")
    mode.add_argument("--ref")
    mode.add_argument("--audit-overlay", action="store_true")
    parser.add_argument("--overlay")
    parser.add_argument("--max-sections", type=int, default=4)
    return parser


def run(argv=None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root)
    project = Path(args.project_root)
    output = Path(args.output)
    references = None
    if args.ref or args.audit_overlay:
        if not args.overlay:
            raise CliError("overlay_required")
        payload = read_json_private(Path(args.overlay), project)
        if not isinstance(payload, dict):
            raise CliError("invalid_overlay")
        references = payload.get("references")
        if not isinstance(references, dict) or not references:
            raise CliError("invalid_overlay")

    if args.audit_overlay:
        cards = [bind_overlay_reference(root, references, reference) for reference in sorted(references)]
        known_paths = {card.relative_path for card in cards}
        freshness = evaluate_freshness(
            [references[reference] for reference in sorted(references)],
            today=date.today(),
            known_paths=known_paths,
        )
        detailed = {
            "schema": 1,
            "mode": "freshness_audit",
            "reference_count": len(cards),
            "freshness": freshness,
        }
        output_meta = write_json_exclusive(output, detailed, project)
        blocked = freshness["blocking"]
        receipt = {
            "ok": not blocked,
            "mode": "freshness_audit",
            "reference_count": len(cards),
            "output_sha256": output_meta["sha256"],
            "output_bytes": output_meta["bytes"],
            "output_handle": output.name,
            "freshness_blocking": freshness["blocking"],
            "freshness_finding_count": len(freshness["findings"]),
        }
        if blocked:
            receipt["error_code"] = "blocking_freshness"
        sys.stdout.write(json.dumps(receipt, sort_keys=True) + "\n")
        return 3 if blocked else 0

    overlay_row = None
    if args.ref:
        card = bind_overlay_reference(root, references, args.ref)
        overlay_row = references.get(args.ref)
        known_paths = {
            row.get("relative_path")
            for row in references.values()
            if isinstance(row, dict) and isinstance(row.get("relative_path"), str)
        }
    else:
        aliases = load_aliases(root)
        card = bind_topic(root, args.topic, aliases)
        known_paths = {card.relative_path}
    evidence = build_evidence(
        card,
        max_sections=args.max_sections,
        overlay_metadata=overlay_row,
    )
    freshness = evaluate_freshness(
        [overlay_row] if isinstance(overlay_row, dict) else [],
        today=date.today(),
        known_paths=known_paths,
    )
    detailed = {"schema": 1, "mode": "evidence", "evidence": evidence, "freshness": freshness}
    output_meta = write_json_exclusive(output, detailed, project)
    blocked = freshness["blocking"]
    receipt = {
        "ok": not blocked,
        "mode": "evidence",
        "record_count": evidence["returned_section_count"],
        "truncated": evidence["truncated"],
        "source_sha256": evidence["content_sha256"],
        "output_sha256": output_meta["sha256"],
        "output_bytes": output_meta["bytes"],
        "output_handle": output.name,
        "freshness_blocking": freshness["blocking"],
        "freshness_finding_count": len(freshness["findings"]),
    }
    if blocked:
        receipt["error_code"] = "blocking_freshness"
    sys.stdout.write(json.dumps(receipt, sort_keys=True) + "\n")
    return 3 if blocked else 0


def main() -> int:
    try:
        return run()
    except (CardError, EvidenceError, SafetyError, CliError) as exc:
        code = str(exc) if re_safe(str(exc)) else "request_failed"
    except Exception:
        code = "internal_error"
    sys.stdout.write(json.dumps({"ok": False, "error_code": code}, sort_keys=True) + "\n")
    return 2


def re_safe(value: str) -> bool:
    return bool(value) and all(character.islower() or character.isdigit() or character == "_" for character in value)


if __name__ == "__main__":
    raise SystemExit(main())
