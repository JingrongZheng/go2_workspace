#!/usr/bin/env bash
# Run on PC: transfer pinned offline sources and build on the Jetson.
set -eo pipefail
go2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
go2_kit="$go2_root/.work/usb-wifi-kit.tar.gz"
[[ -s "$go2_kit" ]] || { echo "Missing source archive: $go2_kit" >&2; exit 2; }
bash "$go2_root/shared/connect_go2_ssh.sh"
go2_socket="$go2_root/.work/ssh-control/go2.sock"
# Transfer through the authenticated SSH session; the board needs no Internet.
ssh -S "$go2_socket" -o BatchMode=yes unitree_go2 'umask 077; mkdir -p "$HOME/go2-wifi-repair"; cat > "$HOME/go2-wifi-repair/source-kit.tar.gz"' < "$go2_kit"
mkdir -p "$go2_root/experiments/EXP-0007"
ssh -S "$go2_socket" -o BatchMode=yes unitree_go2 'set -e; cd "$HOME/go2-wifi-repair"; tar -xzf source-kit.tar.gz; bash usb-wifi-kit/build_on_go2.sh' \
  2>&1 | tee "$go2_root/experiments/EXP-0007/driver-build.log"
