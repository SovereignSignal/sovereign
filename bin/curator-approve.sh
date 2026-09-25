#!/usr/bin/env bash
#
# curator-approve.sh [--force] <proposal> [reason...]
#
# Approve a curator proposal: validate its labels, move it into the matching knowledge/
# subfolder, log the verdict with the optional reason. The law wants the WHY on every
# verdict, approvals included. Commit afterward. This is the ONLY path a proposal becomes trusted.
# Refuses to overwrite an existing knowledge note (that is an update; merge by hand or --force),
# UNLESS the curator itself declared this proposal a same-card update (see below).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_curator-lib.sh"

# Did the curator declare THIS proposal a replacement for the card of the same name?
#
# When a re-proposal collides with an existing card, the curator resolves it as an UPDATE:
# it judges old-vs-new and writes a MERGED body into the proposal file, recording the
# verdict in the lane sidecar proposals/.meta.json as
#   {"<slug>": {"confidence": ..., "update_of": "<slug>", "judged_at": ...}}
# Only an update_of equal to the proposal's OWN slug counts — that is the curator saying
# "this file is the merged replacement for that card". Without this, an owner-gated update
# is unlandable: the overwrite guard refuses every human approve, and only the
# auto-promote gear (which passes --force) can ever land one.
#
# No sidecar, no entry, an unreadable sidecar, a different update_of target, or no python3
# all mean "not declared" — and the overwrite guard then behaves exactly as it always has.
declared_same_slug_update(){ # meta-file slug
  [ -f "$1" ] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import json, sys
try:
    meta = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(1)
entry = meta.get(sys.argv[2]) if isinstance(meta, dict) else None
sys.exit(0 if isinstance(entry, dict) and entry.get("update_of") == sys.argv[2] else 1)' \
    "$1" "$2" 2>/dev/null
}

FORCE=0; [ "${1:-}" = "--force" ] && { FORCE=1; shift; }
arg="${1:?usage: curator-approve.sh [--force] <proposal-file-or-slug> [reason...]}"; shift || true
reason="${*:-}"
prop="$(resolve_proposal "$arg")"
[ -n "$prop" ] || { echo "proposal not found: $arg (looked in $PROPOSALS)"; exit 1; }

echo "approving $(basename "$prop")"
errs="$(validate_note "$prop")"
[ -z "$errs" ] || { echo "REFUSED, invalid candidate note:"; echo "$errs"; exit 1; }

sub="$(type_subdir "$(fm_get "$prop" type)")"
dest="$KNOWLEDGE/$sub/$(basename "$prop")"
slug="$(basename "$prop" .md)"
# A legacy alias must not land as a second card under its proposal filename.
if [ -f "$PROPOSALS/.meta.json" ]; then
  declared_target="$(python3 - "$PROPOSALS/.meta.json" "$slug" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1], encoding='utf-8'))
entry = meta.get(sys.argv[2], {})
target = entry.get('update_of')
if target is not None and not isinstance(target, str):
    raise ValueError('Invalid update target')
print(target or '')
PY
  )" || { echo "REFUSED: proposal update metadata could not be verified."; exit 1; }
  if [ -n "$declared_target" ] && [ "$declared_target" != "$slug" ]; then
    echo "REFUSED: this proposal updates $declared_target but has a different filename. Consolidate it under the target card before approval."
    exit 1
  fi
fi
mkdir -p "$KNOWLEDGE/$sub"
update_landing=0
# Cross-folder collision (2026-09-04). The same slug in ANOTHER type's folder is a
# type conflict, not an update: never land beside it, never --force over it. The
# owner picks the canonical type. Two files with one basename is ambiguous in
# Obsidian, which is how the five cross-folder pairs in the audit came to be.
for other in entities concepts syntheses; do
  [ "$other" = "$sub" ] && continue
  if [ -e "$KNOWLEDGE/$other/$(basename "$prop")" ]; then
    echo "REFUSED, knowledge/$other/$(basename "$prop") already exists with a different type."
    echo "Type conflict: this proposal is a $(fm_get "$prop" type); the existing card lives in $other/. Pick the canonical type, merge by hand, then curator-retire the other."
    exit 1
  fi
done
if [ -e "$dest" ] && [ "$FORCE" -ne 1 ]; then
  if declared_same_slug_update "$PROPOSALS/.meta.json" "$slug"; then
    update_landing=1
    echo "update landing: the curator declared this a same-card update (update_of=$slug); landing its merged body over knowledge/$sub/$(basename "$prop")."
  else
    echo "REFUSED, knowledge/$sub/$(basename "$prop") already exists."
    echo "That is an update to an existing note, not a new one. Merge by hand, or re-run with --force to overwrite."
    exit 1
  fi
fi
if [ "$update_landing" -eq 1 ]; then
  reason="update landing (declared update_of):${reason:+ $reason}"
fi

git_scope_preflight || exit 1
mv "$prop" "$dest"
log_decision approved "$prop" "knowledge/$sub/$(basename "$dest")${reason:+: $reason}"
if ! git_commit "curator: approve knowledge/$sub/$(basename "$dest")" \
  "$prop" "$dest" "$DECISIONS"; then
  echo "Warning: commit succeeded but push to origin failed (see above)."
fi
"$HERE/curator-status.sh" >/dev/null 2>&1 || true
echo "landed: knowledge/$sub/$(basename "$dest")"
