#!/usr/bin/env bash
#
# curator-approve.sh [--force] <proposal> [reason...]
#
# Approve a curator proposal: validate its labels, move it into the matching knowledge/
# subfolder, log the verdict with the optional reason. The law wants the WHY on every
# verdict, approvals included. Commit afterward. This is the ONLY path a proposal becomes trusted.
# Refuses to overwrite an existing knowledge note (that is an update; merge by hand or --force).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_curator-lib.sh"

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
mkdir -p "$KNOWLEDGE/$sub"
if [ -e "$dest" ] && [ "$FORCE" -ne 1 ]; then
  echo "REFUSED, knowledge/$sub/$(basename "$prop") already exists."
  echo "That is an update to an existing note, not a new one. Merge by hand, or re-run with --force to overwrite."
  exit 1
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
