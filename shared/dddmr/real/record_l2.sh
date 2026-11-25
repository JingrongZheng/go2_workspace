#!/usr/bin/env bash
set -eo pipefail
if [[ $# != 3 || $2 != /* || $3 != /* || $2 == "$3" ]]; then
  echo "Usage: $0 BAG_DIRECTORY /raw_cloud_topic /internal_imu_topic" >&2
  exit 2
fi
source /opt/ros/humble/setup.bash
exec ros2 bag record -o "$1" "$2" "$3"
