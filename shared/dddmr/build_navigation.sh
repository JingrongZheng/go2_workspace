#!/usr/bin/env bash
# Build the navigation image/workspace after setup_docker.sh has completed.
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source_root=${DDDMR_SOURCE:-"$project_root/dddmr_navigation-main(1)/dddmr_navigation-main"}
work_root="$project_root/.work/dddmr-local"
jobs=${DDDMR_BUILD_JOBS:-2}
phase=${DDDMR_BUILD_PHASE:-all}
[[ $phase == all || $phase == gtsam ]] || { echo 'Unknown build phase.' >&2; exit 1; }
[[ $jobs =~ ^[1-9][0-9]*$ && $jobs -le 4 ]] || { echo 'Build jobs must be 1..4.' >&2; exit 1; }
[[ -f "$source_root/dddmr_docker/docker_file/Dockerfile_x64" ]] || {
  echo "Missing DDDMR source: $source_root" >&2; exit 1;
}
command -v docker >/dev/null || { echo 'Run setup_docker.sh first.' >&2; exit 1; }
docker info >/dev/null
mkdir -p "$work_root/build-context/pkgs" "$work_root/navigation-ws" "$work_root/logs"
cp "$source_root/dddmr_docker/docker_file/pkgs/serial-foxy.zip" "$work_root/build-context/pkgs/"
/usr/bin/python3 - "$source_root" "$work_root" "$jobs" "$phase" <<'PY'
from pathlib import Path
import sys
source, work, jobs = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
phase = sys.argv[4]
text = (source / 'dddmr_docker/docker_file/Dockerfile_x64').read_text()
if phase == 'gtsam':
    text = text.split('# --- PCL ---', 1)[0]
assert '-j$(nproc)' in text, 'Upstream Dockerfile changed: inspect build parallelism first.'
text = text.replace('-j$(nproc)', '-j' + jobs)
sys.path.insert(0, str(work.parent.parent / 'shared/dddmr'))
from archive_cache import stage_archive
for repo, tag, archive in [
    ('borglab/gtsam', '4.2a9', 'gtsam-4.2a9.tar.gz'),
    ('PointCloudLibrary/pcl', 'pcl-1.15.0', 'pcl-1.15.0.tar.gz'),
    ('koide3/small_gicp', 'v1.0.1', 'small_gicp-v1.0.1.tar.gz'),
    ('AprilRobotics/apriltag', '3806edf38ac4400153677e510c9f9dcb81f472c8', 'apriltag-3806edf.tar.gz'),
]:
    folder = repo.split('/')[-1]
    old = f'RUN cd /tmp && git clone https://github.com/{repo}.git && cd {folder} && git checkout {tag}'
    if phase == 'gtsam' and old not in text:
        continue
    # PCL's official release archive has no Git pax header; use its published checksum.
    checksum = ('fb79d085b08b8335f43ee4cacf4daa2624bb2c411e9243efa6a92c077273840a'
                if archive == 'pcl-1.15.0.tar.gz' else None)
    stage_archive(work, work / 'build-context', archive, expected_sha256=checksum)
    new = (f'COPY sources/{archive} /tmp/{archive}\n'
           f'RUN mkdir -p /tmp/{folder} && tar -xzf /tmp/{archive} -C /tmp/{folder} --strip-components=1 && cd /tmp/{folder}')
    assert old in text, f'Upstream dependency recipe changed: {repo}'
    text = text.replace(old, new)
text = text.replace('http://packages.ros.org/ros2/ubuntu', 'http://mirrors.ustc.edu.cn/ros2/ubuntu')
lines = []
for line in text.splitlines():
    for folder in ['gtsam', 'pcl', 'small_gicp', 'apriltag']:
        if line.startswith('RUN ') and f'cd /tmp/{folder} ' in line and ('make install' in line or '--target install' in line):
            line += f' && rm -rf /tmp/{folder}/build'
    lines.append(line)
text = '\n'.join(lines) + '\n'
mirror = "RUN sed -i -e 's|http://archive.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' -e 's|http://security.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' /etc/apt/sources.list\n"
text = text.replace('FROM ubuntu:22.04\n', 'FROM ubuntu:22.04\n' + mirror, 1)
(work / 'build-context/Dockerfile').write_text(text)
PY
if [[ $phase == gtsam ]]; then
  docker build --network host --progress=plain -t dddmr-gtsam-stage:go2-local "$work_root/build-context" 2>&1 |
    tee "$work_root/logs/gtsam-stage.log"
  exit 0
fi
docker build --network host --progress=plain -t dddmr:go2-local "$work_root/build-context" 2>&1 |
  tee "$work_root/logs/navigation-image.log"
# The upstream source is read-only. Outputs belong only to this experiment workspace.
docker run --rm --network host \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$work_root/navigation-ws,dst=/outputs" \
  --env "BUILD_JOBS=$jobs" --env "MAKEFLAGS=-j$jobs" \
  --env "CMAKE_BUILD_PARALLEL_LEVEL=$jobs" \
  --env "HOST_UID=$(id -u)" --env "HOST_GID=$(id -g)" \
  dddmr:go2-local bash --noprofile --norc -c '
    set -e
    source /opt/ros/humble/setup.bash
    cd /outputs
    trap '\''chown -R "$HOST_UID:$HOST_GID" /outputs'\'' EXIT
    colcon --log-base /outputs/log build \
      --base-paths /ws/src/dddmr_navigation/src \
      --build-base /outputs/build --install-base /outputs/install \
      --symlink-install --parallel-workers "$BUILD_JOBS" \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DTRT_ENABLED=OFF -DTEST_ENABLED=OFF
  ' 2>&1 | tee "$work_root/logs/navigation-build.log"
