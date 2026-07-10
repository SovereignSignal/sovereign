#!/usr/bin/env bash
#
# curator-retire.sh <knowledge-file-or-slug> <reason...>
#
# Retire a trusted card after an explicit owner verdict. The card moves to
# the curator's rejected archive, preserving both Git history and a live
# audit artifact. Retirements always require a reason and never overwrite an
# existing archived card.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_curator-lib.sh"

arg="${1:?usage: curator-retire.sh <knowledge-file-or-slug> <reason...>}"; shift || true
reason="${*:-}"
[ -n "$reason" ] || { echo "REFUSED: retirement requires the owner's reason"; exit 1; }

src=""
if [ -f "$arg" ]; then
  src="$(cd "$(dirname "$arg")" && pwd)/$(basename "$arg")"
else
  slug="${arg%.md}"
  for sub in entities concepts syntheses; do
    candidate="$KNOWLEDGE/$sub/$slug.md"
    if [ -f "$candidate" ]; then
      [ -z "$src" ] || { echo "REFUSED: ambiguous knowledge slug: $slug"; exit 1; }
      src="$candidate"
    fi
  done
fi

[ -n "$src" ] || { echo "knowledge card not found: $arg"; exit 1; }
case "$src" in
  "$KNOWLEDGE"/entities/*.md|"$KNOWLEDGE"/concepts/*.md|"$KNOWLEDGE"/syntheses/*.md) ;;
  *) echo "REFUSED: retirement source is outside flat knowledge folders: $src"; exit 1 ;;
esac

errs="$(validate_note "$src")"
[ -z "$errs" ] || { echo "REFUSED, invalid trusted note:"; echo "$errs"; exit 1; }

git_scope_preflight || exit 1
mkdir -p "$REJECTED"
dest="$REJECTED/$(basename "$src")"
[ ! -e "$dest" ] || { echo "REFUSED: rejected archive already exists: $dest"; exit 1; }

mv "$src" "$dest"
log_decision retired "$src" "$reason"
if ! git_commit "curator: retire $(basename "$src") ($reason)" \
  "$src" "$dest" "$DECISIONS"; then
  echo "Warning: retirement moved and logged, but commit or push failed."
fi
"$HERE/curator-status.sh" >/dev/null 2>&1 || true
echo "retired: $(basename "$src") (kept in rejected/)"
