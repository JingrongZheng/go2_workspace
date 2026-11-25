import rosbag2_py,numpy as np,json
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import Imu
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0024/standing-three-sensors',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
a={}
while r.has_next():
 t,b,stamp=r.read_next()
 if t.endswith('/imu') or t.endswith('/lidar_imu'):
  m=deserialize_message(b,Imu);g=m.angular_velocity;x=m.linear_acceleration
  a.setdefault(t,[]).append([m.header.stamp.sec+m.header.stamp.nanosec*1e-9,g.x,g.y,g.z,x.x,x.y,x.z])
out={}
for t,v in a.items():
 v=np.array(v);out[t]={'n':len(v),'dt_quantiles':np.quantile(np.diff(v[:,0]),[0,.01,.5,.99,1]).tolist(),'median_gyro_acc':np.median(v[:,1:],axis=0).tolist(),'range_gyro_acc':np.ptp(v[:,1:],axis=0).tolist(),'std_gyro_acc':np.std(v[:,1:],axis=0).tolist()}
print(json.dumps(out,indent=2))
