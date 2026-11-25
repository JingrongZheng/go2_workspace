#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
work_root="$project_root/.work/dddmr-local"
sim_root="$work_root/sources/dfl_mobilerobot_simulator"
jobs=${DDDMR_BUILD_JOBS:-2}
[[ $jobs =~ ^[1-9][0-9]*$ && $jobs -le 4 ]] || exit 1
[[ -f "$sim_root/docker/Dockerfile_x64_gazebo" ]] || { echo 'Missing Go2 simulation source.' >&2; exit 1; }
docker info >/dev/null
mkdir -p "$work_root/sim-context" "$work_root/logs"
/usr/bin/python3 - "$sim_root" "$work_root" "$jobs" <<'PY'
from pathlib import Path
import shutil, sys
source, work, jobs = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
context = work / 'sim-context'
shutil.copytree(source, context / 'simulator', dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))
text = (source / 'docker/Dockerfile_x64_gazebo').read_text()
separator = " " + chr(92) + chr(10)
old = separator.join([
    'git clone --branch humble https://github.com/anujjain-dev/unitree-go2-ros2.git /ws_gz/src/unitree-go2-ros2',
    '    && git -C /ws_gz/src/unitree-go2-ros2 checkout --detach "${UPSTREAM_COMMIT}"',
])
sys.path.insert(0, str(work.parent.parent / 'shared/dddmr'))
from archive_cache import stage_archive
stage_archive(work, context, 'go2-fdac259.tar.gz', 'fdac259518930c8f03e79189c4d0fdd00fc47483')
new = ('tar -xzf /tmp/go2-fdac259.tar.gz -C /ws_gz/src/unitree-go2-ros2 --strip-components=1')
assert old in text, 'Upstream Go2 fetch recipe changed.'
text = text.replace(old, 'mkdir -p /ws_gz/src/unitree-go2-ros2 && ' + new)
text = text.replace('RUN mkdir -p /ws_gz/src', 'COPY sources/go2-fdac259.tar.gz /tmp/go2-fdac259.tar.gz\nRUN mkdir -p /ws_gz/src', 1)
start = text.index('ARG SIMULATOR_REF=go2')
end = text.index('\nWORKDIR /ws_gz', start)
text = text[:start] + 'COPY simulator/ /opt/dfl_mobilerobot_simulator/\nRUN bash /opt/dfl_mobilerobot_simulator/scripts/apply_go2_changes.bash /ws_gz/src/unitree-go2-ros2\n' + text[end:]
text = text.replace('FROM ros:humble\n', "FROM ros:humble\nRUN sed -i -e 's|http://archive.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' -e 's|http://security.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' /etc/apt/sources.list\n")
text = text.replace('/etc/apt/sources.list\n', "/etc/apt/sources.list\nRUN sed -i -e 's|http://packages.ros.org/ros2/ubuntu|http://mirrors.ustc.edu.cn/ros2/ubuntu|g' -e 's/ deb-src//g' /etc/apt/sources.list.d/ros2.sources\n", 1)
text = text.replace('&& colcon build --symlink-install', '&& MAKEFLAGS=-j' + jobs + ' CMAKE_BUILD_PARALLEL_LEVEL=' + jobs + ' colcon build --parallel-workers ' + jobs + ' --symlink-install')
(context / 'Dockerfile').write_text(text)
PY
docker build --network host --progress=plain -t dddmr-sim:go2-local "$work_root/sim-context" 2>&1 |
  tee "$work_root/logs/simulation-image.log"
