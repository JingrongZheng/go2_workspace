#!/usr/bin/env bash
# PC-local keyboard requests for either LocalSTA or Remote WebRTC bridges.
set -eo pipefail

go2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
source "$go2_root/unitree_ros2/cyclonedds_ws/install/local_setup.bash"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_LOCALHOST_ONLY=1
unset CYCLONEDDS_URI
exec /usr/bin/python3 "$go2_root/shared/go2_keyboard_control.py" \
  --request-topic /go2/webrtc/sport/request "$@"
