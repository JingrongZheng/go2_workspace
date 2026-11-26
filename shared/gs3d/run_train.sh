#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GO2_GS_IMAGE:-go2-3dgs:latest}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <RGBD_SESSION_DIR> [OUTPUT_DIR] [extra train_gsplat.py args...]" >&2
  exit 2
fi

DATASET="$(cd -- "$1" && pwd)"
shift
if [[ $# -gt 0 && "$1" != --* ]]; then
  OUT_DIR="$1"
  shift
else
  OUT_DIR="$DATASET/gs3d_out"
fi
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd -- "$OUT_DIR" && pwd)"

if [[ ! -f "$DATASET/intrinsics.json" || ! -d "$DATASET/images" ]]; then
  echo "Dataset must contain intrinsics.json and images/: $DATASET" >&2
  exit 2
fi

echo "=== [1/3] Running COLMAP SfM (fixed D435i intrinsics) ==="
echo "=== [2/3] Aligning to DDDMR nav map (or D435i metric depth) ==="
echo "=== [3/3] Training 3DGS with gsplat on RTX 3060 ==="

exec docker run --rm --gpus all \
  -u "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e QT_QPA_PLATFORM=offscreen \
  -v "$ROOT/shared/gs3d:/scripts:ro" \
  -v "$DATASET:/dataset:ro" \
  -v "$OUT_DIR:/output" \
  "$IMAGE" \
  bash -c '
set -euo pipefail
mkdir -p /output/colmap/sparse /output/colmap_txt /output/colmap_aligned

CAM_PARAMS=$(python3 -c "
import json
d = json.load(open(\"/dataset/intrinsics.json\"))
print(f\"{d[\x27fx\x27]},{d[\x27fy\x27]},{d[\x27cx\x27]},{d[\x27cy\x27]}\")
")
echo "[COLMAP] Using D435i PINHOLE params: $CAM_PARAMS"

if [[ ! -f /output/colmap/database.db ]]; then
  xvfb-run -a colmap feature_extractor \
    --database_path /output/colmap/database.db \
    --image_path /dataset/images \
    --ImageReader.camera_model PINHOLE \
    --ImageReader.single_camera 1 \
    --ImageReader.camera_params "$CAM_PARAMS" \
    --SiftExtraction.use_gpu 0

  xvfb-run -a colmap exhaustive_matcher \
    --database_path /output/colmap/database.db \
    --SiftMatching.use_gpu 0

  colmap mapper \
    --database_path /output/colmap/database.db \
    --image_path /dataset/images \
    --output_path /output/colmap/sparse \
    --Mapper.ba_refine_focal_length 0 \
    --Mapper.ba_refine_extra_params 0
fi

colmap model_converter \
  --input_path /output/colmap/sparse/0 \
  --output_path /output/colmap_txt \
  --output_type TXT

python3 /scripts/align_colmap_to_nav.py \
  --dataset /dataset \
  --sparse-txt /output/colmap_txt \
  --output-txt /output/colmap_aligned

python3 /scripts/train_gsplat.py \
  --dataset /dataset \
  --sparse-txt /output/colmap_aligned \
  --output /output/model \
  "$@"
' -- "$@"
