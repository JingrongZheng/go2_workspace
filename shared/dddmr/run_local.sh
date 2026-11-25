#!/usr/bin/env bash
# Start one local simulation component; never connects to a real robot.
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
work_root="$project_root/.work/dddmr-local"
source_root=${DDDMR_SOURCE:-"$project_root/dddmr_navigation-main(1)/dddmr_navigation-main"}
component=${1:-}
[[ $component == simulation || $component == navigation || $component == initialize || $component == display-check ]] || {
  echo 'Usage: bash shared/dddmr/run_local.sh simulation|navigation|initialize|display-check'; exit 1;
}
if [[ $component == initialize ]]; then
  exec docker exec go2-dddmr-navigation bash -c \
    'source /opt/ros/humble/setup.bash; python3 /project-tools/initialize_demo_pose.py'
fi
[[ -n ${DISPLAY:-} && -f ${XAUTHORITY:-} ]] || { echo 'Run from the local desktop session.' >&2; exit 1; }
docker info >/dev/null
container="go2-dddmr-$component"
if state=$(docker container inspect --format '{{.State.Status}}' "$container" 2>/dev/null); then
  if [[ $state != running ]]; then
    echo "容器 $container 已存在，状态为 $state。" >&2
    echo "先检查：docker logs --tail 50 $container" >&2
    echo "需要保留旧容器后重新创建时：docker rename $container ${container}-saved-\$(date +%s)" >&2
    exit 1
  fi
  case "$component" in
    simulation)
      expected_image=dddmr-sim:go2-local
      gui_process=gzclient
      gui_command='source /opt/ros/humble/setup.bash; source /ws_gz/install/setup.bash; exec gzclient'
      ;;
    navigation)
      expected_image=dddmr:go2-local
      gui_process=rviz2
      gui_command='source /opt/ros/humble/setup.bash; source /outputs/install/setup.bash; exec rviz2 -d /project-gui/go2-localization.rviz --ros-args -p use_sim_time:=true'
      ;;
    display-check)
      expected_image=dddmr-display-check:local
      gui_process=rviz2
      gui_command='source /opt/ros/humble/setup.bash; exec rviz2'
      ;;
  esac
  image=$(docker container inspect --format '{{.Config.Image}}' "$container")
  [[ $image == "$expected_image" ]] || {
    echo "同名容器使用其他镜像：$image；请先检查，不自动接管。" >&2; exit 1;
  }
  if docker exec "$container" pgrep -x "$gui_process" >/dev/null; then
    echo "$container 已在运行，界面进程也存在；使用现有窗口。"
  else
    docker exec --detach "$container" bash -c "$gui_command > /tmp/dddmr-gui-reopen.log 2>&1"
    echo "$container 已在运行，已重新启动 $gui_process 界面。"
    echo "若界面未出现：docker exec $container cat /tmp/dddmr-gui-reopen.log"
  fi
  echo "查看日志：docker logs --tail 50 $container"
  echo "完整重启前，先停止导航和仿真：docker stop go2-dddmr-navigation go2-dddmr-simulation"
  exit 0
fi
mkdir -p "$work_root/gui" "$work_root/logs"
auth="$work_root/gui/Xauthority"
touch "$auth"
chmod 600 "$auth"
xauth -f "$XAUTHORITY" nlist "$DISPLAY" | sed 's/^..../ffff/' | xauth -f "$auth" nmerge -
[[ -s $auth ]] || { echo 'Could not prepare X11 authentication.' >&2; exit 1; }
common=(--rm --network host --ipc host --gpus all
  --env DISPLAY --env XAUTHORITY=/tmp/dddmr.Xauthority --env QT_X11_NO_MITSHM=1
  --env ROS_DOMAIN_ID=83 --env ROS_LOCALHOST_ONLY=1
  --env GAZEBO_IP=127.0.0.1 --env GAZEBO_MASTER_URI=http://127.0.0.1:11345
  --env NVIDIA_DRIVER_CAPABILITIES=all --env __NV_PRIME_RENDER_OFFLOAD=1
  --env __GLX_VENDOR_LIBRARY_NAME=nvidia
  --mount "type=bind,src=$project_root/shared/dddmr,dst=/project-tools,readonly"
  --mount "type=bind,src=/tmp/.X11-unix,dst=/tmp/.X11-unix,readonly"
  --mount "type=bind,src=$auth,dst=/tmp/dddmr.Xauthority,readonly")
if [[ ${DDDMR_DETACH:-0} == 1 ]]; then
  common+=(--detach)
fi
if [[ $component == display-check ]]; then
  exec docker run "${common[@]}" --name go2-dddmr-display-check dddmr-display-check:local \
    bash -c 'source /opt/ros/humble/setup.bash; glxinfo -B; exec rviz2'
fi
if [[ $component == simulation ]]; then
  exec docker run "${common[@]}" --name go2-dddmr-simulation dddmr-sim:go2-local \
    bash -c 'source /opt/ros/humble/setup.bash; source /ws_gz/install/setup.bash; exec ros2 launch go2_config gz_lidar_odom.launch.py'
fi
[[ -f "$work_root/navigation-ws/install/setup.bash" ]] || { echo 'Build navigation first.' >&2; exit 1; }
[[ -d "$work_root/maps/gz_go2_demo_world" ]] || { echo 'Missing extracted Go2 demo map.' >&2; exit 1; }
# The upstream saved RViz window is 3700x2272; derive a laptop-sized copy.
docker run --rm --network none --entrypoint cat dddmr:go2-local \
  /opt/ros/humble/share/rviz_common/default.rviz > "$work_root/gui/rviz-default.rviz"
/usr/bin/python3 - "$source_root" "$work_root/gui" <<'PY'
from pathlib import Path
import re
import sys
source, gui = map(Path, sys.argv[1:])
package = source / 'src/dddmr_p2p_move_base'
rviz = (package / 'rviz/p2p_move_base_localization.rviz').read_text()
head, geometry = rviz.rsplit('Window Geometry:', 1)
default = (gui / 'rviz-default.rviz').read_text()
state = re.search(r'^  QMainWindow State:.*$', default, flags=re.M)
assert state, 'RViz default dock layout was not found.'
geometry = re.sub(r'^  QMainWindow State:.*$', state.group(), geometry, flags=re.M)
for key, value in [('Height', 850), ('Width', 1280), ('X', 120), ('Y', 60)]:
    geometry = re.sub(rf'^  {key}:.*$', f'  {key}: {value}', geometry, flags=re.M)
(gui / 'go2-localization.rviz').write_text(head + 'Window Geometry:' + geometry)
launch = (package / 'launch/go2_localization.launch').read_text()
old = '$(find-pkg-share p2p_move_base)/rviz/p2p_move_base_localization.rviz'
assert old in launch, 'Upstream RViz launch changed; inspect before starting.'
(gui / 'go2_localization.launch.xml').write_text(
    launch.replace(old, '/project-gui/go2-localization.rviz'))
PY
exec docker run "${common[@]}" --name go2-dddmr-navigation \
  --mount "type=bind,src=$work_root/gui,dst=/project-gui,readonly" \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$work_root/navigation-ws,dst=/outputs" \
  --mount "type=bind,src=$work_root/maps,dst=/root/dddmr_bags,readonly" \
  dddmr:go2-local bash -c 'source /opt/ros/humble/setup.bash; source /outputs/install/setup.bash; exec ros2 launch /project-gui/go2_localization.launch.xml'
