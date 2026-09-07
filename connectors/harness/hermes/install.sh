#!/bin/bash
# Sovereign connector installer: Hermes agent on this machine, both wires.
#
#   sov connect hermes --host <short-name> --vault <path> --core me,how-to-work-with-me --apply
#
# Read wire: a pre_llm_call shell hook in ~/.hermes/config.yaml (backup kept) with
# consent recorded in ~/.hermes/shell-hooks-allowlist.json, the documented manual path.
# Write wire: a scheduled job running mirror.sh (~/.hermes/memories -> the lane).
# Without --apply it prints what it would do and changes nothing. Hermes picks the
# hook up on its next start (restart the gateway or the CLI session once).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=hermes; LANE_PREFIX=hermes
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "hook       $HERE/session-start.py  (pre_llm_call -> ~/.hermes/config.yaml, consent -> shell-hooks-allowlist.json)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s in $RUNNER_LABEL (this machine's one connector job)"
sov_write_pointers
sov_link_bins
chmod +x "$HERE/session-start.py" "$HERE/hooks.py"
/usr/bin/python3 "$HERE/hooks.py"
sov_register_connector "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "brain-load (pre_llm_call hook, first turn of a conversation)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_runner "$HARNESS"
out="$(cd "$VAULT" && printf '{"session_id":"install-smoke","extra":{"user_message":"hello","conversation_history":[]}}' | /usr/bin/python3 "$HERE/session-start.py")"
printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("context",""); print("[smoke] hook ok: %d chars of context" % len(c) if c else "[smoke] hook produced no context")'
say; say "done. restart Hermes once (gateway or CLI) so it reads the new hooks block; then start a new conversation."
