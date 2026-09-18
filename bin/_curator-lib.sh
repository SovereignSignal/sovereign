#!/usr/bin/env bash
#
# _curator-lib.sh — shared helpers for the curator action scripts.
# Sourced by curator-approve.sh / curator-reject.sh / curator-status.sh.
#
# The curator (each instance names its own; e.g. "the Archivist") drafts candidate notes into
# its own raw lane; these scripts are the DETERMINISTIC safety layer the model never bypasses:
# validate the labels, move on approval, log every verdict, keep the trusted layer clean.
#
# Config via env, with the same pointer-file fallbacks sov-load uses, so a bare
# `curator-approve <slug>` works from anywhere once the pointers exist:
#   SOVS_VAULT     vault root     (fallback: ~/.brain-root, then current dir)
#   CURATOR_LANE   curator's lane (fallback: ~/.curator-lane, then "curator")

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_sov-config.sh"
VAULT="${SOVS_VAULT:-$(_sov_pointer "$HOME/.brain-root")}"
[ -n "$VAULT" ] || VAULT="$(pwd)"
LANE_NAME="${CURATOR_LANE:-}"
[ -z "$LANE_NAME" ] && [ -f "$HOME/.curator-lane" ] && LANE_NAME="$(cat "$HOME/.curator-lane")"
[ -n "$LANE_NAME" ] || LANE_NAME="curator"
LANE="$VAULT/raw/workspaces/$LANE_NAME"
PROPOSALS="$LANE/proposals"
REJECTED="$LANE/rejected"
DECISIONS="$LANE/decisions.log"
STATUS="$LANE/status.json"
KNOWLEDGE="$VAULT/knowledge"
KNOWLEDGE_TYPES="entity concept synthesis"

ts(){ date "+%Y-%m-%dT%H:%M:%S%z"; }

# read one frontmatter key from a file (first match)
fm_get(){ # file key
  awk 'NR==1&&$0=="---"{f=1;next} f&&$0=="---"{exit} f' "$1" 2>/dev/null \
    | sed -n "s/^$2:[[:space:]]*//p" | head -1 | tr -d '\r'
}

# knowledge type -> subfolder (echoes empty if not a knowledge type)
type_subdir(){ case "$1" in
  entity) echo entities;; concept) echo concepts;; synthesis) echo syntheses;;
  # plan and review were added to Part 1 on 2026-09-04 (owner sign-off). Both are
  # writeups that pull several things together, so they live with the syntheses;
  # no new folder, and every tool that walks knowledge/ by folder keeps working.
  plan|review) echo syntheses;; *) echo "";; esac }

# validate a candidate knowledge note; prints problems to stdout; returns nonzero if invalid
validate_note(){ # file
  local f="$1" bad=0 type src created
  [ "$(head -1 "$f" 2>/dev/null)" = "---" ] || { echo "  no label block (missing frontmatter)"; return 1; }
  type=$(fm_get "$f" type); src=$(fm_get "$f" source); created=$(fm_get "$f" created)
  [ -n "$type" ] || { echo "  missing required label: type"; bad=1; }
  [ -n "$src" ]  || { echo "  missing required label: source"; bad=1; }
  if [ -n "$type" ] && [ -z "$(type_subdir "$type")" ]; then
    echo "  type '$type' is not a knowledge type ($KNOWLEDGE_TYPES)"; bad=1; fi
  if [ -n "$created" ] && ! printf '%s' "$created" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    echo "  bad created date '$created' (want YYYY-MM-DD)"; bad=1; fi
  return $bad
}

# decisions.log format (TSV, append-only): ts, verdict, file, actor, detail
# actor = CURATOR_ACTOR env ("owner-cli" when unset), so relayed batches
# (telegram-relay, qc-sweep, ...) stay distinguishable from the owner's own hand
# in the audit trail. Rows written before this column existed have 4 fields.
log_decision(){ # verdict file detail
  mkdir -p "$LANE"
  printf '%s\t%s\t%s\t%s\t%s\n' "$(ts)" "$1" "$(basename "$2")" "${CURATOR_ACTOR:-owner-cli}" "${3:-}" >> "$DECISIONS"
}

