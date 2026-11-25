#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
seconds=${1:-6}
[[ "$seconds" =~ ^[1-9][0-9]{0,2}$ ]] && ((seconds <= 120))
ssh -T -S "$root/.work/ssh-control/go2-wifi.sock" -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o ConnectTimeout=4 unitree@192.168.110.87 "
    set -e
    source /opt/ros/foxy/setup.bash >&2
    source /unitree/module/graph_pid_ws/install/unitree_go/share/unitree_go/local_setup.bash >&2
    source ~/cyclonedds_ws/install/local_setup.bash >&2
    export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export CYCLONEDDS_URI='<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth10</NetworkInterfaceAddress></General></Domain></CycloneDDS>'
    exec timeout $((seconds + 5)) /usr/bin/python3 -u - --seconds $seconds
  " < "$root/experiments/EXP-0022/read_imu_pair.py"
