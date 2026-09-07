#!/bin/bash
# Sovereign connector, Cursor, the WRITE wire.
#
# Mirrors Cursor's work record into this machine's lane, append-only (raw/ is
# provenance, and Cursor rotates its own agent data, so source deletions must
# not propagate):
#   1. GUI composer conversations: SQLite (state.vscdb) -> one markdown file per
#      conversation under chats/, via cursor-chat-export.py beside this script.
#      Exported because the database is the only copy and .vscdb never crosses
#      a sync layer; markdown does.
#   2. CLI agent transcripts per project (~/.cursor/projects/*/agent-transcripts).
#   3. Plans, skills, and the two config files.
#
# Destination and config: see _lib/mirror-common.sh. Failures return nonzero; prior captures are retained.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="cursor-$BRAIN_HOST_RESOLVED"
sov_prepare "$LANE" "cursor" || exit 1
SRC_CLI="$HOME/.cursor"
SRC_APP="$HOME/Library/Application Support/Cursor"
[ -d "$SRC_CLI" ] || exit 0
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 1; }
EXCL=(--exclude=.DS_Store --exclude=.env --exclude=.secrets --exclude='.*.tmp' --exclude='*.tmp')
ok=0; failed=0; lines=()

# 1. GUI chats: copy db + wal + shm together so SQLite replays the WAL and we read
#    live data without locking the running app's database.
GS="$SRC_APP/User/globalStorage"
if [ -f "$GS/state.vscdb" ]; then
  TMP=$(mktemp -d) || exit 1
  trap 'sov_cleanup' EXIT
  for ext in "" "-wal" "-shm"; do
    [ -f "$GS/state.vscdb$ext" ] && cp "$GS/state.vscdb$ext" "$TMP/state.vscdb$ext"
  done
  mkdir -p "$DEST/chats"
  if DB="$TMP/state.vscdb" OUT="$DEST/chats" /usr/bin/python3 "$HERE/cursor-chat-export.py"; then
    ok=$((ok+1)); lines+=("- chats: $(ls "$DEST/chats" | wc -l | tr -d ' ') conversations exported")
  else
    failed=$((failed+1)); echo "mirror: chat export failed" >&2
  fi
fi

# 2. CLI agent transcripts, per project
if [ -d "$SRC_CLI/projects" ]; then
  while read -r t; do
    [ -n "$(find "$t" -type f -print -quit 2>/dev/null)" ] || continue
    proj=$(basename "$(dirname "$t")")
    mkdir -p "$DEST/projects/$proj"
    if rsync -a "${EXCL[@]}" "$t/" "$DEST/projects/$proj/agent-transcripts/"; then ok=$((ok+1)); else failed=$((failed+1)); fi
  done < <(find "$SRC_CLI/projects" -maxdepth 2 -type d -name agent-transcripts 2>/dev/null)
fi

# 3. Plans, skills, config
for sub in plans skills-cursor; do
  [ -d "$SRC_CLI/$sub" ] || continue
  [ -n "$(find "$SRC_CLI/$sub" -type f -print -quit 2>/dev/null)" ] || continue
  if rsync -a "${EXCL[@]}" "$SRC_CLI/$sub/" "$DEST/$sub/"; then ok=$((ok+1)); lines+=("- $sub"); else failed=$((failed+1)); fi
done
mkdir -p "$DEST/config"
[ -f "$SRC_CLI/argv.json" ] && rsync -a "$SRC_CLI/argv.json" "$DEST/config/"
[ -f "$SRC_APP/User/settings.json" ] && rsync -a "$SRC_APP/User/settings.json" "$DEST/config/"

sov_manifest "$DEST" "$LANE" "Cursor mirror manifest" "$ok" "$failed" ${lines[@]+"${lines[@]}"}
sov_finish "Cursor mirror"
exit $?
