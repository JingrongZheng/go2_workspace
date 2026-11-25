#!/usr/bin/env bash
# A single Docker/ROS launch for the real LIO and DDDMR mapping stack.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 NEW_SESSION_DIRECTORY [GROUND_Z]" >&2
  exit 2
fi
real=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$real/../../.." && pwd)
output=$(realpath -m -- "$1")
ground=${2:--0.3168676504844956}
PYTHONNOUSERSITE=1 /usr/bin/python3 - "$ground" <<'PY'
import math,sys
if not math.isfinite(float(sys.argv[1])):
    raise ValueError('Ground height must be finite')
PY
if [[ -e "$output" ]] && { [[ ! -d "$output" ]] || [[ -n $(ls -A -- "$output") ]]; }; then
  echo "Choose a new empty session directory; existing results are preserved." >&2
  exit 2
fi
source_root=$(realpath -e -- "${DDDMR_SOURCE:-$root/dddmr_navigation-main(1)/dddmr_navigation-main}")
[[ -r "$root/.work/dddmr-real/ws/install/setup.bash" ]]
[[ -r "$root/.work/dddmr-local/navigation-ws/install/setup.bash" ]]
mkdir -p "$output/maps" "$output/lio-debug"
cp -- "$real/config/l2_mapping_lab.yaml" "$output/parameters.yaml"
cp -- "$real/go2_published_cloud_geometry.json" "$real/go2_nominal_geometry.json" "$output/"
printf '%s\n' "$ground" > "$output/ground_z.txt"
echo "L2 + chassis IMU -> Point-LIO -> DDDMR; no controller."
echo "Maps: $output/maps (call /save_mapped_point_cloud before Ctrl+C)."
exec docker run --rm --init --network host --ipc host --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-84}" --env ROS_LOCALHOST_ONLY=1 \
  --env DDDMR_MAPPING_DIR=/session/maps/ \
  --mount "type=bind,src=$root/.work/dddmr-real/ws,dst=/lio-ws,readonly" \
  --mount "type=bind,src=$output/lio-debug,dst=/lio-ws/src/point_lio/Log" \
  --mount "type=bind,src=$root/.work/dddmr-local/navigation-ws,dst=/outputs,readonly" \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$real,dst=/go2-real,readonly" \
  --mount "type=bind,src=$output,dst=/session" \
  dddmr-point-lio:go2-local bash -ec '
    exec > >(tee -a /session/stack.log) 2>&1
    source /opt/ros/humble/setup.bash
    source /outputs/install/setup.bash
    source /lio-ws/install/local_setup.bash
    exec ros2 launch /go2-real/go2_live_mapping.launch.py parameters:=/session/parameters.yaml "ground_z:=$1"
  ' bash "$ground"
