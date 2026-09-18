#!/bin/bash
# Sovereign connector installer: Notion, the official API pull.
#
#   sov connect notion --vault <path> --host <short-name>                    # dry run
#   sov connect notion ... --secret ntn_xxx --apply                          # install
#   options: --secret TOKEN   the integration token (else $NOTION_API_KEY, else ~/.notion-mirror/mirror.env)
#            --at HH:MM       daily run time, default 03:45
#            --lane PATH      lane under the vault, default raw/tools/Notion (one workspace, one lane, no host suffix)
#            --no-launchd     write the plist, do not load it (tests; or load it later from a GUI Terminal)
#
# Write wire only: a daily scheduled job runs bin/sov-mirror-notion (delta; a full walk when
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
NOTION_DIR="${NOTION_STATE_DIR:-$HOME/.notion-mirror}"
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
if [ -z "$SECRET" ] && [ -f "$NOTION_DIR/mirror.env" ]; then
  SECRET="$(sed -n 's/^NOTION_API_KEY=//p' "$NOTION_DIR/mirror.env" | head -1 | tr -d "\"'")"
fi
case "$AT" in [0-9][0-9]:[0-9][0-9]) ;; *) echo "--at wants HH:MM, got $AT" >&2; exit 64;; esac

token_line="MISSING: pass --secret TOKEN, or put NOTION_API_KEY in $NOTION_DIR/mirror.env"
[ -n "$SECRET" ] && token_line="provided (goes to $NOTION_DIR/mirror.env, never to the vault)"
sov_plan "write      bin/sov-mirror-notion daily at $AT as $LABEL (delta; full walk when the last one is older than six days)" \
         "read       none (Notion is a source, not an agent)" \
         "token      $token_line" \
         "state      $NOTION_DIR"

if [ -z "$SECRET" ]; then
  /usr/bin/python3 -c 'import json,sys; print("no token. " + json.load(open(sys.argv[1]))["manual_step"])' "$HERE/harness.json"
  exit 65
fi

sov_write_pointers
sov_link_bins
ln -sfn "$TEMPLATE/bin/sov-mirror-notion" "$HOME/brain-bin/sov-mirror-notion"
say "[bins] ~/brain-bin/sov-mirror-notion"

# instance env: merge, never clobber; the token line is rewritten, everything else kept
mkdir -p "$NOTION_DIR"; chmod 700 "$NOTION_DIR"
umask 077
# the token goes through the environment, never argv, so ps never shows it
NOTION_API_KEY_VALUE="$SECRET" /usr/bin/python3 - "$NOTION_DIR/mirror.env" "$ROOT" "$NOTION_LANE" <<'EOF'
import os, sys
path, root, lane = sys.argv[1:4]
token = os.environ["NOTION_API_KEY_VALUE"]
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
umask 022  # mirror.env is written 600 by the writer itself; everything after it is ordinary
say "[env] $NOTION_DIR/mirror.env written (mode 600)"

# a status line from the retired import script would otherwise show as this harness's
# own status until its first run; park it once, only when this harness has never completed
# a run (no state/cursor yet)
if [ ! -f "$NOTION_DIR/state/cursor" ]; then
  for name in last-status last-success; do
    if [ -f "$NOTION_DIR/$name" ]; then
      mv "$NOTION_DIR/$name" "$NOTION_DIR/$name.pre-api"
      say "[state] previous importer status parked as $name.pre-api"
    fi
  done
fi

# ask Notion what the token can see; a test can stub this
if [ -n "${SOV_TEST_CHECK_OUTPUT:-}" ]; then
  check_out="$SOV_TEST_CHECK_OUTPUT"; check_rc=0
else
  check_rc=0
  check_out="$("$HOME/brain-bin/sov-mirror-notion" --check --state-dir "$NOTION_DIR" 2>&1)" || check_rc=$?
fi
printf '%s\n' "$check_out" | sed 's/^/  /'
if [ "$check_rc" -ne 0 ] && [ "$check_rc" -ne 2 ]; then
  echo "check failed (exit $check_rc): the token is refused or Notion is unreachable; nothing scheduled" >&2
  exit "$check_rc"
fi

# roots.json: every root reachable today becomes required, so a later disconnect trips the guard
if [ ! -f "$NOTION_DIR/roots.json" ]; then
  /usr/bin/python3 - "$NOTION_DIR/roots.json" "$check_out" <<'EOF'
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
  say "[roots] $NOTION_DIR/roots.json kept"
fi

# The daily job: a calendar time, never RunAtLoad (a first full walk takes hours and is
# the owner's call). This is the one harness that keeps a job of its own instead of
# joining the shared connector runner: its run is measured in hours, and neither launchd
# StartInterval nor a systemd oneshot starts a second run while one is in flight, so a
# lane that can outlive a tick would starve every 15-minute lane behind it.
sov_install_calendar_job "$HERE/mirror.sh" "$AT"

# lane contract: written once; an existing LANE.md is the owner's. It comes AFTER the job,
# never before: behind a staging hop $LANE_DIR is inside ~/.vault-staging, and making that
# tree is what sends every mirror on this Mac into staging. Made here it would be made
# before anything existed to carry it, so an install that then failed would leave the whole
# machine mirroring into a tree nothing drains -- the tick path closes this by the same
# ordering. sov_install_calendar_job makes the tree itself, under the rollback that takes
# it back if the run dies, and brings up the mover that carries it.
sov_assert_staging_carried
mkdir -p "$LANE_DIR"
if [ -f "$LANE_DIR/LANE.md" ]; then
  say "[lane] LANE.md kept (owner's contract) in $LANE_DIR"
else
  sed -e "s|{{LANE}}|$LANE|g" -e "s|{{HOST}}|$HOST|g" -e "s|{{DATE}}|$TODAY|g" -e "s|{{AT}}|$AT|g" \
      -e "s|{{LABEL}}|$LABEL|g" -e "s|{{WRITE_VIA}}|${WRITE_VIA:-}|g" "$HERE/LANE.md.tmpl" > "$LANE_DIR/LANE.md"
  say "[lane] LANE.md written in $LANE_DIR"
fi

say; say "done. first run is yours to start: sov-mirror-notion --full --dry-run, then --full (hours on a large workspace)."
say "the job runs a delta every day at $AT and a full walk weekly. status: $NOTION_DIR/last-status"
