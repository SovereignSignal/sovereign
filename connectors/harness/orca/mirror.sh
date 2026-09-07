#!/bin/bash
# Sovereign connector, Orca, the WRITE wire.
#
# Orca orchestrates other coding agents and keeps its record only in SQLite
# (orchestration.db: runs, tasks, decision gates, questions, messages). The
# database never crosses a sync layer; markdown does. This renders one capture per
# run into this machine's lane via orca-export.py beside this script. Read wire:
# none of its own; the agents Orca drives carry theirs.
#
# Destination and config: see _lib/mirror-common.sh. Failures return nonzero; prior captures are retained.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="orca-$BRAIN_HOST_RESOLVED"
sov_prepare "$LANE" "orca" || exit 1
SRC="$HOME/Library/Application Support/Orca"
[ -f "$SRC/orchestration.db" ] || exit 0
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 1; }
ok=0; failed=0; lines=()

# Copy db + wal + shm together so SQLite replays the WAL and we read live data
# without locking the running app's database.
TMP=$(mktemp -d) || exit 1
trap 'sov_cleanup' EXIT
for ext in "" "-wal" "-shm"; do
  [ -f "$SRC/orchestration.db$ext" ] && cp "$SRC/orchestration.db$ext" "$TMP/orchestration.db$ext"
done
mkdir -p "$DEST/runs"
if out=$(DB="$TMP/orchestration.db" OUT="$DEST/runs" /usr/bin/python3 "$HERE/orca-export.py" 2>&1); then
  ok=$((ok+1)); lines+=("- $out")
else
  failed=$((failed+1)); echo "mirror: export failed: $out" >&2
fi

sov_manifest "$DEST" "$LANE" "Orca mirror manifest" "$ok" "$failed" ${lines[@]+"${lines[@]}"}
sov_finish "Orca mirror"
exit $?
