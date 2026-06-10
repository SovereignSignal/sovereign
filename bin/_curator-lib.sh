#!/usr/bin/env bash
#
# _curator-lib.sh — shared helpers for the curator action scripts.
# Sourced by curator-approve.sh / curator-reject.sh / curator-status.sh.
#
# The curator (named "the Archivist" in Owner's brain) drafts candidate notes into its
# own raw lane; these scripts are the DETERMINISTIC safety layer the model never bypasses:
# validate the labels, move on approval, log every verdict, keep the trusted layer clean.
#
# Config via env:
#   SOVS_VAULT     vault root (default: current dir)
#   CURATOR_LANE   the curator's raw lane name (default: curator; Owner's brain: archivist)

VAULT="${SOVS_VAULT:-$(pwd)}"
LANE_NAME="${CURATOR_LANE:-curator}"
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
  entity) echo entities;; concept) echo concepts;; synthesis) echo syntheses;; *) echo "";; esac }

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

log_decision(){ # verdict file detail
  mkdir -p "$LANE"
  printf '%s\t%s\t%s\t%s\n' "$(ts)" "$1" "$(basename "$2")" "${3:-}" >> "$DECISIONS"
}

# commit if the vault is a git repo; try to push, warn (do not fail) if push can't run
git_commit(){ # message
  git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1 || return 0
  git -C "$VAULT" add -A >/dev/null 2>&1 || true
  git -C "$VAULT" commit -q -m "$1" >/dev/null 2>&1 || return 0
  git -C "$VAULT" push -q >/dev/null 2>&1 || echo "  (committed locally; push deferred)"
}

# resolve a proposal arg (full path, slug, or slug.md) to a file path in PROPOSALS
resolve_proposal(){ # arg -> echoes path or empty
  local a="$1"
  if [ -f "$a" ]; then echo "$a"; elif [ -f "$PROPOSALS/$a" ]; then echo "$PROPOSALS/$a";
  elif [ -f "$PROPOSALS/$a.md" ]; then echo "$PROPOSALS/$a.md"; else echo ""; fi
}
