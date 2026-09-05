#!/bin/bash
# Sovereign connector installer: Notion, the official API pull.
#
#   sov connect notion --vault "~/My Brain" --host hub                       # dry run
#   sov connect notion ... --secret ntn_xxx --apply                          # install
#   options: --secret TOKEN   the integration token (else $NOTION_API_KEY, else ~/.notion-mirror/mirror.env)
#            --at HH:MM       daily run time, default 03:45
#            --lane PATH      lane under the vault, default raw/tools/Notion (one workspace, one lane, no host suffix)
#            --no-launchd     write the plist, do not load it (tests; or load it later from a GUI Terminal)
#
# Write wire only: a daily launchd job runs bin/brain-mirror-notion (delta; a full walk when
# the last one is older than six days). No read wire: Notion is a source, not an agent.
# The token is written to ~/.notion-mirror/mirror.env (mode 600) and never to the vault or a log.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=notion; LANE_PREFIX=notion
. "$HERE/../_lib/install-common.sh"

SECRET="${NOTION_API_KEY:-}"
AT="${NOTION_AT:-03:45}"
NOTION_LANE="${NOTION_LANE:-raw/tools/Notion}"
STATE_DIR="${NOTION_STATE_DIR:-$HOME/.notion-mirror}"
NO_LAUNCHD=0
LANE_ARG=""
rest=()
while [ $# -gt 0 ]; do
  case "$1" in
    --secret) SECRET="$2"; shift 2;;
    --at) AT="$2"; shift 2;;
    --lane) LANE_ARG="$2"; NOTION_LANE="${2#/}"; shift 2;;
    --no-launchd) NO_LAUNCHD=1; shift;;
    *) rest+=("$1"); shift;;
  esac
