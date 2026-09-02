#!/bin/bash
# Sovereign connector installer: Cursor on this machine, both wires.
#
#   sov connect cursor --host client --vault "~/My Brain" --core me,how-to-work-with-me --apply
#
# Read wire: sessionStart hook merged into ~/.cursor/hooks.json (backup kept); it
# returns the pack as additional_context. Write wire: launchd job running mirror.sh
# (GUI chats exported from SQLite, CLI transcripts, plans, skills, config).
# Without --apply it prints what it would do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=cursor; LANE_PREFIX=cursor
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "hook       $HERE/session-start.py  (sessionStart -> ~/.cursor/hooks.json)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s as $LABEL"
sov_write_pointers
sov_link_bins
sov_merge_hook_cursor "$HOME/.cursor/hooks.json" "$HERE/session-start.py"
sov_install_launchd "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "brain-load (sessionStart hook)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_hook "$HERE/session-start.py" cursor
say; say "done. open $VAULT/workstreams/<name>/ in Cursor, start an agent chat, and ask what Sovereign context it received."
