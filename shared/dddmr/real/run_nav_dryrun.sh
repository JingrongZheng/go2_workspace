#!/usr/bin/env bash
# Single Docker launch for R3 + R4 combined dry-run:
# Point-LIO + 3D MCL relocalization + A* global planner + P2P local planner + /cmd_vel audit.
# Strictly DRY-RUN: no robot velocity bridge is started.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "Usage: $0 SAVED_MAP_DIRECTORY [SESSION_DIRECTORY] [GROUND_Z]" >&2
  exit 2
fi

real="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$real/../../.." && pwd)"
map_dir="$(realpath -e -- "$1")"
session="$(realpath -m -- "${2:-$root/.work/sessions/nav-dryrun-$(date +%Y%m%d-%H%M%S)}")"
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
cp -- "$real/config/l2_nav_dryrun_lab.yaml" "$session/parameters.yaml"
printf '%s\n' "$map_dir" > "$session/map_dir.txt"
printf '%s\n' "$ground" > "$session/ground_z.txt"

echo "R3+R4 DRY-RUN: Point-LIO + MCL 3D + A* Global Planner + P2P Move Base + /cmd_vel audit."
echo "Safety: NO robot velocity bridge is running (robot will NOT move autonomously)."
echo "Map:     $map_dir"
echo "Session: $session (logs: stack.log, cmd_vel_audit.jsonl)"
echo "In RViz ('./go2 rviz nav'):"
echo "  1) Use '2D Pose Estimate' to set initial pose (/initial_3d_pose)"
echo "  2) Use '2D Goal Pose' (/goal_pose_3d) or 'Publish Point' (/clicked_point) to test planning"

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
    exec ros2 launch /go2-real/go2_nav_dryrun.launch.py parameters:=/session/parameters.yaml "ground_z:=$1"
  ' bash "$ground"
