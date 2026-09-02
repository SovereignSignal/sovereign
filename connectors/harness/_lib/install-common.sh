#!/bin/bash
# Shared installer steps for every harness connector. Sourced, not run.
#
# A harness install.sh sets HARNESS and LANE_PREFIX, sources this file, then calls
# the steps it needs. Everything written is instance-level: pointer files, one
# launchd plist, one hook entry, one LANE.md. The template stays general.
#
#   sov_parse_args "$@"       --host --vault --core --hub --interval --label --apply
#   sov_resolve               VAULT CORE HOST LANE LANE_DIR WRITE_VIA LABEL PLIST
#   sov_plan <line>...        print the dry-run summary (always)
#   sov_write_pointers        ~/.brain-root ~/.brain-core ~/.brain-host
#   sov_link_bins             ~/brain-bin/{brain-load,brain-capture,brain-lane-scope,sov}
#   sov_merge_hook_claude_style <json> <hook> <matcher>   Claude Code settings.json / Codex hooks.json
#   sov_merge_hook_cursor <json> <hook>                   Cursor ~/.cursor/hooks.json (version 1)
#   sov_install_launchd <mirror.sh>                       every $INTERVAL s, StandardErrorPath set
#   sov_lane_contract <LANE.md.tmpl> <read line>          render, or patch read: + note
#   sov_smoke_mirror <mirror.sh>
#   sov_smoke_hook <hook> <claude|cursor>
set -euo pipefail

HOST=""; VAULT=""; CORE=""; HUB=""; INTERVAL=900; APPLY=0; LABEL=""
_pointer() { [ -f "$1" ] && tr -d '\n' < "$1" || true; }
say() { printf '%s\n' "$*"; }

sov_parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --host) HOST="$2"; shift 2;;
      --vault) VAULT="$2"; shift 2;;
      --core) CORE="$2"; shift 2;;
      --hub) HUB="$2"; shift 2;;
      --interval) INTERVAL="$2"; shift 2;;
      --label) LABEL="$2"; shift 2;;
      --apply) APPLY=1; shift;;
      -h|--help) sed -n '2,20p' "$0"; exit 0;;
      *) echo "unknown option: $1" >&2; exit 64;;
    esac
  done
}

sov_resolve() {
  VAULT="${VAULT:-$(_pointer "$HOME/.brain-root")}"
  CORE="${CORE:-$(_pointer "$HOME/.brain-core")}"
  HOST="${HOST:-$(_pointer "$HOME/.brain-host")}"
  HOST="${HOST:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
  VAULT="${VAULT/#\~/$HOME}"
  [ -n "$VAULT" ] || { echo "need --vault PATH (or ~/.brain-root)"; exit 64; }
  [ -d "$VAULT/knowledge" ] || { echo "not a brain: $VAULT has no knowledge/ folder"; exit 66; }
  [ -n "$CORE" ] || echo "note: no always-on core (--core a,b,c or ~/.brain-core); packs will be topic-only"
  LANE="$LANE_PREFIX-$HOST"
  if [ -d "$HOME/.vault-staging" ]; then
    LANE_DIR="$HOME/.vault-staging/raw/tools/$LANE"; WRITE_VIA=" (via staging)"
  else
    LANE_DIR="$VAULT/raw/tools/$LANE"; WRITE_VIA=""
  fi
  LABEL="${LABEL:-com.sovereign.connector.$HARNESS}"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  TODAY="$(date +%F)"
}

sov_plan() {
  say "Sovereign connector: $HARNESS on host '$HOST'"
  say "  vault      $VAULT"
  say "  core       ${CORE:-(none)}"
  say "  lane       $LANE_DIR"
  for l in "$@"; do say "  $l"; done
  say "  template   $TEMPLATE"
  if [ "$APPLY" -ne 1 ]; then say; say "dry run. add --apply to install."; exit 0; fi
}

sov_write_pointers() {
  printf '%s' "$VAULT" > "$HOME/.brain-root"
  [ -n "$CORE" ] && printf '%s' "$CORE" > "$HOME/.brain-core"
  printf '%s' "$HOST" > "$HOME/.brain-host"
  [ -n "$HUB" ] && printf '%s' "$HUB" > "$HOME/.brain-hub"
  say "[pointers] ~/.brain-root ~/.brain-core ~/.brain-host${HUB:+ ~/.brain-hub}"
}

sov_link_bins() {
  mkdir -p "$HOME/brain-bin"
  for b in brain-load brain-capture brain-lane-scope sov; do
    [ -e "$TEMPLATE/bin/$b" ] && ln -sfn "$TEMPLATE/bin/$b" "$HOME/brain-bin/$b"
  done
  chmod +x "$TEMPLATE/bin/sov" 2>/dev/null || true
  say "[bins] ~/brain-bin -> $TEMPLATE/bin"
}

