#!/usr/bin/env bash
set -eo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-84}"
export ROS_LOCALHOST_ONLY=1
if [[ -f /opt/ros/humble/setup.bash ]]; then
  set +u
  source /opt/ros/humble/setup.bash
  set -u
fi
if [[ -x "$ROOT/.work/webrtc-venv/bin/python" ]]; then
  # Include system ROS 2 dist-packages so optional /mcl_pose sync works alongside venv OpenCV.
  export PYTHONPATH="/opt/ros/humble/lib/python3.10/site-packages:/opt/ros/humble/local/lib/python3.10/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
  exec "$ROOT/.work/webrtc-venv/bin/python" "$ROOT/shared/gs3d/record_rgbd_keyframes.py" "$@"
else
  exec /usr/bin/python3 "$ROOT/shared/gs3d/record_rgbd_keyframes.py" "$@"
fi
