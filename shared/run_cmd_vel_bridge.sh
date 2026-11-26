#!/usr/bin/env bash
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-84}"
export ROS_LOCALHOST_ONLY=1
export PYTHONNOUSERSITE=1
unset CYCLONEDDS_URI
exec /usr/bin/python3 "$root/shared/go2_cmd_vel_bridge.py" "$@"
