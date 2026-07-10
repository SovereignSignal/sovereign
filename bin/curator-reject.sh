#!/usr/bin/env bash
#
# curator-reject.sh <proposal> [reason...]
#
# Reject a curator proposal: move it to the lane's rejected/ archive (non-destructive,
# never a hard delete) and log the verdict with an optional reason.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_curator-lib.sh"

arg="${1:?usage: curator-reject.sh <proposal-file-or-slug> [reason...]}"; shift || true
reason="${*:-}"
prop="$(resolve_proposal "$arg")"
[ -n "$prop" ] || { echo "proposal not found: $arg (looked in $PROPOSALS)"; exit 1; }

git_scope_preflight || exit 1
mkdir -p "$REJECTED"
base="$(basename "$prop")"
dest="$REJECTED/$base"
if [ -e "$dest" ]; then
  stem="${base%.md}"
  stamp="$(date +%Y%m%d-%H%M%S)"
  dest="$REJECTED/${stem}--rejected-${stamp}.md"
  [ ! -e "$dest" ] || { echo "rejected archive collision: $dest"; exit 1; }
fi
mv "$prop" "$dest"
log_decision rejected "$prop" "$reason"
git_commit "curator: reject $(basename "$prop")${reason:+ ($reason)}" \
  "$prop" "$dest" "$DECISIONS"
"$HERE/curator-status.sh" >/dev/null 2>&1 || true
echo "rejected: $(basename "$prop") (kept in rejected/)"
