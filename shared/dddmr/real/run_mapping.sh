#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 4 ]] || [[ $3 != /* ]]; then
  echo "Usage: $0 {offline|wifi} PARAMETERS_YAML /raw_cloud_topic GROUND_Z" >&2
  exit 2
fi
ipc=()
case "$1" in
  offline) network=none ;;
  wifi) network=host; ipc=(--ipc host) ;;
  *) exit 2 ;;
esac
real=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
case "${GO2_MAPPING_PROFILE:-l2}" in
  l2) launch=go2_l2_mapping.launch.py; image=dddmr-point-lio:go2-local ;;
  raw) launch=go2_mapping.launch.py; image=dddmr:go2-local ;;
  *) echo "GO2_MAPPING_PROFILE must be l2 or raw" >&2; exit 2 ;;
esac
root=$(cd "$real/../../.." && pwd)
work="$root/.work/dddmr-local/navigation-ws"
source_root=$(realpath -e -- "${DDDMR_SOURCE:-$root/dddmr_navigation-main(1)/dddmr_navigation-main}")
params=$(realpath -e -- "$2")
[[ -f "$params" && -r "$work/install/setup.bash" ]]
map_dir=${DDDMR_REAL_MAPS:-"$root/.work/dddmr-real/maps"}
mkdir -p "$map_dir"
exec docker run --rm --init --network "$network" "${ipc[@]}" --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-84}" --env "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY:-0}" \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$work,dst=/outputs,readonly" \
  --mount "type=bind,src=$real,dst=/real,readonly" \
  --mount "type=bind,src=$params,dst=/mapping.yaml,readonly" \
  --env DDDMR_MAPPING_DIR=/maps/ \
  --mount "type=bind,src=$(realpath "$map_dir"),dst=/maps" \
  "$image" bash -ec '
    source /opt/ros/humble/setup.bash
    source /outputs/install/setup.bash
    exec ros2 launch "/real/$3" parameters:=/mapping.yaml "cloud_topic:=$1" "ground_z:=$2"
  ' bash "$3" "$4" "$launch"
