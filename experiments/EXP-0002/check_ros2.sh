#!/usr/bin/env bash
set -euo pipefail

for package in unitree_api unitree_go unitree_hg; do
  ros2 pkg prefix "$package"
done

ros2 interface show unitree_api/msg/Request
ros2 interface show unitree_go/msg/SportModeState

if [[ ${1:-} == --robot ]]; then
  ros2 topic list -t --no-daemon
  timeout 10s ros2 topic echo /sportmodestate unitree_go/msg/SportModeState --once
fi
