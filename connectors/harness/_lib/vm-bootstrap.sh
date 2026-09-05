#!/usr/bin/env bash
# vm-bootstrap.sh — run once INSIDE a local VM (Parallels, UTM, ...) whose host Mac shares
# its home folder into the guest. The console hands the owner this one line:
#   bash /media/psf/Home/.sovereign/vm-bootstrap.sh
# It opens ssh, authorizes the hub's fleet key (and the Mac's own key when present),
# joins the tailnet so the hub can reach the VM like any other machine, lets user
# services run without a login, and prints the address. Nothing else changes in the VM.
# After it, the hub finishes the job: `sov host add <name> --user <u> --addr <ip> --apply`.
set -euo pipefail
SHARE="${SOVEREIGN_SHARE:-/media/psf/Home}"        # where the Mac home is mounted in the guest
HUB_PUB="$SHARE/.sovereign/hub.pub"                  # the hub's fleet key (placed there by the console)
MAC_PUB="$SHARE/.sovereign/mac.pub"                  # optional: the Mac's own key

echo "== 1/5 ssh server"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq; sudo apt-get install -y -qq openssh-server curl >/dev/null
  sudo systemctl enable --now ssh >/dev/null
elif command -v dnf >/dev/null; then
  sudo dnf install -y -q openssh-server curl >/dev/null; sudo systemctl enable --now sshd >/dev/null
fi
echo "   sshd running"

echo "== 2/5 keys"
[[ -r "$HUB_PUB" ]] || { echo "   cannot read $HUB_PUB: is the Mac home shared into this VM (Parallels: Sharing > Share Mac home)?"; exit 1; }
mkdir -p ~/.ssh && chmod 700 ~/.ssh; touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
for pub in "$HUB_PUB" "$MAC_PUB"; do
  [[ -r "$pub" ]] || continue
  grep -qF "$(cut -d' ' -f2 "$pub")" ~/.ssh/authorized_keys || cat "$pub" >> ~/.ssh/authorized_keys
  echo "   authorized: $(cut -d' ' -f3- "$pub")"
done

echo "== 3/5 tailnet"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
sudo tailscale up --hostname "$(hostname)" || true      # prints a login URL the first time
TS=$(tailscale ip -4 2>/dev/null || true)
echo "   tailscale: ${TS:-not up yet; open the login URL above, then run: sudo tailscale up}"

echo "== 4/5 user services survive logout"
command -v loginctl >/dev/null && sudo loginctl enable-linger "$USER" && echo "   linger on for $USER"

echo "== 5/5 address"
LAN=$(hostname -I | awk '{print $1}')
echo "   $(hostname): user $USER, tailnet ${TS:-pending}, local $LAN"
echo "SOVEREIGN-READY host=$(hostname) user=$USER addr=${TS:-$LAN}"
