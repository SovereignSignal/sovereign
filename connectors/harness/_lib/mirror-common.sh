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

BRAIN_LANE_RESOLVED="${BRAIN_LANE:-$(_pointer "$HOME/.brain-lane")}"

# A producer box (a VM with a scoped clone and ~/.brain-lane) has one workspace lane
# on a git branch; each harness writes under <lane>/<harness>/ and the mirror commits
# and pushes it. A driver Mac has one tool lane per harness under raw/tools/.
sov_git_lane_dir() {
  [ -n "$BRAIN_LANE_RESOLVED" ] && [ -n "$BRAIN_ROOT_RESOLVED" ] || return 1
  local d="$BRAIN_ROOT_RESOLVED/raw/workspaces/$BRAIN_LANE_RESOLVED"
  [ -f "$d/LANE.md" ] && grep -qE "^write:[[:space:]]*git-branch" "$d/LANE.md" && printf '%s' "$d"
}

sov_dest() {
  local lane="$1" prefix="${2:-$1}" gl
  if gl="$(sov_git_lane_dir)"; then printf '%s' "$gl/$prefix"
  elif [ -n "${BRAIN_STAGE:-}" ]; then printf '%s' "$BRAIN_STAGE/raw/tools/$lane"
  elif [ -d "$HOME/.vault-staging" ]; then printf '%s' "$HOME/.vault-staging/raw/tools/$lane"
  elif [ -n "$BRAIN_ROOT_RESOLVED" ] && [ -d "$BRAIN_ROOT_RESOLVED/raw/tools" ]; then printf '%s' "$BRAIN_ROOT_RESOLVED/raw/tools/$lane"
  else echo "mirror: no destination (set ~/.brain-root, or create ~/.vault-staging)" >&2; return 1; fi
}

# On a git lane: commit what the mirror wrote and push the lane branch. Best effort,
# same rules as brain-capture: only the declared lane branch, never another ref.
sov_git_publish() {
  local dest="$1" what="$2" gl branch cur
  gl="$(sov_git_lane_dir)" || return 0
  branch="$(grep -E "^branch:" "$gl/LANE.md" | sed -E "s/^branch:[[:space:]]*//" | tr -d " ")"
  branch="${branch:-lane/$BRAIN_LANE_RESOLVED}"
  cur="$(git -C "$BRAIN_ROOT_RESOLVED" branch --show-current 2>/dev/null)"
  if [ "$cur" != "$branch" ]; then echo "mirror: on '$cur', lane branch is '$branch'; not committing" >&2; return 0; fi
  git -C "$BRAIN_ROOT_RESOLVED" add -A -- "$dest" 2>/dev/null || return 0
  if git -C "$BRAIN_ROOT_RESOLVED" diff --cached --quiet -- "$dest"; then return 0; fi
  git -C "$BRAIN_ROOT_RESOLVED" commit -q -m "capture: $what $(date -u +%FT%TZ)" -- "$dest" 2>/dev/null || return 0
  git -C "$BRAIN_ROOT_RESOLVED" push -q origin "$branch" 2>>/dev/stderr || echo "mirror: push of $branch failed (will retry next run)" >&2
}

sov_manifest() {
  local dest="$1" lane="$2" title="$3" ok="$4" failed="$5"; shift 5
  {
    echo "---"; echo "type: capture"; echo "source: $lane"; echo "created: $(date +%F)"; echo "title: $title"; echo "---"; echo
    echo "Last run: $(date -u +%FT%TZ) on $BRAIN_HOST_RESOLVED. Items mirrored: $ok. Failed: $failed."; echo
    for l in "$@"; do echo "$l"; done
  } > "$dest/MANIFEST.md"
}
