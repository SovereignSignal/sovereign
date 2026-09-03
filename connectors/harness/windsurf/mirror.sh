#!/bin/bash
# Sovereign connector, Windsurf, the WRITE wire.
#
# Mirrors Windsurf's memories folder (~/.codeium/windsurf/memories: global rules
# plus the memories Cascade writes) into this machine's lane. The binary cascade
# state (*.pb) never crosses. Then re-applies the read instruction so a rules file
# reset by the app gets it back.
#
# Destination and config: see _lib/mirror-common.sh. Exit 0 always.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="windsurf-$BRAIN_HOST_RESOLVED"
DEST="$(sov_dest "$LANE" "windsurf")" || exit 0
SRC="$HOME/.codeium/windsurf/memories"
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 0; }

ok=0; failed=0; n=0
if [ -d "$SRC" ] && [ -n "$(find "$SRC" -type f -print -quit 2>/dev/null)" ]; then
  if rsync -a "${SOV_EXCL[@]}" --exclude='*.pb' "$SRC/" "$DEST/memories/"; then
    ok=1; n="$(find "$DEST/memories" -type f | wc -l | tr -d ' ')"
  else
    failed=1; echo "mirror: rsync failed for $SRC" >&2
  fi
fi
sov_manifest "$DEST" "$LANE" "Windsurf memories mirror manifest" "$ok" "$failed" \
  "Source: \`~/.codeium/windsurf/memories/\`. Files in the lane: $n."
/usr/bin/python3 "$HERE/../_lib/ensure-text-instruction.py" "$SRC/global_rules.md" "$HERE/INSTRUCTION.md" >> "$DEST/MANIFEST.md" 2>&1 || true
sov_git_publish "$DEST" "Windsurf memories mirror"
exit 0
