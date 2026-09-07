#!/bin/bash
# Sovereign connector installer: Codex CLI on this machine, both wires.
#
#   sov connect codex --host <short-name> --vault <path> --core me,how-to-work-with-me --apply
#
# Read wire: SessionStart hook merged into ~/.codex/hooks.json (backup kept), then
# trusted in ~/.codex/config.toml by trust.py (the record the /hooks screen writes).
# Write wire: mirror.sh (~/.codex/memories -> the lane), ticked by the shared connector job.
# Without --apply it prints what it would do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=codex; LANE_PREFIX=codex-memory
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "hook       $HERE/session-start.py  (SessionStart: startup|resume -> ~/.codex/hooks.json)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s in $RUNNER_LABEL (this machine's one connector job)"
sov_write_pointers
sov_link_bins
sov_merge_hook_claude_style "$HOME/.codex/hooks.json" "$HERE/session-start.py" "startup|resume"
/usr/bin/python3 "$HERE/trust.py"
sov_register_connector "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "brain-load (session-start hook)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_runner "$HARNESS"
sov_smoke_hook "$HERE/session-start.py" claude
say; say "done. the hook is installed and trusted (same record the /hooks screen writes)."
say "start codex inside $VAULT/workstreams/<name>/ and ask it what Sovereign context it received."
