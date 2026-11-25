#!/usr/bin/env bash
# Install only a user-space ROS message workspace and the command receiver.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
host=${1:-192.168.110.87}
socket=${2:-"$root/.work/ssh-control/go2-wifi-new.sock"}
/usr/bin/python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$host"
kit=$(mktemp -d "$root/.work/wifi-keyboard-setup.XXXXXX")
trap 'rm -rf -- "$kit"' EXIT
mkdir -p "$kit/unitree_api"
cp -r "$root/unitree_ros2/cyclonedds_ws/src/unitree/unitree_api/msg" "$kit/unitree_api/"
cp "$root/unitree_ros2/cyclonedds_ws/src/unitree/unitree_api/package.xml" "$kit/unitree_api/"
cat > "$kit/unitree_api/CMakeLists.txt" <<'CMAKE'
cmake_minimum_required(VERSION 3.5)
project(unitree_api)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
# Official IDL unchanged; optional Connext-specific output is not required.
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Request.msg" "msg/RequestHeader.msg" "msg/RequestIdentity.msg"
  "msg/RequestLease.msg" "msg/RequestPolicy.msg" "msg/Response.msg"
  "msg/ResponseHeader.msg" "msg/ResponseStatus.msg")
ament_export_dependencies(rosidl_default_runtime)
ament_package()
CMAKE
cp "$root/shared/go2_wifi_control_source.py" "$kit/"
tar -cf "$kit/deploy.tar" -C "$kit" unitree_api go2_wifi_control_source.py
ssh -T -S "$socket" -o BatchMode=yes "unitree@$host" \
  'mkdir -p /home/unitree/go2-keyboard-control/staging && tar -xf - -C /home/unitree/go2-keyboard-control/staging' < "$kit/deploy.tar"
ssh -T -S "$socket" -o BatchMode=yes "unitree@$host" "bash -c 'set -e
mkdir -p ~/go2-keyboard-control/ws/src
cp -r ~/go2-keyboard-control/staging/unitree_api ~/go2-keyboard-control/ws/src/
cp ~/go2-keyboard-control/staging/go2_wifi_control_source.py ~/go2-keyboard-control/
source /opt/ros/foxy/setup.bash
source ~/cyclonedds_ws/install/local_setup.bash
cd ~/go2-keyboard-control/ws
colcon build --packages-select unitree_api --parallel-workers 1 --cmake-args -DBUILD_TESTING=OFF -DPYTHON_EXECUTABLE=/usr/bin/python3
'"
