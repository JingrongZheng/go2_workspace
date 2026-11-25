"""Synthetic stationary integration fixture; never used as real robot odometry."""
import rosbag2_py,copy,numpy as np
from rclpy.serialization import deserialize_message,serialize_message
from sensor_msgs.msg import Imu,PointCloud2
base='experiments/EXP-0024/'
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri=base+'standing-three-sensors',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
c=i=None
while r.has_next() and (c is None or i is None):
 t,b,s=r.read_next()
 if t.endswith('/cloud'):c=deserialize_message(b,PointCloud2)
 if t.endswith('/lidar_imu'):i=deserialize_message(b,Imu)
i.angular_velocity.x=i.angular_velocity.y=i.angular_velocity.z=0.
a=np.array([i.linear_acceleration.x,i.linear_acceleration.y,i.linear_acceleration.z]);a*=9.81/np.linalg.norm(a)
i.linear_acceleration.x,i.linear_acceleration.y,i.linear_acceleration.z=map(float,a)
w=rosbag2_py.SequentialWriter();w.open(rosbag2_py.StorageOptions(uri=base+'static-fixture',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
for name,typ in [('/go2/bodytrial/cloud','sensor_msgs/msg/PointCloud2'),('/go2/bodytrial/lidar_imu','sensor_msgs/msg/Imu')]:w.create_topic(rosbag2_py.TopicMetadata(name=name,type=typ,serialization_format='cdr'))
start=1700000000000000000
for n in range(3000):
 ns=start+n*4000000;i.header.stamp.sec=ns//1000000000;i.header.stamp.nanosec=ns%1000000000;w.write('/go2/bodytrial/lidar_imu',serialize_message(i),ns)
 if n%17==0:
  c.header.stamp=i.header.stamp;w.write('/go2/bodytrial/cloud',serialize_message(c),ns)
