#!/usr/bin/env bash
set -eo pipefail

go2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
source "$go2_root/unitree_ros2/cyclonedds_ws/install/local_setup.bash"
export LD_LIBRARY_PATH="$go2_root/.work/webrtc-system-libs/extracted/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_LOCALHOST_ONLY=1
unset CYCLONEDDS_URI
exec "$go2_root/.work/webrtc-venv/bin/python" "$go2_root/shared/go2_webrtc_state.py" "$@"
