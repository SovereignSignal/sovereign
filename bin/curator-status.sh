#!/usr/bin/env bash
#
# curator-status.sh
#
# Count pending proposals, write status.json (the file the launcher and a digest read),
# and print a short summary. No side effects beyond writing status.json.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_curator-lib.sh"
mkdir -p "$LANE"

pending=0; lines=""
if [ -d "$PROPOSALS" ]; then
  while IFS= read -r -d '' f; do
    pending=$((pending+1))
    t="$(fm_get "$f" title)"; [ -n "$t" ] || t="$(basename "$f" .md)"
    lines="${lines}  - $(basename "$f" .md): ${t}"$'\n'
  done < <(find "$PROPOSALS" -maxdepth 1 -type f -name '*.md' -print0 2>/dev/null)
fi

last_decision="$(tail -1 "$DECISIONS" 2>/dev/null | cut -f1,2 | tr '\t' ' ')"
printf '{\n  "generated_at": "%s",\n  "lane": "%s",\n  "pending": %s,\n  "last_decision": "%s"\n}\n' \
  "$(ts)" "$LANE_NAME" "$pending" "${last_decision:-none}" > "$STATUS"

echo "curator status, lane '$LANE_NAME'"
echo "  pending proposals: $pending"
[ "$pending" -gt 0 ] && printf '%s' "$lines"
echo "  last decision: ${last_decision:-none}"
echo "  wrote: ${STATUS#"$VAULT"/}"
