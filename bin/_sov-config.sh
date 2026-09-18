# Source-only compatibility reader. Does not write or migrate configuration.
_sov_pointer() {
  local file="$1" key legacy modern value=""
  key="${file##*/}"
  if [[ "$key" = .brain-* ]]; then
    key="${key#.brain-}"
    key="$(printf '%s' "$key" | tr '[:lower:]-' '[:upper:]_')"
    legacy="BRAIN_$key"; modern="SOVEREIGN_$key"
    value="${!legacy:-}"
    [ "$key" != ROOT ] || value="${value:-${SOVS_VAULT:-}}"
  else
    key=""
  fi
  if [ -z "$value" ] && [ -f "$file" ]; then value="$(tr -d '\n' < "$file")"; fi
  if [ -z "$value" ] && [ -n "$key" ]; then
    value="${!modern:-}"
    [ "$key" != ROOT ] || value="${value:-${SOVEREIGN_VAULT:-}}"
  fi
  printf '%s' "$value"
}
