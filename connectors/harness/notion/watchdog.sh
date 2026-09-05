#!/usr/bin/env bash
# connectors/harness/notion/watchdog.sh: alert when the Notion mirror has not succeeded in MAX_AGE_H hours.
# Independent of the mirror job: the mirror cannot report its own absence.
set -uo pipefail
STATE_DIR="${NOTION_STATE_DIR:-$HOME/.notion-mirror}"
SUCCESS="$STATE_DIR/last-success"
STATUS="$STATE_DIR/last-status"
MAX_AGE_H="${NOTION_MIRROR_MAX_AGE_H:-36}"
notify() { command -v osascript >/dev/null 2>&1 && osascript -e "display notification \"$1\" with title \"Notion mirror watchdog\"" >/dev/null 2>&1 || true; }
last_status="$(cat "$STATUS" 2>/dev/null || echo "(no status file)")"
if [ ! -f "$SUCCESS" ]; then
  echo "WATCHDOG ALERT: no last-success file. status=$last_status" >&2
  notify "no successful run yet: $last_status"
  exit 1
fi
now=$(date +%s)
mtime=$(stat -c %Y "$SUCCESS" 2>/dev/null || stat -f %m "$SUCCESS")
age_h=$(( (now - mtime) / 3600 ))
if [ "$age_h" -gt "$MAX_AGE_H" ]; then
  echo "WATCHDOG ALERT: last success ${age_h}h ago (limit ${MAX_AGE_H}h). status=$last_status" >&2
  notify "STALE: last success ${age_h}h ago. $last_status"
  exit 1
fi
echo "ok: last success ${age_h}h ago"
