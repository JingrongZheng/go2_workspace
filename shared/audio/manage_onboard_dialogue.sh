#!/usr/bin/env bash
# Execute on the robot computer. systemd owns the process, not the PC/SSH session.
set -euo pipefail
go2_dialogue_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "${1:-status}" in
  start)
    umask 077
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/go2-dialogue.service" <<EOF
[Unit]
Description=Go2 onboard text dialogue (audio only)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$go2_dialogue_root
ExecStart=/bin/bash $go2_dialogue_root/shared/audio/run_onboard_dialogue.sh
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now go2-dialogue.service
    python3 - <<'PYREADY'
import time
from urllib.request import build_opener, ProxyHandler
client = build_opener(ProxyHandler({}))
for attempt in range(50):
    try:
        with client.open('http://127.0.0.1:8765/health', timeout=1) as response:
            if response.status == 200:
                print('Onboard dialogue HTTP ready; check --health for configuration status.')
                break
    except OSError:
        time.sleep(.1)
else:
    raise SystemExit('Service has not become HTTP-ready; inspect systemctl --user status go2-dialogue.')
PYREADY
    ;;
  stop) systemctl --user stop go2-dialogue.service ;;
  status) systemctl --user status --no-pager go2-dialogue.service ;;
  *) echo 'Usage: manage_onboard_dialogue.sh start|stop|status' >&2; exit 2 ;;
esac
