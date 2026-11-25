#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
work="$root/.work/dddmr-real"
revision=a8e2d0d5090af97ead8dd4fac3d37cf3dbb33ff7
src="$work/ws/src/point_lio"
mkdir -p "$work/ws/src"
if [[ ! -f "$src/.source-revision" ]]; then
  staging=$(mktemp -d "$work/source.XXXXXX")
  trap 'rm -rf -- "$staging"' EXIT
  git init -q "$staging/point_lio"
  git -C "$staging/point_lio" remote add origin https://github.com/dfloreaa/point_lio_ros2.git
  git -C "$staging/point_lio" config remote.origin.promisor true
  git -C "$staging/point_lio" config remote.origin.partialclonefilter blob:none
  git -C "$staging/point_lio" fetch --depth 1 --filter=blob:none origin "$revision"
  git -C "$staging/point_lio" sparse-checkout set config include launch rviz_cfg src
  git -C "$staging/point_lio" checkout --detach "$revision"
  git -C "$staging/point_lio" restore --source=HEAD --ignore-skip-worktree-bits -- CMakeLists.txt package.xml LICENSE Log PCD
  printf '%s\n' "$revision" > "$staging/point_lio/.source-revision"
  mv -T "$staging/point_lio" "$src"
fi
[[ $(cat "$src/.source-revision") == "$revision" ]]
/usr/bin/python3 "$root/shared/dddmr/real/patch_point_lio.py" "$src"
docker build --network host -t dddmr-point-lio:go2-local -f "$root/shared/dddmr/real/Dockerfile" "$root/shared/dddmr/real"
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env MAKEFLAGS=-j2 --env CMAKE_BUILD_PARALLEL_LEVEL=2 \
  --mount "type=bind,src=$work/ws,dst=/lio-ws" --workdir /lio-ws \
  dddmr-point-lio:go2-local bash -ec '
    source /opt/ros/humble/setup.bash
    colcon build --packages-select point_lio --parallel-workers 1 \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=17
  '
test -x "$work/ws/install/point_lio/lib/point_lio/pointlio_mapping"
