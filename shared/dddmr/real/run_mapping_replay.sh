#!/usr/bin/env bash
# One isolated container: recorded sensors -> LIO -> DDDMR -> saved pose graph.
set -euo pipefail
if [[ $# != 4 ]]; then
  echo "Usage: $0 BAG_DIRECTORY PARAMETERS_YAML GROUND_Z NEW_OUTPUT_DIRECTORY" >&2
  exit 2
fi
real=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$real/../../.." && pwd)
bag=$(realpath -e -- "$1")
params=$(realpath -e -- "$2")
[[ -f "$bag/metadata.yaml" && -f "$params" ]]
output=$(realpath -m -- "$4")
if [[ -e "$output" ]] && [[ -n $(ls -A -- "$output") ]]; then
  echo "Output directory is not empty; preserve it and choose another directory." >&2
  exit 2
fi
source_root=$(realpath -e -- "${DDDMR_SOURCE:-$root/dddmr_navigation-main(1)/dddmr_navigation-main}")
duration=$(/usr/bin/python3 - "$bag/metadata.yaml" "$3" <<'PY'
import math,sys,yaml
metadata=yaml.safe_load(open(sys.argv[1]))['rosbag2_bagfile_information']
if not math.isfinite(float(sys.argv[2])):
    raise ValueError('Ground height must be finite')
print(metadata['duration']['nanoseconds'] / 1e9 + 12.)
PY
)
mkdir -p "$output/maps" "$output/lio-debug"
cp -- "$params" "$output/parameters.yaml"
cp -- "$real/go2_published_cloud_geometry.json" "$real/go2_nominal_geometry.json" "$output/"
printf '%s\n' "$bag" > "$output/input-bag-path.txt"
exec docker run --rm --init --network none --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env ROS_DOMAIN_ID=84 --env ROS_LOCALHOST_ONLY=1 \
  --env DDDMR_MAPPING_DIR=/session/maps/ \
  --mount "type=bind,src=$root/.work/dddmr-real/ws,dst=/lio-ws,readonly" \
  --mount "type=bind,src=$output/lio-debug,dst=/lio-ws/src/point_lio/Log" \
  --mount "type=bind,src=$root/.work/dddmr-local/navigation-ws,dst=/outputs,readonly" \
  --mount "type=bind,src=$source_root,dst=/ws/src/dddmr_navigation,readonly" \
  --mount "type=bind,src=$real,dst=/go2-real,readonly" \
  --mount "type=bind,src=$bag,dst=/recorded-bag,readonly" \
  --mount "type=bind,src=$output,dst=/session" \
  dddmr-point-lio:go2-local bash -ec '
    source /opt/ros/humble/setup.bash
    source /outputs/install/setup.bash
    source /lio-ws/install/local_setup.bash
    ros2 launch /go2-real/go2_live_mapping.launch.py parameters:=/session/parameters.yaml \
      "ground_z:=$1" >/session/stack.log 2>&1 &
    stack=$!
    trap '\''kill -TERM "$stack" 2>/dev/null || true; sleep 2; kill -KILL "$stack" 2>/dev/null || true'\'' EXIT
    ros2 bag play /recorded-bag --delay 5 --topics /go2/relay/cloud /go2/relay/chassis_imu >/session/player.log 2>&1 &
    /usr/bin/python3 /go2-real/mapping_session.py --duration "$2"
  ' bash "$3" "$duration"
