#!/bin/bash
# Sovereign connector installer: Claude Code on this machine, both wires.
#
#   sov connect claude-code --host client --vault "~/Documents/My Brain" --core me,how-to-work-with-me --apply
#
# Without --apply it prints what it would do and changes nothing.
# Everything it writes is instance-level (pointer files, one plist, one hook entry,
# one LANE.md). The template stays general.
#
# What --apply does, in order:
#   1. pointer files   ~/.brain-root ~/.brain-core ~/.brain-host
#   2. symlinks        ~/brain-bin/{brain-load,brain-capture,brain-lane-scope,sov}
#   3. read wire       SessionStart hook merged into ~/.claude/settings.json (backup kept)
#   4. write wire      launchd job running mirror.sh every --interval seconds,
#                      StandardErrorPath set (a silent job is a broken job)
#   5. lane contract   LANE.md rendered into the lane (or its read: line patched)
#   6. smoke test      one mirror run, one hook run
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HOST=""; VAULT=""; CORE=""; INTERVAL=900; APPLY=0
LABEL="com.sovereign.connector.claude-code"

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --vault) VAULT="$2"; shift 2;;
    --core) CORE="$2"; shift 2;;
    --interval) INTERVAL="$2"; shift 2;;
    --label) LABEL="$2"; shift 2;;
    --apply) APPLY=1; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 64;;
  esac
done

_pointer() { [ -f "$1" ] && tr -d '\n' < "$1" || true; }
VAULT="${VAULT:-$(_pointer "$HOME/.brain-root")}"
CORE="${CORE:-$(_pointer "$HOME/.brain-core")}"
HOST="${HOST:-$(_pointer "$HOME/.brain-host")}"
HOST="${HOST:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
VAULT="${VAULT/#\~/$HOME}"

[ -n "$VAULT" ] || { echo "need --vault PATH (or ~/.brain-root)"; exit 64; }
[ -d "$VAULT/knowledge" ] || { echo "not a brain: $VAULT has no knowledge/ folder"; exit 66; }
[ -n "$CORE" ] || echo "note: no always-on core (--core a,b,c or ~/.brain-core); packs will be topic-only"

LANE="claude-code-$HOST"
if [ -d "$HOME/.vault-staging" ]; then
  LANE_DIR="$HOME/.vault-staging/raw/tools/$LANE"; WRITE_VIA=" (via staging)"
else
  LANE_DIR="$VAULT/raw/tools/$LANE"; WRITE_VIA=""
fi
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SETTINGS="$HOME/.claude/settings.json"
HOOK="$HERE/session-start.py"
MIRROR="$HERE/mirror.sh"

say() { printf '%s\n' "$*"; }
say "Sovereign connector: claude-code on host '$HOST'"
say "  vault      $VAULT"
say "  core       ${CORE:-(none)}"
say "  lane       $LANE_DIR"
say "  hook       $HOOK  (SessionStart: startup|resume|clear|compact)"
say "  mirror     $MIRROR  every ${INTERVAL}s as $LABEL"
say "  template   $TEMPLATE"
if [ "$APPLY" -ne 1 ]; then say; say "dry run. add --apply to install."; exit 0; fi

# 1. pointer files
printf '%s' "$VAULT" > "$HOME/.brain-root"
[ -n "$CORE" ] && printf '%s' "$CORE" > "$HOME/.brain-core"
printf '%s' "$HOST" > "$HOME/.brain-host"
say "[1] pointer files written"

# 2. symlinks
mkdir -p "$HOME/brain-bin"
for b in brain-load brain-capture brain-lane-scope sov; do
  [ -e "$TEMPLATE/bin/$b" ] && ln -sfn "$TEMPLATE/bin/$b" "$HOME/brain-bin/$b"
done
chmod +x "$HOOK" "$MIRROR" "$TEMPLATE/bin/sov" 2>/dev/null || true
say "[2] ~/brain-bin symlinks -> $TEMPLATE/bin"

# 3. hook (merge, idempotent by command path, backup first)
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
cp "$SETTINGS" "$SETTINGS.bak-$(date +%Y%m%d-%H%M%S)"
/usr/bin/python3 - "$SETTINGS" "$HOOK" <<'EOF'
import json, sys
path, hook = sys.argv[1], sys.argv[2]
d = json.load(open(path))
groups = d.setdefault("hooks", {}).setdefault("SessionStart", [])
present = any(h.get("command") == hook for g in groups for h in g.get("hooks", []))
if not present:
    groups.append({"matcher": "startup|resume|clear|compact",
                   "hooks": [{"type": "command", "command": hook, "timeout": 30,
                              "statusMessage": "Sovereign: loading brain context"}]})
    json.dump(d, open(path, "w"), indent=2)
    print("[3] SessionStart hook added to", path)
else:
    print("[3] SessionStart hook already present")
EOF

# 4. launchd job for the write wire
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
		<string>$MIRROR</string>
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
say "[4] launchd job $LABEL loaded (every ${INTERVAL}s)"

# 5. lane contract
mkdir -p "$LANE_DIR"
TODAY="$(date +%F)"
if [ -f "$LANE_DIR/LANE.md" ]; then
  cp "$LANE_DIR/LANE.md" "$LANE_DIR/.LANE.md.bak-$(date +%Y%m%d-%H%M%S)"
  /usr/bin/python3 - "$LANE_DIR/LANE.md" "$TODAY" "$LABEL" "$INTERVAL" <<'EOF'
import re, sys
p, today, label, interval = sys.argv[1:5]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r"(?m)^read:.*$", "read: brain-load (session-start hook)", s, count=1)
note = ("\n\nRewired %s by `sov connect claude-code`: read wire is the SessionStart hook "
        "(`connectors/harness/claude-code/session-start.py`), write wire is `mirror.sh` every %ss "
        "as `%s`, now mirroring every project's memory under `memory/<project>/`. "
        "`memory/MANIFEST.md` is the heartbeat; `brain-load-usage.md` is the read receipt.\n"
        % (today, interval, label))
if "sov connect claude-code" not in s2:
    s2 = s2.rstrip() + note
open(p, "w", encoding="utf-8").write(s2)
print("[5] LANE.md patched (read: line + install note)")
EOF
else
  sed -e "s|{{HOST}}|$HOST|g" -e "s|{{DATE}}|$TODAY|g" -e "s|{{INTERVAL}}|$INTERVAL|g" \
      -e "s|{{LABEL}}|$LABEL|g" -e "s|{{WRITE_VIA}}|$WRITE_VIA|g" \
      "$HERE/LANE.md.tmpl" > "$LANE_DIR/LANE.md"
  say "[5] LANE.md written"
fi

# 6. smoke test
/bin/bash "$MIRROR"
say "[6] mirror ran: $(grep -m1 'Last run' "$LANE_DIR/memory/MANIFEST.md" 2>/dev/null || echo 'no manifest?')"
out="$(cd "$VAULT" && printf '{"cwd":"%s","session_id":"install-smoke","source":"startup"}' "$VAULT" | /usr/bin/python3 "$HOOK")"
if printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print("[6] hook ok:", d.get("systemMessage"))'; then :; else
  say "[6] hook produced no context (check ~/.brain-core and brain-load)"; fi
say
say "done. open a Claude Code session inside $VAULT/workstreams/<name>/ and look for the Sovereign line."