# Refuse a verdict before any move or decision-log append when the Git index
# already contains someone else's staged work. git_commit rechecks this to
# catch a race between preflight and commit.
git_scope_preflight(){
  # Plain-file archives do not require Git or macOS command-line developer tools.
  [ -e "$VAULT/.git" ] || return 0
  git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1 || return 0
  if ! git -C "$VAULT" diff --cached --quiet --; then
    echo "REFUSED: vault index already has staged changes; curator action aborted." >&2
    return 1
  fi
}

# Commit only the paths named by the caller; try to push.
#
# The vault normally has unrelated producer and Obsidian Sync churn. A bare
# `git add -A` would silently sweep that work into a curator verdict commit.
# Callers must therefore provide every path belonging to the verdict. The
# only escape hatch is explicit and intended for controlled maintenance:
# CURATOR_ALLOW_GIT_ADD_ALL=1.
# Push failures are LOUD: write to stderr AND return nonzero so the nightly
# digest surfaces them instead of silently swallowing.
git_commit(){ # message [vault-path ...]
  local message="$1"; shift || true
  # Plain-file archives do not require Git or macOS command-line developer tools.
  [ -e "$VAULT/.git" ] || return 0
  git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1 || return 0

  # Never mix a curator verdict with paths that were already staged by a
  # human or another process.
  if ! git -C "$VAULT" diff --cached --quiet --; then
    echo "  REFUSED: vault index already has staged changes; curator commit aborted." >&2
    return 1
  fi

  if [ "$#" -gt 0 ]; then
    local p rel
    local -a rels=()
    for p in "$@"; do
      case "$p" in
        "$VAULT"/*) rel="${p#"$VAULT"/}" ;;
        /*) echo "  REFUSED: scoped commit path is outside vault: $p" >&2; return 1 ;;
        *) rel="$p" ;;
      esac
      [ -n "$rel" ] || { echo "  REFUSED: empty scoped commit path" >&2; return 1; }
      case "/$rel/" in
        */../*|*/./*) echo "  REFUSED: unsafe scoped commit path: $rel" >&2; return 1 ;;
      esac
      # A freshly materialized owner-approved proposal can be untracked and
      # already moved by the time we stage. Skip that vanished source path;
      # tracked sources still stage their deletion.
      if [ -e "$VAULT/$rel" ] || git -C "$VAULT" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
        rels+=("$rel")
      fi
    done
    [ "${#rels[@]}" -gt 0 ] || {
      echo "  REFUSED: no scoped curator paths remain to stage." >&2; return 1; }
    git -C "$VAULT" add -A -- "${rels[@]}" >/dev/null 2>&1 || {
      echo "  REFUSED: failed to stage scoped curator paths." >&2; return 1; }
  elif [ "${CURATOR_ALLOW_GIT_ADD_ALL:-0}" = "1" ]; then
    git -C "$VAULT" add -A >/dev/null 2>&1 || {
      echo "  REFUSED: failed to stage vault." >&2; return 1; }
  else
    echo "  REFUSED: curator commit requires explicit paths." >&2
    return 1
  fi

  git -C "$VAULT" commit -q -m "$message" >/dev/null 2>&1 || return 0
  if ! git -C "$VAULT" push -q 2>/dev/null; then
    # count unpushed commits so the warning carries weight
    local unpushed
    unpushed=$(git -C "$VAULT" log --oneline @{u}..HEAD 2>/dev/null | wc -l | tr -d ' ')
    echo "  ⚠ PUSH FAILED: ${unpushed} commit(s) unpushed to origin. Vault is not backed up." >&2
    return 1
  fi
}

# resolve a proposal arg (full path, slug, or slug.md) to a file path in PROPOSALS
resolve_proposal(){ # arg -> echoes path or empty
  # Nightly queue first, then proposals/audit/ (the weekly audit's historicize
  # redrafts — never both at once by construction, but the nightly wins if so),
  # then vault-relative for paths pasted from a report while cd'd elsewhere.
  local a="$1"
  if [ -f "$a" ]; then echo "$a"; elif [ -f "$PROPOSALS/$a" ]; then echo "$PROPOSALS/$a";
  elif [ -f "$PROPOSALS/$a.md" ]; then echo "$PROPOSALS/$a.md";
  elif [ -f "$PROPOSALS/audit/$a" ]; then echo "$PROPOSALS/audit/$a";
  elif [ -f "$PROPOSALS/audit/$a.md" ]; then echo "$PROPOSALS/audit/$a.md";
  elif [ -f "$VAULT/$a" ]; then echo "$VAULT/$a"; else echo ""; fi
}
