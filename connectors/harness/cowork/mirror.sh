#!/bin/bash
# Sovereign connector, Cowork (Claude Desktop local agent mode), the WRITE wire.
#
# Mirrors each Cowork project's memory folder into this machine's lane, one
# folder per project space. Empty memory folders are skipped (syncing empty
# folders causes push/delete loops downstream); dot-prefixed space names lose
# the dot, since hidden folders never cross a sync layer.
#
# Destination and config: see _lib/mirror-common.sh. Exit 0 always.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="cowork-$BRAIN_HOST_RESOLVED"
DEST="$(sov_dest "$LANE")" || exit 0
SRC="${COWORK_SESSIONS:-$HOME/Library/Application Support/Claude/local-agent-mode-sessions}"
[ -d "$SRC" ] || exit 0
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 0; }

ok=0; failed=0; lines=()
while read -r m; do
  [ -n "$(find "$m" -type f -not -name '.DS_Store' -print -quit 2>/dev/null)" ] || continue
  space=$(basename "$(dirname "$m")"); space="${space#.}"
  if rsync -a --delete --max-delete=50 --exclude='.DS_Store' --exclude='*.tmp' "$m/" "$DEST/$space/"; then
    ok=$((ok+1)); lines+=("- \`$space\`")
  else
    failed=$((failed+1)); echo "mirror: rsync failed for $space" >&2
  fi
done < <(find "$SRC" -type d -name memory 2>/dev/null)

sov_manifest "$DEST" "$LANE" "Cowork memory mirror manifest" "$ok" "$failed" \
  "Each folder is one Cowork project space's memory." "" ${lines[@]+"${lines[@]}"}
# the read wire: every space carries the Sovereign instruction, new spaces included
/usr/bin/python3 "$HERE/ensure-instruction.py" >> "$DEST/MANIFEST.md" 2>&1 || true
exit 0
