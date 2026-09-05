#!/bin/bash
# Sovereign connector installer: Orca on this machine, the write wire.
#
#   sov connect orca --host client --vault "~/My Brain" --apply
#
# Orca orchestrates other coding agents; those agents carry their own read wires, so
# this connector installs none. Write wire: a scheduled job running mirror.sh, which
# renders Orca's runs (tasks, decision gates, questions, messages) from its SQLite
# store into markdown, one capture per run. Without --apply it prints what it would
# do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=orca; LANE_PREFIX=orca
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "mirror     $HERE/mirror.sh  every ${INTERVAL}s as $LABEL  (orchestration.db -> runs/*.md)"
sov_write_pointers
sov_link_bins
sov_install_launchd "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "none (the agents Orca drives carry their own read wires)"
sov_smoke_mirror "$HERE/mirror.sh"
say; say "done. Orca runs land under raw/tools/orca-$HOST/runs/ after each mirror pass."
