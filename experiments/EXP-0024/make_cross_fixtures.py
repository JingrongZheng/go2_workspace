"""Diagnostic crossed fixtures only; these are not physical recordings."""
import rosbag2_py,copy,numpy as np
from rclpy.serialization import deserialize_message,serialize_message
from sensor_msgs.msg import Imu,PointCloud2
from pathlib import Path
base=Path('experiments/EXP-0024')
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri=str(base/'standing-three-sensors'),storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
rows=[];firstcloud=None;accs=[]
while r.has_next():
 name,b,stamp=r.read_next()
 if name not in ['/go2/bodytrial/cloud','/go2/bodytrial/lidar_imu']:continue
 m=deserialize_message(b,PointCloud2 if name.endswith('/cloud') else Imu)
 if name.endswith('/cloud') and firstcloud is None:firstcloud=copy.deepcopy(m)
 if name.endswith('/lidar_imu'):accs.append([m.linear_acceleration.x,m.linear_acceleration.y,m.linear_acceleration.z])
 rows.append((name,m,stamp))
a=np.median(accs,axis=0);a*=9.81/np.linalg.norm(a)
for trial in ['real-cloud-constant-imu','constant-cloud-real-imu']:
 w=rosbag2_py.SequentialWriter();w.open(rosbag2_py.StorageOptions(uri=str(base/trial),storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
 for name,typ in [('/go2/bodytrial/cloud','sensor_msgs/msg/PointCloud2'),('/go2/bodytrial/lidar_imu','sensor_msgs/msg/Imu')]:w.create_topic(rosbag2_py.TopicMetadata(name=name,type=typ,serialization_format='cdr'))
 for name,original,stamp in rows:
  m=copy.deepcopy(original)
  if trial=='real-cloud-constant-imu' and name.endswith('/lidar_imu'):
   m.angular_velocity.x=m.angular_velocity.y=m.angular_velocity.z=0.
   m.linear_acceleration.x,m.linear_acceleration.y,m.linear_acceleration.z=map(float,a)
  if trial=='constant-cloud-real-imu' and name.endswith('/cloud'):
   m=copy.deepcopy(firstcloud);m.header=original.header
  w.write(name,serialize_message(m),stamp)
 del w
 s=Path('.work/go2-standing-lidar-check.sh').read_text().replace('standing-three-sensors',trial).replace('standing-lidar-replay.log',trial+'-replay.log').replace('inspect_standing_lidar.py','inspect_'+trial.replace('-','_')+'.py')
 s=s.replace("kill -INT", "kill -TERM").replace('; wait "$pid" || true', '; sleep 1; kill -KILL "$pid" 2>/dev/null || true')
 Path('.work/go2-'+trial+'-check.sh').write_text(s)
 s=(base/'inspect_standing_lidar.py').read_text().replace('standing-lidar',trial).replace('time.monotonic()+20','time.monotonic()+26')
 (base/('inspect_'+trial.replace('-','_')+'.py')).write_text(s)
