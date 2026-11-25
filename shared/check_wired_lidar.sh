#!/usr/bin/env bash
set -eo pipefail

go2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
go2_iface="${GO2_IFACE:-enp2s0}"
if [[ ! "$go2_iface" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
  echo 'Invalid GO2_IFACE' >&2
  exit 2
fi
if [[ ! -r "/sys/class/net/$go2_iface/operstate" ]] || [[ "$(cat "/sys/class/net/$go2_iface/operstate")" != up ]]; then
  echo "No active wired link on $go2_iface. Connect the cable and check device power." >&2
  exit 2
fi
source /opt/ros/humble/setup.bash
source "$go2_root/unitree_ros2/cyclonedds_ws/install/local_setup.bash"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_LOCALHOST_ONLY=0
export ROS_DOMAIN_ID=0
export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"$go2_iface\"/></Interfaces></General></Domain></CycloneDDS>"
echo "Read-only DDS probe: interface=$go2_iface domain=$ROS_DOMAIN_ID"
ip -br addr show dev "$go2_iface"
exec /usr/bin/python3 "$go2_root/shared/probe_wired_lidar.py" "$@"
