#!/bin/bash
# Sovereign connector, Hermes agent, the WRITE wire.
#
# Mirrors Hermes' built-in memory (~/.hermes/memories: MEMORY.md and USER.md, the
# distilled cross-session record) into this machine's lane. Sessions live in a
# SQLite store and are transcripts, so they never cross; SOUL.md is persona config,
# not knowledge, and stays where it is.
#
# Destination and config: see _lib/mirror-common.sh. Exit 0 always.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="hermes-$BRAIN_HOST_RESOLVED"
DEST="$(sov_dest "$LANE" "hermes")" || exit 0
SRC="${HERMES_HOME:-$HOME/.hermes}/memories"
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 0; }

ok=0; failed=0; n=0
if [ -d "$SRC" ] && [ -n "$(find "$SRC" -maxdepth 1 -name '*.md' -print -quit 2>/dev/null)" ]; then
  if rsync -a "${SOV_EXCL[@]}" --include='*.md' --exclude='*' "$SRC/" "$DEST/memories/"; then
    ok=1; n="$(find "$DEST/memories" -type f -name '*.md' | wc -l | tr -d ' ')"
  else
    failed=1; echo "mirror: rsync failed for $SRC" >&2
  fi
fi
sov_manifest "$DEST" "$LANE" "Hermes memory mirror manifest" "$ok" "$failed" \
  "Source: \`~/.hermes/memories/\` (MEMORY.md, USER.md). Markdown files in the lane: $n."
sov_git_publish "$DEST" "Hermes memory mirror"
exit 0
