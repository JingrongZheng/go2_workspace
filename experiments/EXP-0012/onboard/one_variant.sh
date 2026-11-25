#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/foxy/setup.bash
if [[ "$VARIANT" == old ]]; then
  source /unitree/module/graph_pid_ws/install/setup.bash
else
  source "$HOME/go2-lidar-diagnostic/hesai_v2_ws/install/setup.bash"
fi
source "$HOME/cyclonedds_ws/install/setup.bash"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export LD_LIBRARY_PATH="/usr/local/lib:$LD_LIBRARY_PATH"
export CYCLONEDDS_URI="$HOME/go2-lidar-diagnostic/hesai_v2_ws/cyclonedds_xt16.xml"
export ROS_DOMAIN_ID=83 ROS_LOCALHOST_ONLY=0
ros2 pkg prefix "$([[ "$VARIANT" == old ]] && echo hesai_lidar || echo hesai_ros_driver)"
/usr/bin/python3 "$TEST_DIR/probe_wired_lidar.py" --duration 17 > "$TEST_DIR/$VARIANT-points.log" 2>&1 &
probe_pid=$!
if [[ "$VARIANT" == old ]]; then
  setsid timeout --signal=INT --kill-after=3 15 ros2 launch hesai_lidar hesai_lidar_launch.py > "$TEST_DIR/$VARIANT-driver.log" 2>&1 &
else
  setsid timeout --signal=INT --kill-after=3 15 ros2 run hesai_ros_driver hesai_ros_driver_node --ros-args -p "config_path:=$HOME/go2-lidar-diagnostic/hesai_v2_ws/config_xt16_compare.yaml" > "$TEST_DIR/$VARIANT-driver.log" 2>&1 &
fi
driver_pid=$!
cleanup() {
  kill -TERM -- "-$driver_pid" 2>/dev/null || true
  kill "$probe_pid" 2>/dev/null || true
}
trap cleanup EXIT
sleep 3
ps -eo pid,ppid,args | grep -E '[h]esai_lidar_node|[h]esai_ros_driver_node' || true
ss -lun
wait "$driver_pid" && driver_rc=0 || driver_rc=$?
wait "$probe_pid" && probe_rc=0 || probe_rc=$?
echo "variant=$VARIANT driver_exit=$driver_rc subscriber_exit=$probe_rc"
cat "$TEST_DIR/$VARIANT-points.log"
tail -n 16 "$TEST_DIR/$VARIANT-driver.log"
