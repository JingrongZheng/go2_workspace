#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 3 && $# != 4 ]] || [[ $2 != /* || $3 != /* || $2 == "$3" ]]; then
  echo "Usage: $0 {offline|wifi} /raw_cloud_topic /internal_imu_topic [BAG_DIRECTORY]" >&2
  exit 2
fi
ipc=()
case "$1" in
  offline) network=none; domain=84 ;;
  wifi) network=host; ipc=(--ipc host); domain=${ROS_DOMAIN_ID:-84} ;;
  *) exit 2 ;;
esac
if [[ $# == 4 && $1 != offline ]]; then
  echo "Bag playback uses the offline mode." >&2
  exit 2
fi
real=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
case "${GO2_IMU_SOURCE:-lidar}" in
  lidar) launch=point_lio_l2.launch.py ;;
  chassis) launch=point_lio_chassis.launch.py ;;
  *) echo "GO2_IMU_SOURCE must be lidar or chassis" >&2; exit 2 ;;
esac
work="$real/../../../.work/dddmr-real/ws"
[[ -r "$work/install/setup.bash" ]] || { echo "Run build_point_lio.sh first." >&2; exit 1; }
mounts=()
if [[ $# == 4 ]]; then
  bag=$(realpath -e -- "$4")
  [[ -f "$bag/metadata.yaml" ]] || { echo "Missing bag metadata.yaml." >&2; exit 2; }
  mounts+=(--mount "type=bind,src=$bag,dst=/recorded-bag,readonly")
fi
exec docker run --rm --init --network "$network" "${ipc[@]}" --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env "ROS_DOMAIN_ID=$domain" --env "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY:-0}" \
  --mount "type=bind,src=$(realpath "$work"),dst=/lio-ws,readonly" \
  --mount "type=bind,src=$(realpath "$work/src/point_lio/Log"),dst=/lio-ws/src/point_lio/Log" \
  --mount "type=bind,src=$real,dst=/go2-real,readonly" "${mounts[@]}" \
  dddmr-point-lio:go2-local bash -ec '
    source /opt/ros/humble/setup.bash
    source /lio-ws/install/local_setup.bash
    play=false
    [[ ! -d /recorded-bag ]] || play=true
    exec ros2 launch "/go2-real/$3" "cloud_topic:=$1" "imu_topic:=$2" "play_bag:=$play"
  ' bash "$2" "$3" "$launch"
