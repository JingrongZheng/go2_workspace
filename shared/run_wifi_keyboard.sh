#!/usr/bin/env bash
set -eo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source /opt/ros/humble/setup.bash
source "$root/unitree_ros2/cyclonedds_ws/install/local_setup.bash"
export PYTHONNOUSERSITE=1
exec /usr/bin/python3 "$root/shared/go2_wifi_keyboard.py" "$@"
