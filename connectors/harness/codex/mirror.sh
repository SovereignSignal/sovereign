#!/bin/bash
# Sovereign connector, Codex CLI, the WRITE wire.
#
# Mirrors Codex's distilled memory (~/.codex/memories/, its own small git repo:
# MEMORY.md, memory_summary.md, raw_memories.md, rollout summaries) into this
# machine's lane. The working tree only, never the .git store, never session
# transcripts (~/.codex/sessions/**/*.jsonl).
#
# Destination and config: see _lib/mirror-common.sh. Exit 0 always.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"

LANE="codex-memory-$BRAIN_HOST_RESOLVED"
DEST="$(sov_dest "$LANE" "codex-memory")" || exit 0
SRC="$HOME/.codex/memories"
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 0; }

ok=0; failed=0; n=0
if [ -d "$SRC" ] && [ -n "$(find "$SRC" -type f -print -quit 2>/dev/null)" ]; then
  if rsync -a "${SOV_EXCL[@]}" "$SRC/" "$DEST/"; then
    ok=1; n="$(find "$DEST" -type f -name '*.md' | wc -l | tr -d ' ')"
  else
    failed=1; echo "mirror: rsync failed for $SRC" >&2
  fi
fi
sov_manifest "$DEST" "$LANE" "Codex memory mirror manifest" "$ok" "$failed" \
  "Source: \`~/.codex/memories/\` (working tree). Markdown files in the lane: $n."
sov_git_publish "$DEST" "Codex memory mirror"
exit 0
