#!/usr/bin/env bash
# Single Docker/ROS launch for R3: Point-LIO + DDDMR 3D MCL relocalization on a saved map.
# Read-only localization: no global/local planner, no /cmd_vel, no motion control.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "Usage: $0 SAVED_MAP_DIRECTORY [SESSION_DIRECTORY] [GROUND_Z]" >&2
  exit 2
fi

real="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$real/../../.." && pwd)"
map_dir="$(realpath -e -- "$1")"
session="$(realpath -m -- "${2:-$root/.work/sessions/loc-$(date +%Y%m%d-%H%M%S)}")"
ground="${3:--0.3168676504844956}"

if [[ ! -f "$map_dir/poses.pcd" || ! -f "$map_dir/ground.pcd" ]]; then
  echo "Not a saved DDDMR map directory (missing poses.pcd or ground.pcd): $map_dir" >&2
  exit 2
fi

PYTHONNOUSERSITE=1 /usr/bin/python3 - "$ground" <<'PY'
import math, sys
if not math.isfinite(float(sys.argv[1])):
    raise ValueError("Ground height must be finite")
PY

if [[ -e "$session" ]] && { [[ ! -d "$session" ]] || [[ -n $(ls -A -- "$session") ]]; }; then
  echo "Choose a new empty session directory; existing results are preserved." >&2
  exit 2
fi

source_root="$(realpath -e -- "${DDDMR_SOURCE:-$root/dddmr_navigation-main(1)/dddmr_navigation-main}")"
[[ -r "$root/.work/dddmr-real/ws/install/setup.bash" ]]
[[ -r "$root/.work/dddmr-local/navigation-ws/install/setup.bash" ]]

mkdir -p "$session/lio-debug"
cp -- "$real/config/l2_localization_lab.yaml" "$session/parameters.yaml"
printf '%s\n' "$map_dir" > "$session/map_dir.txt"
printf '%s\n' "$ground" > "$session/ground_z.txt"

echo "R3 Localization: L2 + chassis IMU -> Point-LIO -> DDDMR MCL 3D; no planner or controller."
echo "Map:     $map_dir"
echo "Session: $session (log: $session/stack.log)"
echo "Provide coarse initial pose via RViz '2D Pose Estimate' (publishes /initial_3d_pose)."

exec docker run --rm --init --network host --ipc host --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-84}" --env ROS_LOCALHOST_ONLY=1 \
  --mount "type=bind,src=$root/.work/dddmr-real/ws,dst=/lio-ws,readonly" \
  --mount "type=bind,src=$session/lio-debug,dst=/lio-ws/src/point_lio/Log" \
  --mount "type=bind,src=$root/.work/dddmr-local/navigation-ws,dst=/outputs,readonly" \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$real,dst=/go2-real,readonly" \
  --mount "type=bind,src=$map_dir,dst=/saved-map,readonly" \
  --mount "type=bind,src=$session,dst=/session" \
  dddmr-point-lio:go2-local bash -ec '
    exec > >(tee -a /session/stack.log) 2>&1
    source /opt/ros/humble/setup.bash
    source /outputs/install/setup.bash
    source /lio-ws/install/local_setup.bash
    exec ros2 launch /go2-real/go2_live_localization.launch.py parameters:=/session/parameters.yaml "ground_z:=$1"
  ' bash "$ground"
