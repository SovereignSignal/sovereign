#!/bin/bash
# Sovereign connector, Notion, the WRITE wire: one run of brain-mirror-notion.
# Delta by default; a full walk when the last one is older than six days. Exit 0 always,
# like every harness mirror: the run's own verdict is ~/.notion-mirror/last-status, and a
# failure is also one stderr line, which launchd routes to the error log.
set -uo pipefail
STATE_DIR="${NOTION_STATE_DIR:-$HOME/.notion-mirror}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/brain-bin/brain-mirror-notion"
[ -x "$BIN" ] || BIN="$HERE/../../../bin/brain-mirror-notion"
mkdir -p "$STATE_DIR"
if ! "$BIN" --state-dir "$STATE_DIR" >> "$STATE_DIR/mirror.out.log" 2>&1; then
  echo "notion mirror: run failed; see $STATE_DIR/last-status and $STATE_DIR/mirror.out.log" >&2
fi
exit 0
