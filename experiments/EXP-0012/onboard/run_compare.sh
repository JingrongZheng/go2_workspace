#!/usr/bin/env bash
set -eo pipefail
run_dir="$HOME/go2-lidar-diagnostic/retest-20261121"
mkdir -p "$run_dir"
exec > >(tee "$run_dir/summary.log") 2>&1
printf 'Snapshot before testing\n'
date -Is
ps -eo pid,ppid,args | grep -E '[h]esai_lidar_node|[h]esai_ros_driver_node|[U]nitreeSlam' || true
if pgrep -f '^(/[^ ]*/)?(hesai_lidar_node|hesai_ros_driver_node|UnitreeSlam)( |$)' >/dev/null; then
  echo 'Existing driver detected; abort without stopping it.'
  exit 3
fi
if ss -H -lun | awk '{print $4}' | grep -Eq ':(2368|10110)$'; then
  echo 'Sensor port occupied; abort.'
  exit 4
fi
/usr/bin/python3 - <<'UDP'
import socket,time,collections,json
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.bind(('0.0.0.0',2368));s.settimeout(0.5)
counts=collections.Counter();end=time.monotonic()+12
while time.monotonic()<end:
    try:
        data,addr=s.recvfrom(65535);counts[(addr[0],addr[1],len(data))]+=1
    except socket.timeout: pass
s.close()
print('UDP_BASELINE_12S '+json.dumps([[*key,n] for key,n in counts.items()]),flush=True)
UDP
for variant in old new; do
  echo "BEGIN $variant"
  env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin LANG=C.UTF-8 \
    VARIANT="$variant" TEST_DIR="$run_dir" \
    bash --noprofile --norc "$run_dir/one_variant.sh"
  echo "END $variant"
  ss -lun | grep -E ':(2368|10110) ' || true
  if ss -H -lun | awk '{print $4}' | grep -Eq ':(2368|10110)$'; then
    echo 'Sensor port still occupied; stop comparison.'; exit 5
  fi
done
printf 'Snapshot after testing\n'
ps -eo pid,ppid,args | grep -E '[h]esai_lidar_node|[h]esai_ros_driver_node|[U]nitreeSlam' || true
