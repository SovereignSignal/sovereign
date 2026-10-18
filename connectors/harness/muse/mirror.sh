#!/bin/bash
# Sovereign connector, Muse Code, the WRITE wire.
#
# Mirrors Muse's distilled memory (markdown notes under
# ${XDG_DATA_HOME:-~/.local/share}/muse/memory, one folder per scope such as
# personal/) into this machine's lane. Session transcripts live elsewhere
# (muse/sessions) and never cross: this wire only ever reads the memory tree.
# Then re-applies the read instruction to the personal memory index, which
# every Muse session loads at open.
#
# Destination and config: see _lib/mirror-common.sh. Failures return nonzero; prior captures are retained.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="muse-$BRAIN_HOST_RESOLVED"
sov_prepare "$LANE" "muse" || exit 1
SRC="${MUSE_MEMORY:-${XDG_DATA_HOME:-$HOME/.local/share}/muse/memory}"
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 1; }

ok=0; failed=0; n=0
if [ -d "$SRC" ] && [ -n "$(find "$SRC" -type f -name '*.md' -print -quit 2>/dev/null)" ]; then
  if rsync -a "${SOV_EXCL[@]}" --exclude='*.lock' --exclude='*.bak-*' "$SRC/" "$DEST/memory/"; then
    ok=1; n="$(find "$DEST/memory" -type f -name '*.md' | wc -l | tr -d ' ')"
  else
    failed=1; echo "mirror: rsync failed for $SRC" >&2
  fi
fi
sov_manifest "$DEST" "$LANE" "Muse memory mirror manifest" "$ok" "$failed" \
  "Source: \`$SRC/\` (one folder per memory scope). Markdown files in the lane: $n."
mkdir -p "$SRC/personal" || true
/usr/bin/python3 "$HERE/../_lib/ensure-text-instruction.py" "$SRC/personal/MEMORY.md" "$HERE/INSTRUCTION.md" >> "$DEST/MANIFEST.md" 2>&1 || true
sov_finish "Muse memory mirror"
exit $?
