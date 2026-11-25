"""Stationary replay diagnostic: group per-point updates in 5ms bins."""
import rosbag2_py,numpy as np
from rclpy.serialization import deserialize_message,serialize_message
from sensor_msgs.msg import PointCloud2
base='experiments/EXP-0024/'
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri=base+'standing-three-sensors',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
w=rosbag2_py.SequentialWriter();w.open(rosbag2_py.StorageOptions(uri=base+'scanbatch-trial',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
for x in r.get_all_topics_and_types():
 if x.name!='/go2/bodytrial/imu':w.create_topic(x)
while r.has_next():
 name,b,s=r.read_next()
 if name=='/go2/bodytrial/imu':continue
 if name.endswith('/cloud'):
  m=deserialize_message(b,PointCloud2);data=bytearray(m.data);off=next(f.offset for f in m.fields if f.name=='time');t=np.ndarray((m.width,),'<f4',buffer=data,offset=off,strides=(m.point_step,));t[:]=0.;m.data=bytes(data);b=serialize_message(m)
 w.write(name,b,s)
