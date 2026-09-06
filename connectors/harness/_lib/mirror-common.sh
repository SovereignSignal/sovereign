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

# Several connectors share one lane repo and their timers fire on the same tick, so
# their git calls collide on .git/index.lock and one loses. git has no lock of its own
# for add/commit, so take one here. mkdir is atomic on every POSIX filesystem and,
# unlike flock, exists on macOS too.
sov_git_lock() {
  local lock="$1" waited=0
  # A lock still held after 10 minutes belonged to a run that died; reclaim it.
  if [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
    echo "mirror: reclaiming a publish lock left behind by a dead run" >&2
    rmdir "$lock" 2>/dev/null
  fi
  while ! mkdir "$lock" 2>/dev/null; do
    waited=$((waited + 2))
    if [ "$waited" -ge 60 ]; then
      echo "mirror: publish lock still held after ${waited}s; skipping this tick" >&2
      return 1
    fi
    sleep 2
  done
  return 0
}

# Credentials never enter the brain. Every write wire ends in sov_git_publish, so the
# redaction pass sits at its top and covers every lane on every host without a per-lane
# line: credential-shaped values in what the mirror just wrote become [redacted <kind>]
# before the bytes are committed, relayed or synced anywhere. Same rules as
# lib/brain_redact.py; the vault's commit-time scan is the check behind it.
sov_redact() {
  local dest="$1" bin="$HOME/brain-bin/brain-redact" out n
  [ -x "$bin" ] || bin="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/bin/brain-redact"
  [ -x "$bin" ] || { echo "mirror: brain-redact not found; lane $dest written unredacted" >&2; return 0; }
  out="$("$bin" "$dest" 2>&1)" || { echo "mirror: brain-redact failed on $dest: $out" >&2; return 0; }
  n="$(printf '%s\n' "$out" | sed -n 's/^redacted: \([0-9]*\) value(s) in \([0-9]*\) file(s)$/\1 in \2/p')"
  case "$n" in ""|"0 in 0") return 0;; esac
  # Routine reporting goes to stdout: the fence working is not a job failure, and a
  # connector's stderr is read as trouble (the console counts lines there). Only the
  # two failure paths above stay on stderr.
  echo "mirror: redacted $n file(s) under $dest"
  printf '%s\n' "$out" | grep -v '^redacted: ' | sed 's/^/mirror:   /' 
  [ -f "$dest/MANIFEST.md" ] && printf '\nRedacted on this run: %s file(s); the values never entered the brain.\n' "$n" >> "$dest/MANIFEST.md"
  return 0
}

# On a git lane: commit what the mirror wrote and push the lane branch. Best effort,
# same rules as brain-capture: only the declared lane branch, never another ref.
# Never silent: a connector that cannot commit leaves the working tree dirty, and a
# dirty tree makes brain-capture abort, which stops the lane heartbeat. That failure
# has to reach the log or it costs days.
sov_git_publish() {
  local dest="$1" what="$2" gl branch cur lock rc
  sov_redact "$dest"
  gl="$(sov_git_lane_dir)" || return 0
  branch="$(grep -E "^branch:" "$gl/LANE.md" | sed -E "s/^branch:[[:space:]]*//" | tr -d " ")"
  branch="${branch:-lane/$BRAIN_LANE_RESOLVED}"
  cur="$(git -C "$BRAIN_ROOT_RESOLVED" branch --show-current 2>/dev/null)"
  if [ "$cur" != "$branch" ]; then echo "mirror: on '$cur', lane branch is '$branch'; not committing" >&2; return 0; fi
  lock="$BRAIN_ROOT_RESOLVED/.git/sov-publish.lock"
  sov_git_lock "$lock" || return 0
  sov_git_publish_locked "$dest" "$what" "$branch"; rc=$?
  rmdir "$lock" 2>/dev/null
  return $rc
}

sov_git_publish_locked() {
  local dest="$1" what="$2" branch="$3" err
  if ! err="$(git -C "$BRAIN_ROOT_RESOLVED" add -A -- "$dest" 2>&1)"; then
    echo "mirror: git add failed for $dest: $err" >&2; return 0
  fi
  if git -C "$BRAIN_ROOT_RESOLVED" diff --cached --quiet -- "$dest"; then return 0; fi
  if ! err="$(git -C "$BRAIN_ROOT_RESOLVED" commit -q -m "capture: $what $(date -u +%FT%TZ)" -- "$dest" 2>&1)"; then
    echo "mirror: commit failed for $dest: $err" >&2; return 0
  fi
  if ! err="$(git -C "$BRAIN_ROOT_RESOLVED" push -q origin "$branch" 2>&1)"; then
    echo "mirror: push of $branch failed (will retry next run): $err" >&2; return 0
  fi
  return 0
}

sov_manifest() {
  local dest="$1" lane="$2" title="$3" ok="$4" failed="$5"; shift 5
  {
    echo "---"; echo "type: capture"; echo "source: $lane"; echo "created: $(date +%F)"; echo "title: $title"; echo "---"; echo
    echo "Last run: $(date -u +%FT%TZ) on $BRAIN_HOST_RESOLVED. Items mirrored: $ok. Failed: $failed."; echo
    for l in "$@"; do echo "$l"; done
  } > "$dest/MANIFEST.md"
}
