#!/bin/bash
# Sovereign connector, Claude Code, the WRITE wire.
#
# Syncs Claude Code's distilled memory into this machine's lane in the brain.
# Every project's memory folder (~/.claude/projects/<key>/memory/) is mirrored
# under memory/<key>/ so nothing a session learned stays behind on one machine.
# Never the transcripts (*.jsonl): those are cold-storage material, not brain
# material, and they would bloat the vault's git history without ever helping.
#
# Where it writes (in order):
#   $BRAIN_STAGE, else ~/.vault-staging/raw/tools/<lane>/ if that folder exists
#     (the TCC hop: a launchd job running bash cannot write into ~/Documents on
#     macOS, so it stages and a relay job whose program is rsync carries it in),
#   else straight into <vault>/raw/tools/<lane>/.
#
# Config, all instance-level, none of it in this file:
#   ~/.brain-root   vault path        (or $BRAIN_ROOT)
#   ~/.brain-host   short host name   (or $BRAIN_HOST; default: lowercase hostname -s)
#
# Exit 0 always. A failed sync is reported in MANIFEST.md and on stderr, which the
# launchd job routes to a log file (StandardErrorPath is mandatory, see install.sh).
set -uo pipefail

_pointer() { [ -f "$1" ] && tr -d '\n' < "$1"; }
ROOT="${BRAIN_ROOT:-$(_pointer "$HOME/.brain-root")}"
HOST="${BRAIN_HOST:-$(_pointer "$HOME/.brain-host")}"
HOST="${HOST:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
LANE="claude-code-$HOST"

if [ -n "${BRAIN_STAGE:-}" ]; then
  DEST="$BRAIN_STAGE/raw/tools/$LANE"
elif [ -d "$HOME/.vault-staging" ]; then
  DEST="$HOME/.vault-staging/raw/tools/$LANE"
elif [ -n "$ROOT" ] && [ -d "$ROOT/raw/tools" ]; then
  DEST="$ROOT/raw/tools/$LANE"
else
  echo "mirror: no destination (set ~/.brain-root, or create ~/.vault-staging)" >&2
  exit 0
fi

EXCL=(--exclude=.DS_Store --exclude=.env --exclude=.secrets --exclude='.*.tmp' --exclude='*.jsonl' --exclude='.git/')
SRC_BASE="$HOME/.claude/projects"
mkdir -p "$DEST/memory" || { echo "mirror: cannot create $DEST" >&2; exit 0; }

ok=0; failed=0; keys=()
for m in "$SRC_BASE"/*/memory; do
  [ -d "$m" ] || continue
  [ -n "$(find "$m" -type f -name '*.md' -print -quit 2>/dev/null)" ] || continue
  key="$(basename "$(dirname "$m")")"
  mkdir -p "$DEST/memory/$key"
  if rsync -a "${EXCL[@]}" "$m/" "$DEST/memory/$key/" 2>>/dev/stderr; then
    ok=$((ok+1)); keys+=("$key")
  else
    failed=$((failed+1)); echo "mirror: rsync failed for $key" >&2
  fi
done

# MANIFEST.md doubles as the lane heartbeat: a plain .md so every sync layer
# carries it (dotfiles and .json do not cross Obsidian Sync).
{
  echo "---"
  echo "type: capture"
  echo "source: $LANE"
  echo "created: $(date +%F)"
  echo "title: Claude Code memory mirror manifest"
  echo "---"
  echo
  echo "Last run: $(date -u +%FT%TZ) on $HOST. Projects mirrored: $ok. Failed: $failed."
  echo
  echo "Each folder under \`memory/\` is one Claude Code project; the folder name is"
  echo "the project's working directory as Claude Code encodes it (slashes become dashes)."
  echo
  for k in "${keys[@]}"; do echo "- \`$k\`"; done
} > "$DEST/memory/MANIFEST.md"

exit 0
