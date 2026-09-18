#!/bin/bash
# Connector: Claude Desktop (Cowork) project memory -> the archive's loading dock.
# One-way. Machine-scoped lane. Secrets never travel (memory dirs hold only md).
# Set BRAIN_ROOT and MACHINE, test once by hand, then schedule every ~15 min.

BRAIN_ROOT="${BRAIN_ROOT:-${SOVEREIGN_ROOT:-${SOVEREIGN_VAULT:-$HOME/brain}}}"          # path to your archive vault
MACHINE="${MACHINE:-$(hostname -s | tr 'A-Z' 'a-z')}"
SRC="$HOME/Library/Application Support/Claude/local-agent-mode-sessions"
DST="$BRAIN_ROOT/raw/tools/cowork-$MACHINE"

[ -d "$SRC" ] || exit 0
mkdir -p "$DST"
find "$SRC" -type d -name memory 2>/dev/null | while read -r m; do
  # never mirror empty dirs: file sync deletes empty folders, rsync recreates them - an endless loop
  [ -n "$(find "$m" -type f -not -name '.DS_Store' -print -quit 2>/dev/null)" ] || continue
  space=$(basename "$(dirname "$m")")
  space="${space#.}"    # dot-dirs are invisible to most file-sync layers
  rsync -a --delete --max-delete=50 --exclude='.DS_Store' --exclude='*.tmp' "$m/" "$DST/$space/"
done
