#!/bin/bash
# Sovereign connector, Claude Code, the WRITE wire.
#
# Mirrors Claude Code's distilled memory into this machine's lane: every project's
# memory folder (~/.claude/projects/<key>/memory/) lands under memory/<key>/, so
# nothing a session learned stays behind on one machine. Never the transcripts
# (*.jsonl): cold-storage material, not brain material.
#
# Destination and config: see _lib/mirror-common.sh (pointer files, staging rule).
# Failures return nonzero and preserve the previous published capture; diagnostics go to stderr,
# which the launchd job routes to a log (StandardErrorPath is mandatory).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="claude-code-$BRAIN_HOST_RESOLVED"
sov_prepare "$LANE" "claude-code" || exit 1
mkdir -p "$DEST/memory" || { echo "mirror: cannot create $DEST" >&2; exit 1; }

ok=0; failed=0; lines=()
for m in "$HOME"/.claude/projects/*/memory; do
  [ -d "$m" ] || continue
  [ -n "$(find "$m" -type f -name '*.md' -print -quit 2>/dev/null)" ] || continue
  key="$(basename "$(dirname "$m")")"
  mkdir -p "$DEST/memory/$key"
  if rsync -a "${SOV_EXCL[@]}" "$m/" "$DEST/memory/$key/"; then
    ok=$((ok+1)); lines+=("- \`$key\`")
  else
    failed=$((failed+1)); echo "mirror: rsync failed for $key" >&2
  fi
done

sov_manifest "$DEST/memory" "$LANE" "Claude Code memory mirror manifest" "$ok" "$failed" \
  "Each folder under \`memory/\` is one Claude Code project; the folder name is the" \
  "project's working directory as Claude Code encodes it (slashes become dashes)." "" ${lines[@]+"${lines[@]}"}
# the lane-level heartbeat the health check and sov status read
cp "$DEST/memory/MANIFEST.md" "$DEST/MANIFEST.md"
sov_finish "Claude Code memory mirror"
exit $?
