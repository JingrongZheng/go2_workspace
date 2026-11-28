#!/usr/bin/env bash
set -eo pipefail
go2_dialogue_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$go2_dialogue_root/vendor${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$go2_dialogue_root/.work/system-libs/usr/lib/aarch64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$go2_dialogue_root/.venv/bin/python" "$go2_dialogue_root/shared/audio/onboard_dialogue.py" "$@"
