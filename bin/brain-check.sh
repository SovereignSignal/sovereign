#!/usr/bin/env bash
#
# brain-check.sh — verify notes carry valid labels. The spell-checker for the brain.
#
#   brain-check.sh [vault-dir]     (defaults to current dir)
#
# Severity follows the rules in CLAUDE.md:
#   - knowledge/  : the trusted layer, born clean. Every note MUST have a valid label
#                   block. Any problem is a HARD FAILURE (non-zero exit).
#   - workstreams/: the working desk. Rollout is forward-only, so unlabeled legacy notes
#                   are fine (skipped). A note that HAS labels is validated, but problems
#                   are WARNINGS, not failures — a nudge to tidy when you next touch it.
#   - raw/ archive/ repos/ .obsidian/ : not checked.
# Exit non-zero only if knowledge/ has a problem.

set -uo pipefail
VAULT="${1:-.}"
TYPES="entity concept synthesis note log capture snapshot plan review"
fail=0; warn=0; checked=0

is_type(){ for t in $TYPES; do [ "$1" = "$t" ] && return 0; done; return 1; }

report(){ # file  level(FAIL|warn)  message
  if [ "$2" = "FAIL" ]; then echo "FAIL  ${1#"$VAULT"/} — $3"; fail=$((fail+1));
  else echo "warn  ${1#"$VAULT"/} — $3"; warn=$((warn+1)); fi
}

check_file(){ # file  zone(knowledge|workstreams)
  local f="$1" zone="$2" lvl="warn"; checked=$((checked+1))
  [ "$zone" = "knowledge" ] && lvl="FAIL"
  if [ "$(head -1 "$f" 2>/dev/null)" != "---" ]; then
    [ "$zone" = "knowledge" ] && report "$f" FAIL "no label block (knowledge notes must be labeled)"
    return   # unlabeled workstreams note: legacy, allowed under forward-only rollout
  fi
  local fm type src created
  fm=$(awk 'NR==1&&$0=="---"{f=1;next} f&&$0=="---"{exit} f{print}' "$f")
  type=$(printf '%s\n' "$fm"    | sed -n 's/^type:[[:space:]]*//p'    | head -1 | tr -d '\r')
  src=$(printf '%s\n' "$fm"     | sed -n 's/^source:[[:space:]]*//p'  | head -1 | tr -d '\r')
  created=$(printf '%s\n' "$fm" | sed -n 's/^created:[[:space:]]*//p' | head -1 | tr -d '\r')
  [ -n "$type" ] || report "$f" "$lvl" "missing required label: type"
  [ -n "$src" ]  || report "$f" "$lvl" "missing required label: source"
  if [ -n "$type" ] && ! is_type "$type"; then
    report "$f" "$lvl" "unknown type '$type' (allowed: $TYPES)"
  fi
  if [ -n "$created" ] && ! printf '%s' "$created" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    report "$f" "$lvl" "bad created date '$created' (want YYYY-MM-DD)"
  fi
}

for zone in knowledge workstreams; do
  [ -d "$VAULT/$zone" ] || continue
  while IFS= read -r -d '' f; do check_file "$f" "$zone"; done \
    < <(find "$VAULT/$zone" -type f -name '*.md' -not -path '*/.*' -print0 2>/dev/null)
done

echo ""
echo "checked $checked notes — $fail hard failure(s) in knowledge/, $warn warning(s) in workstreams/"
[ "$fail" -eq 0 ] || { echo "BRAIN CHECK FAILED"; exit 1; }
echo "BRAIN CHECK PASSED"