# Claude Code settings.json and Codex hooks.json share one shape:
#   {"hooks": {"SessionStart": [{"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}]}}
sov_merge_hook_claude_style() {
  local json="$1" hook="$2" matcher="$3"
  mkdir -p "$(dirname "$json")"
  [ -f "$json" ] || echo '{}' > "$json"
  cp "$json" "$json.bak-$(date +%Y%m%d-%H%M%S)"
  chmod +x "$hook" 2>/dev/null || true
  /usr/bin/python3 - "$json" "$hook" "$matcher" <<'EOF'
import json, sys
path, hook, matcher = sys.argv[1:4]
d = json.load(open(path))
groups = d.setdefault("hooks", {}).setdefault("SessionStart", [])
if any(h.get("command") == hook for g in groups for h in g.get("hooks", [])):
    print("[hook] already present in", path)
else:
    groups.append({"matcher": matcher,
                   "hooks": [{"type": "command", "command": hook, "timeout": 30,
                              "statusMessage": "Sovereign: loading brain context"}]})
    json.dump(d, open(path, "w"), indent=2)
    print("[hook] SessionStart added to", path)
EOF
}

# Cursor: {"version": 1, "hooks": {"sessionStart": [{"command": "...", "timeout": 30}]}}
sov_merge_hook_cursor() {
  local json="$1" hook="$2"
  mkdir -p "$(dirname "$json")"
  [ -f "$json" ] || echo '{"version": 1, "hooks": {}}' > "$json"
  cp "$json" "$json.bak-$(date +%Y%m%d-%H%M%S)"
  chmod +x "$hook" 2>/dev/null || true
  /usr/bin/python3 - "$json" "$hook" <<'EOF'
import json, sys
path, hook = sys.argv[1:3]
d = json.load(open(path))
d.setdefault("version", 1)
arr = d.setdefault("hooks", {}).setdefault("sessionStart", [])
if any(h.get("command") == hook for h in arr):
    print("[hook] already present in", path)
else:
    arr.append({"command": hook, "timeout": 30})
    json.dump(d, open(path, "w"), indent=2)
    print("[hook] sessionStart added to", path)
EOF
}

sov_install_launchd() {
  local mirror="$1"
  chmod +x "$mirror" 2>/dev/null || true
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>$mirror</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StartInterval</key>
	<integer>$INTERVAL</integer>
	<key>StandardOutPath</key>
	<string>$HOME/Library/Logs/$LABEL.log</string>
	<key>StandardErrorPath</key>
	<string>$HOME/Library/Logs/$LABEL.error.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  say "[launchd] $LABEL every ${INTERVAL}s"
}

sov_lane_contract() {
  local tmpl="$1" readline="$2"
  mkdir -p "$LANE_DIR"
  if [ -f "$LANE_DIR/LANE.md" ]; then
    cp "$LANE_DIR/LANE.md" "$LANE_DIR/.LANE.md.bak-$(date +%Y%m%d-%H%M%S)"
    /usr/bin/python3 - "$LANE_DIR/LANE.md" "$readline" "$HARNESS" "$TODAY" "$LABEL" "$INTERVAL" <<'EOF'
import re, sys
p, readline, harness, today, label, interval = sys.argv[1:7]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r"(?m)^read:.*$", "read: " + readline, s, count=1)
marker = "sov connect " + harness
if marker not in s2:
    s2 = s2.rstrip() + ("\n\nRewired %s by `%s`: read wire `%s`; write wire "
        "`connectors/harness/%s/mirror.sh` every %ss as `%s`. `MANIFEST.md` in the lane is "
        "the heartbeat; `brain-load-usage.md` is the read receipt.\n"
        % (today, marker, readline, harness, interval, label))
open(p, "w", encoding="utf-8").write(s2)
print("[lane] LANE.md patched (read: + note)")
EOF
  else
    sed -e "s|{{HOST}}|$HOST|g" -e "s|{{DATE}}|$TODAY|g" -e "s|{{INTERVAL}}|$INTERVAL|g" \
        -e "s|{{LABEL}}|$LABEL|g" -e "s|{{WRITE_VIA}}|$WRITE_VIA|g" -e "s|{{READ}}|$readline|g" \
        "$tmpl" > "$LANE_DIR/LANE.md"
    say "[lane] LANE.md written"
  fi
}

sov_smoke_mirror() {
  /bin/bash "$1"
  say "[smoke] mirror: $(grep -m1 'Last run' "$LANE_DIR/MANIFEST.md" 2>/dev/null || echo 'no manifest?')"
}

sov_smoke_hook() {
  local hook="$1" style="$2" out
  out="$(cd "$VAULT" && CURSOR_PROJECT_DIR="$VAULT" printf '{"cwd":"%s","session_id":"install-smoke","source":"startup"}' "$VAULT" | /usr/bin/python3 "$hook")"
  if [ "$style" = "cursor" ]; then
    printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("additional_context",""); print("[smoke] hook ok: %d chars of context" % len(c) if c else "[smoke] hook produced no context")'
  else
    printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print("[smoke] hook ok:", d.get("systemMessage"))' || say "[smoke] hook produced no context (check ~/.brain-core and brain-load)"
  fi
}
