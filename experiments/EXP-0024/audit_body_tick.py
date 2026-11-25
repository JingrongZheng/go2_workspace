import json,shlex,subprocess
from pathlib import Path
source='''import time,json,rclpy
from unitree_go.msg import LowState
from rclpy.qos import qos_profile_sensor_data
rclpy.init();n=rclpy.create_node("body_tick_audit");rows=[]
def cb(m):rows.append([int(m.tick),time.time_ns()])
s=n.create_subscription(LowState,"/lowstate",cb,qos_profile_sensor_data);end=time.monotonic()+4
while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.1)
print(json.dumps(rows));n.destroy_node();rclpy.shutdown()
'''
setup='source /opt/ros/foxy/setup.bash >&2; source ~/cyclonedds_ws/install/local_setup.bash >&2; source /unitree/module/graph_pid_ws/install/unitree_go/share/unitree_go/local_setup.bash >&2; export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; export CYCLONEDDS_URI='+shlex.quote('<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth10</NetworkInterfaceAddress></General></Domain></CycloneDDS>')+'; /usr/bin/python3 -c '+shlex.quote(source)
r=subprocess.run(['ssh','-T','-S','/home/suiliang/go2_workspace/.work/ssh-control/go2-wifi-new.sock','-o','BatchMode=yes','unitree@192.168.110.87','bash -c '+shlex.quote(setup)],capture_output=True,text=True,timeout=15)
Path('experiments/EXP-0024/body-tick-audit.json').write_text(r.stdout);Path('experiments/EXP-0024/body-tick-audit.stderr').write_text(r.stderr)
rows=json.loads(r.stdout);d=[(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(rows,rows[100:]) if b[0]>a[0]];d.sort();print({'samples':len(rows),'tick_range':[rows[0][0],rows[-1][0]],'ns_per_tick_median':d[len(d)//2]})
