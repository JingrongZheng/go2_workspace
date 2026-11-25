#!/usr/bin/env bash
# Authenticate locally once, then let project tools reuse the SSH connection.
# Works without relying on ~/.ssh/config host aliases.
set -euo pipefail

go2_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
go2_control_dir="$go2_root/.work/ssh-control"
mkdir -p "$go2_control_dir"
chmod 700 "$go2_control_dir"

mode="wired"
user="${GO2_USER:-unitree}"
host=""
socket=""
close_only=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    wired|wifi)
      mode="$1"
      shift
      ;;
    --host)
      host="${2:?missing value for --host}"
      shift 2
      ;;
    --user)
      user="${2:?missing value for --user}"
      shift 2
      ;;
    --socket)
      socket="${2:?missing value for --socket}"
      shift 2
      ;;
    --close)
      close_only=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: connect_go2_ssh.sh [wired|wifi] [--host IP] [--user USER] [--socket PATH] [--close]
Defaults:
  wired: unitree@192.168.123.18  socket=.work/ssh-control/go2.sock
  wifi:  unitree@192.168.110.87  socket=.work/ssh-control/go2-wifi.sock
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$host" ]]; then
  if [[ "$mode" == "wifi" ]]; then
    host="${GO2_WIFI_HOST:-192.168.110.87}"
  else
    host="${GO2_WIRED_HOST:-192.168.123.18}"
  fi
fi

if [[ -z "$socket" ]]; then
  if [[ "$mode" == "wifi" ]]; then
    socket="$go2_control_dir/go2-wifi.sock"
  else
    socket="$go2_control_dir/go2.sock"
  fi
fi

target="${user}@${host}"

if [[ "$close_only" -eq 1 ]]; then
  if ssh -S "$socket" -O check "$target" 2>/dev/null; then
    ssh -S "$socket" -O exit "$target"
  elif [[ -S "$socket" ]]; then
    rm -- "$socket"
    echo "Removed stale SSH socket: $socket"
  else
    echo "No active SSH connection for $target ($socket)."
  fi
  exit 0
fi

if ssh -S "$socket" -O check "$target" 2>/dev/null; then
  echo "Existing Go2 SSH connection is available: $target ($socket)"
  exit 0
fi

# A reboot or link drop can leave a dead local socket. Remove it only after check failed.
if [[ -S "$socket" ]]; then
  rm -- "$socket"
fi

ssh -M -S "$socket" -o ControlPersist=30m -o ConnectTimeout=8 \
  -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -fN "$target"
ssh -S "$socket" -O check "$target"
echo "Go2 SSH connection ready: $target ($socket). Password was entered locally and is not saved."
