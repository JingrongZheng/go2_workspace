"""Offline comparison using CMU's gyro-only IMU treatment and measured cloud axes."""
import json
from pathlib import Path
import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message,serialize_message
from rosidl_runtime_py.utilities import get_message
base=Path(__file__).parent
geo=json.loads((base.parent/'EXP-0022/imu-axis-check.json').read_text())['cloud_to_firmware_base']
R=np.array(geo['rotation_matrix']); t=np.array(geo['translation_m'])
reader=rosbag2_py.SequentialReader();writer=rosbag2_py.SequentialWriter()
reader.open(rosbag2_py.StorageOptions(uri=str(base.parent/'EXP-0023/auto-aligned-v2'),storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
writer.open(rosbag2_py.StorageOptions(uri=str(base/'gyro-trial-bag'),storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
types={}
for x in reader.get_all_topics_and_types():
 types[x.name]=get_message(x.type)
 writer.create_topic(x)
while reader.has_next():
 name,raw,stamp=reader.read_next();msg=deserialize_message(raw,types[name])
 msg.header.frame_id='base_link'
 if name.endswith('/cloud'):
  data=bytearray(msg.data);f={x.name:x.offset for x in msg.fields}
  arrays=[np.ndarray((msg.width,),'<f4',buffer=data,offset=f[k],strides=(msg.point_step,)) for k in 'xyz']
  points=np.stack(arrays,1)@R.T+t
  for axis,array in enumerate(arrays):array[:]=points[:,axis]
  msg.data=bytes(data)
 else:
  g=msg.angular_velocity
  g.x,g.y,g.z=map(float,R@np.array([g.x,g.y,g.z]))
  msg.linear_acceleration.x=msg.linear_acceleration.y=msg.linear_acceleration.z=0.
  msg.orientation.x=msg.orientation.y=msg.orientation.z=0.;msg.orientation.w=1.
 writer.write(name,serialize_message(msg),stamp)
