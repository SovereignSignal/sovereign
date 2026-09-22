#!/bin/bash
# Sovereign connector, Parallels guests, the WRITE wire.
#
# The Linux VMs on this Mac hold Claude Code (and sometimes Claude Desktop) but have no
# SSH server and no Tailscale, so nothing outside the host can reach them. The host can:
# `prlctl exec` runs a command inside a running guest and returns its stdout, and a tar
# stream survives that path byte for byte (checked 2026-09-22 against sha256sum in the
# guest). So the host pulls, one folder per guest:
#
#   <lane>/<guest-slug>/claude-code/memory/<project>/   Claude Code distilled memory
#   <lane>/<guest-slug>/claude/                          Claude Desktop outputs, if any
#
# A guest that is not running is named in the manifest and skipped; nothing is invented
# for it. A guest with no Claude material is named and skipped too. Credentials
# (.credentials.json, .claude.json) and transcripts (*.jsonl) are never asked for: only
# the memory folders and the outputs folder are tarred. The guest is never written to.
#
# Destination and config: see _lib/mirror-common.sh. Failures return nonzero; prior captures are retained.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"
LANE="parallels-$BRAIN_HOST_RESOLVED"
PRLCTL="${PRLCTL:-/usr/local/bin/prlctl}"
[ -x "$PRLCTL" ] || exit 0                      # no Parallels here: nothing to do, not a failure
sov_prepare "$LANE" "parallels" || exit 1
mkdir -p "$DEST" || { echo "mirror: cannot create $DEST" >&2; exit 1; }
ok=0; failed=0; lines=()

# Every guest command is a script on prlctl's stdin. `prlctl exec VM sh -c '...'` re-splits
# its arguments on spaces and cannot carry quoting; a script on stdin arrives intact, and
# its stdout (a tar stream included) comes back byte for byte. Because prlctl reads stdin,
# the guest list is collected into an array first, never streamed into a loop that also
# runs prlctl. Guests run these as root, read-only; the guest is never written to.
# Both return prlctl's own exit status, so a guest that answered nothing because the exec
# failed (prlctl is occasionally flaky: "PrlJob_GetResult: Invalid argument") is told apart
# from a guest that truly has nothing; one retry covers the transient case. An exec that
# still fails marks the guest FAILED and the run nonzero, never "0 folders mirrored".
in_guest_raw() {
  local try rc
  for try in 1 2; do
    printf '%s\n' "$2" | "$PRLCTL" exec "$1" sh 2>/dev/null
    rc=${PIPESTATUS[1]}
    [ "$rc" -eq 0 ] && return 0
    sleep 2
  done
  return "$rc"
}
in_guest() { local out; out="$(in_guest_raw "$1" "$2")" || return $?; printf '%s' "$out" | tr -d '\r'; }

# `prlctl list -i` reports the guest OS as a distro or platform name (ubuntu, debian,
# win-11, macos-14). Only a Linux guest has /home and sh; the others are named and skipped
# before any exec, so a running Windows guest is not mistaken for a broken exec.
os_of() { "$PRLCTL" list -i "$1" 2>/dev/null | sed -n 's/^OS:[[:space:]]*//p' | head -1 | tr -d '\r'; }
is_linux_os() { case "$1" in win*|macos*|other*|"") return 1;; *) return 0;; esac; }

slug_of() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'; }

rows=()
while IFS= read -r row; do rows+=("$row"); done < <("$PRLCTL" list -a -o name,status 2>/dev/null | tail -n +2 \
  | sed -E 's/[[:space:]]+(running|stopped|suspended|paused|starting|stopping|resetting|suspending|resuming|unknown)[[:space:]]*$/|\1/')

for row in ${rows[@]+"${rows[@]}"}; do
  name="${row%%|*}"; status="${row##*|}"
  [ -n "$name" ] && [ "$name" != "$row" ] || continue
  slug="$(slug_of "$name")"
  if [ "$status" != "running" ]; then
    lines+=("- \`$slug\` ($name): $status, skipped")
    continue
  fi
  os="$(os_of "$name")"
  if ! is_linux_os "$os"; then
    lines+=("- \`$slug\` ($name): running, ${os:-unknown OS}, not a Linux guest, skipped")
    continue
  fi
  # Claude runs as a login user inside a guest, so only /home is asked.
  if ! homes="$(in_guest "$name" 'for h in /home/*; do [ -d "$h/.claude/projects" ] && echo "$h"; done; true')"; then
    failed=$((failed+1)); lines+=("- \`$slug\` ($name): running, but prlctl exec FAILED twice"); echo "mirror: prlctl exec failed for guest $name" >&2
    continue
  fi
  homes="$(printf '%s\n' "$homes" | grep '^/')"
  if [ -z "$homes" ]; then
    lines+=("- \`$slug\` ($name): running, no Claude Code projects, skipped")
    continue
  fi
  projects=0; guest_failed=0
  while IFS= read -r home; do
    [ -n "$home" ] || continue
    if ! mems="$(in_guest "$name" "cd '$home/.claude/projects' && find . -mindepth 2 -maxdepth 2 -type d -name memory | sed 's#^\./##'")"; then
      guest_failed=1; echo "mirror: prlctl exec failed listing projects in guest $name" >&2; break
    fi
    [ -n "$mems" ] || continue
    out="$DEST/$slug/claude-code/memory"; mkdir -p "$out" || { guest_failed=1; break; }
    script="cd '$home/.claude/projects' && tar -cf - --"; while IFS= read -r m; do script="$script '$m'"; done <<< "$mems"
    if in_guest_raw "$name" "$script" | tar -xf - -C "$out" --exclude='*.jsonl' --exclude='.credentials.json' 2>/dev/null; then
      # <project>/memory/*.md -> <project>/*.md, the same shape the claude-code lane uses
      for p in "$out"/*/memory; do
        [ -d "$p" ] || continue
        proj="$(dirname "$p")"; rsync -a "$p/" "$proj/" && rm -rf "$p"
        projects=$((projects+1))
      done
    else
      guest_failed=1; echo "mirror: tar from guest $name failed" >&2
    fi
    # Claude Desktop outputs, when the folder exists and holds anything.
    if [ -n "$(in_guest "$name" "[ -d '$home/Claude' ] && find '$home/Claude' -type f -print -quit; true")" ]; then
      mkdir -p "$DEST/$slug/claude"
      in_guest_raw "$name" "cd '$home' && tar -cf - Claude" \
        | tar -xf - -C "$DEST/$slug/claude" --strip-components=1 --exclude='*.jsonl' 2>/dev/null \
        || { guest_failed=1; echo "mirror: tar of Claude outputs from guest $name failed" >&2; }
    fi
  done <<< "$homes"
  if [ "$guest_failed" -eq 0 ]; then
    ok=$((ok+1)); lines+=("- \`$slug\` ($name): running, $projects project memory folder(s) mirrored")
  else
    failed=$((failed+1)); lines+=("- \`$slug\` ($name): running, collection FAILED")
  fi
done

sov_manifest "$DEST" "$LANE" "Parallels guest mirror manifest" "$ok" "$failed" \
  "Each folder is one guest VM on this Mac, pulled by the host through \`prlctl exec\`;" \
  "\`<guest>/claude-code/memory/<project>/\` is that guest's Claude Code memory, \`<guest>/claude/\`" \
  "its Claude Desktop outputs. A guest that is not running is skipped, never invented." "" ${lines[@]+"${lines[@]}"}
sov_finish "Parallels guest mirror"
exit $?
