#!/usr/bin/env bash
set -eo pipefail
go2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export LD_LIBRARY_PATH="$go2_root/.work/webrtc-system-libs/extracted/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$go2_root/.work/webrtc-venv/bin/python" "$go2_root/shared/audio/streaming_dialogue.py" "$@"
