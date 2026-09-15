#!/bin/bash
#
# _sov-python.sh — the one answer to "which python3 runs the brain's tools and its jobs".
# Sourced by bin/sov (its own tools) and connectors/harness/_lib/install-common.sh (the
# program a scheduled job names), so the two never disagree.
#
# On a Mac /usr/bin/python3 is an Xcode shim. After an Xcode update it exits 69 ("You have
# not agreed to the Xcode license agreements") until someone accepts the license, and a
# launchd job that names it fails every tick, silently, from then on (one laptop, 2026-09-14,
# seven hours of it). The Command Line Tools ship a real interpreter at a stable path that
# no Xcode update gates, so that one is preferred when it exists.
#
#   sov_python <template-dir>   print the interpreter path, in this order:
#     1. <template>/../python/bin/python3   a managed Hub's bundled runtime
#     2. $SOV_PYTHON                        an explicit choice (bin/sov exports its own)
#     3. the Command Line Tools python      Darwin only; SOV_CLT_PYTHON overrides the path
#     4. /usr/bin/python3                   the shim, or Linux's ordinary python3

sov_python() {
  local template="$1"
  local clt="${SOV_CLT_PYTHON:-/Library/Developer/CommandLineTools/usr/bin/python3}"
  if [ -x "$template/../python/bin/python3" ]; then echo "$template/../python/bin/python3"; return; fi
  if [ -n "${SOV_PYTHON:-}" ]; then echo "$SOV_PYTHON"; return; fi
  if [ "${SOV_PLATFORM:-$(uname -s)}" = "Darwin" ] && [ -x "$clt" ]; then echo "$clt"; return; fi
  echo /usr/bin/python3
}

# True when the path is the Xcode shim on a Mac: the one choice an Xcode update can revoke.
sov_python_is_shim() {
  [ "${SOV_PLATFORM:-$(uname -s)}" = "Darwin" ] && [ "$1" = /usr/bin/python3 ]
}
