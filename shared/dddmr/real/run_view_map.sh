#!/usr/bin/env bash
# Load a saved DDDMR pose-graph map in Docker and open it in host RViz2 (3D).
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 SAVED_MAP_DIRECTORY [--server-only]" >&2
  exit 2
fi

real="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$real/../../.." && pwd)"
map_dir="$(realpath -e -- "$1")"
server_only=0
if [[ "${2:-}" == "--server-only" ]]; then
  server_only=1
elif [[ -n "${2:-}" ]]; then
  echo "Unknown option: $2" >&2
  exit 2
fi

if [[ ! -f "$map_dir/poses.pcd" || ! -f "$map_dir/ground.pcd" ]]; then
  echo "Not a saved DDDMR map directory (missing poses.pcd or ground.pcd): $map_dir" >&2
  exit 2
fi

source_root="$(realpath -e -- "${DDDMR_SOURCE:-$root/dddmr_navigation-main(1)/dddmr_navigation-main}")"
[[ -r "$root/.work/dddmr-local/navigation-ws/install/setup.bash" ]]

domain="${ROS_DOMAIN_ID:-84}"
cname="go2-map-viewer-$$"
params_file="$(mktemp /tmp/go2-map-server-XXXXXX.yaml)"
cat >"$params_file" <<'YAML'
dddmr_pg_map_server_manager:
  ros__parameters:
    maps: [map1]
map1:
  ros__parameters:
    pose_graph_dir: /saved-map
    complete_map_voxel_size: 0.1
YAML

cleanup() {
  docker rm -f "$cname" >/dev/null 2>&1 || true
  rm -f "$params_file"
}
trap cleanup EXIT INT TERM

echo "Loading saved map: $map_dir (ROS_DOMAIN_ID=$domain)"
docker run -d --rm --init --name "$cname" --network host --ipc host --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env "ROS_DOMAIN_ID=$domain" --env ROS_LOCALHOST_ONLY=1 \
  --mount "type=bind,src=$root/.work/dddmr-local/navigation-ws,dst=/outputs,readonly" \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$map_dir,dst=/saved-map,readonly" \
  --mount "type=bind,src=$params_file,dst=/tmp/map-server.yaml,readonly" \
  dddmr:go2-local bash -ec '
    source /opt/ros/humble/setup.bash
    source /outputs/install/setup.bash
    exec ros2 run dddmr_pg_map_server dddmr_pg_map_server_node --ros-args --params-file /tmp/map-server.yaml
  ' >/dev/null

sleep 2
if ! docker ps -q --filter "name=^/${cname}$" | grep -q .; then
  echo "Map server failed to start." >&2
  exit 1
fi

if [[ "$server_only" -eq 1 ]]; then
  echo "Map server running on ROS_DOMAIN_ID=$domain. Press Ctrl+C to stop."
  docker logs -f "$cname"
  exit 0
fi

# shellcheck disable=SC1091
set +u
source /opt/ros/humble/setup.bash
set -u
export ROS_DOMAIN_ID="$domain"
export ROS_LOCALHOST_ONLY=1
export PYTHONNOUSERSITE=1
unset CYCLONEDDS_URI
echo "Opening RViz2 (close RViz window or Ctrl+C to stop map server)..."
rviz2 -d "$real/go2_view_map.rviz"
