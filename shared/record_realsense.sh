#!/usr/bin/env bash
set -eo pipefail
go2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$go2_root/.work/webrtc-venv/bin/python" "$go2_root/shared/record_realsense.py" "$@"
