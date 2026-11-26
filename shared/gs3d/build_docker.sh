#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GO2_GS_IMAGE:-go2-3dgs:latest}"
echo "Building $IMAGE from $ROOT/shared/gs3d/docker/Dockerfile ..."
exec docker build -t "$IMAGE" "$ROOT/shared/gs3d/docker"
