#!/usr/bin/env bash
# Onboard entry for the user's selected HesaiTechnology/HesaiLidar_ROS_2.0 driver.
set -euo pipefail
go2_hesai_ws=${GO2_HESAI_WS:-"$HOME/go2-lidar-diagnostic/hesai_v2_ws"}
go2_hesai_config=${GO2_HESAI_CONFIG:-"$go2_hesai_ws/config_xt16_official.yaml"}
go2_dds_ws=${GO2_DDS_WS:-"$HOME/cyclonedds_ws"}
go2_dds_config=${GO2_CYCLONEDDS_URI:-"$go2_hesai_ws/cyclonedds_xt16.xml"}
[[ -f /opt/ros/foxy/setup.bash && -f "$go2_hesai_ws/install/setup.bash" ]] || {
  echo 'Foxy or the compiled official Hesai workspace is missing.' >&2; exit 1;
}
[[ -f $go2_hesai_config ]] || { echo "Missing config: $go2_hesai_config" >&2; exit 1; }
[[ -f "$go2_dds_ws/install/setup.bash" && -f "$go2_dds_config" ]] || {
  echo 'Matching onboard Cyclone DDS workspace or XML is missing.' >&2; exit 1;
}
echo "Driver: HesaiTechnology/HesaiLidar_ROS_2.0"
echo "Workspace: $go2_hesai_ws"
echo "Config: $go2_hesai_config"
echo "DDS: rmw_cyclonedds_cpp; XML: $go2_dds_config"
echo 'PointCloud2: /lidar_points; Ctrl+C stops.'
exec env -i HOME="$HOME" USER="$(id -un)" PATH=/usr/bin:/bin LANG=C.UTF-8 \
  GO2_HESAI_WS="$go2_hesai_ws" GO2_HESAI_CONFIG="$go2_hesai_config" \
  GO2_DDS_WS="$go2_dds_ws" CYCLONEDDS_URI="$go2_dds_config" \
  ROS_DOMAIN_ID="${GO2_ROS_DOMAIN_ID:-0}" ROS_LOCALHOST_ONLY="${GO2_ROS_LOCALHOST_ONLY:-0}" \
  /bin/bash --noprofile --norc -c '
    set -e
    source /opt/ros/foxy/setup.bash
    source "$GO2_HESAI_WS/install/setup.bash"
    source "$GO2_DDS_WS/install/setup.bash"
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export LD_LIBRARY_PATH="/usr/local/lib:$LD_LIBRARY_PATH"
    exec ros2 run hesai_ros_driver hesai_ros_driver_node --ros-args \
      -p "config_path:=$GO2_HESAI_CONFIG"
  '
