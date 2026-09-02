#!/bin/bash
# Sovereign connector installer: Codex CLI on this machine, both wires.
#
#   sov connect codex --host client --vault "~/My Brain" --core me,how-to-work-with-me --apply
#
# Read wire: SessionStart hook merged into ~/.codex/hooks.json (backup kept).
# Write wire: launchd job running mirror.sh (~/.codex/memories -> the lane).
# Without --apply it prints what it would do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=codex; LANE_PREFIX=codex-memory
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "hook       $HERE/session-start.py  (SessionStart: startup|resume -> ~/.codex/hooks.json)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s as $LABEL"
sov_write_pointers
sov_link_bins
sov_merge_hook_claude_style "$HOME/.codex/hooks.json" "$HERE/session-start.py" "startup|resume"
sov_install_launchd "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "brain-load (session-start hook)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_hook "$HERE/session-start.py" claude
say; say "done. ONE MANUAL STEP: Codex runs no hook until you trust it. Start codex, type /hooks,"
say "and trust the Sovereign session-start hook (trust is by hash, so re-trust after editing it)."
say "Then start codex inside $VAULT/workstreams/<name>/ and ask it what Sovereign context it received."
