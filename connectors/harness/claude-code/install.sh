#!/bin/bash
# Sovereign connector installer: Claude Code on this machine, both wires.
#
#   sov connect claude-code --host client --vault "~/My Brain" --core me,how-to-work-with-me --apply
#
# Without --apply it prints what it would do and changes nothing. Steps (shared
# with every harness, see _lib/install-common.sh): pointer files, ~/brain-bin
# symlinks, the SessionStart hook merged into ~/.claude/settings.json (backup kept),
# a launchd job for mirror.sh with StandardErrorPath set, LANE.md rendered or
# patched, then one smoke run of each wire.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=claude-code; LANE_PREFIX=claude-code
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "hook       $HERE/session-start.py  (SessionStart: startup|resume|clear|compact -> ~/.claude/settings.json)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s as $LABEL"
sov_write_pointers
sov_link_bins
sov_merge_hook_claude_style "$HOME/.claude/settings.json" "$HERE/session-start.py" "startup|resume|clear|compact"
sov_install_launchd "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "brain-load (session-start hook)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_hook "$HERE/session-start.py" claude
say; say "done. open a Claude Code session inside $VAULT/workstreams/<name>/ and look for the Sovereign line."