done
# --lane must stay a relative path inside the vault: reject an absolute path (before the
# leading-slash strip below normalizes it away) and reject any .. path segment.
case "$LANE_ARG" in
  /*) echo "--lane must be a relative path inside the vault with no .. segments" >&2; exit 64;;
esac
case "/$NOTION_LANE/" in
  */../*) echo "--lane must be a relative path inside the vault with no .. segments" >&2; exit 64;;
esac
sov_parse_args ${rest[@]+"${rest[@]}"}
sov_resolve

# One workspace, one lane: never suffixed by host, so paths that name it keep working.
case "$LANE_DIR" in "$HOME/.vault-staging"/*) ROOT="$HOME/.vault-staging";; *) ROOT="$VAULT";; esac
LANE="$(basename "$NOTION_LANE")"
LANE_DIR="$ROOT/$NOTION_LANE"
if [ -z "$SECRET" ] && [ -f "$STATE_DIR/mirror.env" ]; then
  SECRET="$(sed -n 's/^NOTION_API_KEY=//p' "$STATE_DIR/mirror.env" | head -1 | tr -d "\"'")"
fi
case "$AT" in [0-9][0-9]:[0-9][0-9]) ;; *) echo "--at wants HH:MM, got $AT" >&2; exit 64;; esac
HOUR=$((10#${AT%%:*})); MIN=$((10#${AT##*:}))

token_line="MISSING: pass --secret TOKEN, or put NOTION_API_KEY in $STATE_DIR/mirror.env"
[ -n "$SECRET" ] && token_line="provided (goes to $STATE_DIR/mirror.env, never to the vault)"
sov_plan "write      bin/brain-mirror-notion daily at $AT as $LABEL (delta; full walk when the last one is older than six days)" \
         "read       none (Notion is a source, not an agent)" \
         "token      $token_line" \
         "state      $STATE_DIR"

if [ -z "$SECRET" ]; then
  /usr/bin/python3 -c 'import json,sys; print("no token. " + json.load(open(sys.argv[1]))["manual_step"])' "$HERE/harness.json"
  exit 65
fi

sov_write_pointers
sov_link_bins
ln -sfn "$TEMPLATE/bin/brain-mirror-notion" "$HOME/brain-bin/brain-mirror-notion"
say "[bins] ~/brain-bin/brain-mirror-notion"

# instance env: merge, never clobber; the token line is rewritten, everything else kept
mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR"
umask 077
/usr/bin/python3 - "$STATE_DIR/mirror.env" "$SECRET" "$ROOT" "$NOTION_LANE" <<'EOF'
import os, sys
path, token, root, lane = sys.argv[1:5]
keep = []
have = set()
if os.path.exists(path):
    for line in open(path, encoding="utf-8"):
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in ("NOTION_API_KEY", "BRAIN_ROOT", "NOTION_LANE"):
            continue
        keep.append(line.rstrip("\n"))
lines = ["NOTION_API_KEY=" + token, "BRAIN_ROOT=" + root, "NOTION_LANE=" + lane] + keep
tmp = path + ".new"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines).rstrip("\n") + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
EOF
say "[env] $STATE_DIR/mirror.env written (mode 600)"

# ask Notion what the token can see; a test can stub this
if [ -n "${SOV_TEST_CHECK_OUTPUT:-}" ]; then
  check_out="$SOV_TEST_CHECK_OUTPUT"; check_rc=0
else
  check_rc=0
  check_out="$("$HOME/brain-bin/brain-mirror-notion" --check --state-dir "$STATE_DIR" 2>&1)" || check_rc=$?
fi
printf '%s\n' "$check_out" | sed 's/^/  /'
if [ "$check_rc" -ne 0 ] && [ "$check_rc" -ne 2 ]; then
  echo "check failed (exit $check_rc): the token is refused or Notion is unreachable; nothing scheduled" >&2
  exit "$check_rc"
fi

# roots.json: every root reachable today becomes required, so a later disconnect trips the guard
if [ ! -f "$STATE_DIR/roots.json" ]; then
  /usr/bin/python3 - "$STATE_DIR/roots.json" "$check_out" <<'EOF'
import json, re, sys
out, check_out = sys.argv[1], sys.argv[2]
roots = {}
grab = False
for line in check_out.splitlines():
    if line.startswith("roots reachable:"):
        grab = True; continue
    if grab:
        m = re.match(r"\s+([0-9a-f]{32})\s", line)
        if m:
            roots[m.group(1)] = "Private & Shared"
        elif line.strip():
            grab = False
json.dump({"default": "Private & Shared", "required": roots}, open(out, "w", encoding="utf-8"), indent=1)
print("[roots] %s written with %d required root(s); edit it to map a teamspace root to its folder" % (out, len(roots)))
EOF
else
  say "[roots] $STATE_DIR/roots.json kept"
fi

# lane contract: written once; an existing LANE.md is the owner's
mkdir -p "$LANE_DIR"
if [ -f "$LANE_DIR/LANE.md" ]; then
  say "[lane] LANE.md kept (owner's contract) in $LANE_DIR"
else
  sed -e "s|{{LANE}}|$LANE|g" -e "s|{{HOST}}|$HOST|g" -e "s|{{DATE}}|$TODAY|g" -e "s|{{AT}}|$AT|g" \
      -e "s|{{LABEL}}|$LABEL|g" -e "s|{{WRITE_VIA}}|${WRITE_VIA:-}|g" "$HERE/LANE.md.tmpl" > "$LANE_DIR/LANE.md"
  say "[lane] LANE.md written in $LANE_DIR"
fi

# the daily job: a calendar time, never RunAtLoad (a first full walk takes hours and is the owner's call)
if [ "$PLATFORM" = "Darwin" ]; then
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
		<string>$HERE/mirror.sh</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>$HOUR</integer>
		<key>Minute</key>
		<integer>$MIN</integer>
	</dict>
	<key>RunAtLoad</key>
	<false/>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin</string>
	</dict>
	<key>StandardOutPath</key>
	<string>$HOME/Library/Logs/$LABEL.log</string>
	<key>StandardErrorPath</key>
	<string>$HOME/Library/Logs/$LABEL.error.log</string>
</dict>
</plist>
EOF
  if [ "$NO_LAUNCHD" -eq 1 ]; then
    say "[launchd] $PLIST written, not loaded (--no-launchd). Load it from a Terminal on this Mac:"
    say "          launchctl bootstrap gui/\$(id -u) $PLIST"
  else
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
      say "[launchd] $LABEL daily at $AT"
    else
      say "[launchd] $PLIST written but bootstrap failed (no GUI session here?). Load it from a Terminal on this Mac:"
      say "          launchctl bootstrap gui/\$(id -u) $PLIST"
    fi
  fi
else
  say "[timer] Linux: schedule $HERE/mirror.sh with a systemd user timer, OnCalendar=*-*-* $AT:00"
fi

say; say "done. first run is yours to start: brain-mirror-notion --full --dry-run, then --full (hours on a large workspace)."
say "the job runs a delta every day at $AT and a full walk weekly. status: $STATE_DIR/last-status"
