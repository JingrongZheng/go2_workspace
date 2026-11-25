#!/usr/bin/env bash
# Read-only inventory. Run on the expansion computer; no driver/SLAM launch.
set -u
echo '=== Host and network ==='
uname -a
ip -br addr
ip route
ip neigh
echo '=== Installed packages ==='
dpkg-query -W -f='${Package} ${Version}\n' 2>/dev/null | 
  grep -Ei 'hesai|pandar|xt16|lidar|unitree|slam' || true
echo '=== Existing driver and configuration paths (bounded depth) ==='
find /home/unitree /opt /usr/local /etc/systemd/system -maxdepth 5 \
  \( -name .cache -o -name node_modules -o -name .git \) -prune -o \
  \( -iname '*hesai*' -o -iname '*pandar*' -o -iname '*xt16*' \) -print \
  2>/dev/null | head -n 150
echo '=== Processes ==='
ps -eo pid,etime,args | grep -Ei '[h]esai|[p]andar|[x]t16|[l]idar|[s]lam' | head -n 60
echo '=== Services ==='
systemctl list-units --all --no-pager --plain 2>/dev/null | 
  grep -Ei 'hesai|pandar|xt16|lidar|slam|unitree' || true
systemctl list-unit-files --no-pager 2>/dev/null | 
  grep -Ei 'hesai|pandar|xt16|lidar|slam|unitree' || true
echo '=== UDP listeners ==='
ss -ulnp
echo '=== ROS packages in clean subshells (no nodes started) ==='
if [[ -f /opt/ros/foxy/setup.bash ]]; then
  env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 \
    /bin/bash --noprofile --norc -c \
    'source /opt/ros/foxy/setup.bash; ros2 pkg list | grep -Ei "hesai|pandar|xt16|lidar|slam|unitree"' || true
fi
if [[ -f /opt/ros/noetic/setup.bash ]]; then
  env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 \
    /bin/bash --noprofile --norc -c \
    'source /opt/ros/noetic/setup.bash; rospack list | grep -Ei "hesai|pandar|xt16|lidar|slam|unitree"' || true
fi
echo '=== Matching boot logs (limited to current user permissions) ==='
journalctl -b --no-pager -n 1200 -o short-monotonic 2>/dev/null | 
  grep -Ei 'hesai|pandar|xt16|lidar|slam' | tail -n 100 || true
echo 'DONE. Absence here does not exclude a custom workspace, container, or renamed vendor binary.'
