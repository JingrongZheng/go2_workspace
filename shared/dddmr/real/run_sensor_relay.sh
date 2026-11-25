#!/usr/bin/env bash
set -eo pipefail
real=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source /opt/ros/humble/setup.bash
export ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-84}
unset CYCLONEDDS_URI
exec /usr/bin/python3 "$real/relay_sensors.py" "$@"
