#!/bin/bash
# Shared write-wire helpers for every harness mirror. Sourced, not run.
#
#   sov_dest <lane>                     -> prints the lane directory to write into:
#        $BRAIN_STAGE/raw/tools/<lane>, else ~/.vault-staging/raw/tools/<lane> if that
#        folder exists (the TCC hop on macOS), else <vault>/raw/tools/<lane>.
#        Prints nothing and returns 1 when this machine is not connected.
#   sov_manifest <dest> <lane> <title> <ok> <failed> [line...]
#        writes <dest>/MANIFEST.md: the lane heartbeat, a plain .md so every sync
#        layer carries it (dotfiles and .json do not cross Obsidian Sync).
#
# Config, all instance-level: ~/.brain-root (or $BRAIN_ROOT), ~/.brain-host (or $BRAIN_HOST).
_pointer() { [ -f "$1" ] && tr -d '\n' < "$1" || true; }
BRAIN_ROOT_RESOLVED="${BRAIN_ROOT:-$(_pointer "$HOME/.brain-root")}"
BRAIN_HOST_RESOLVED="${BRAIN_HOST:-$(_pointer "$HOME/.brain-host")}"
BRAIN_HOST_RESOLVED="${BRAIN_HOST_RESOLVED:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
SOV_EXCL=(--exclude=.DS_Store --exclude=.env --exclude=.secrets --exclude='.*.tmp' --exclude='*.tmp' --exclude='*.jsonl' --exclude='.git/')

sov_dest() {
  local lane="$1"
  if [ -n "${BRAIN_STAGE:-}" ]; then printf '%s' "$BRAIN_STAGE/raw/tools/$lane"
  elif [ -d "$HOME/.vault-staging" ]; then printf '%s' "$HOME/.vault-staging/raw/tools/$lane"
  elif [ -n "$BRAIN_ROOT_RESOLVED" ] && [ -d "$BRAIN_ROOT_RESOLVED/raw/tools" ]; then printf '%s' "$BRAIN_ROOT_RESOLVED/raw/tools/$lane"
  else echo "mirror: no destination (set ~/.brain-root, or create ~/.vault-staging)" >&2; return 1; fi
}

sov_manifest() {
  local dest="$1" lane="$2" title="$3" ok="$4" failed="$5"; shift 5
  {
    echo "---"; echo "type: capture"; echo "source: $lane"; echo "created: $(date +%F)"; echo "title: $title"; echo "---"; echo
    echo "Last run: $(date -u +%FT%TZ) on $BRAIN_HOST_RESOLVED. Items mirrored: $ok. Failed: $failed."; echo
    for l in "$@"; do echo "$l"; done
  } > "$dest/MANIFEST.md"
}
