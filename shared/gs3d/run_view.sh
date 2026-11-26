#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GO2_GS_IMAGE:-go2-3dgs:latest}"
PORT="${GO2_GS_PORT:-8080}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <POINT_CLOUD.PLY>" >&2
  exit 2
fi
PLY_ABS="$(cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")"
if [[ ! -f "$PLY_ABS" ]]; then
  echo "PLY file not found: $PLY_ABS" >&2
  exit 2
fi

echo "Starting 3DGS viewer on http://localhost:$PORT for $PLY_ABS ..."
exec docker run --rm -it \
  -p "$PORT:$PORT" \
  -v "$ROOT/shared/gs3d:/scripts:ro" \
  -v "$(dirname -- "$PLY_ABS"):/model:ro" \
  "$IMAGE" \
  python3 /scripts/view_gsplat.py "/model/$(basename -- "$PLY_ABS")" --port "$PORT"
