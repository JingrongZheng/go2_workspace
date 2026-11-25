import json,numpy as np,rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0024/motion-trial-01',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''));types={x.name:get_message(x.type) for x in r.get_all_topics_and_types()};rows={};imu=[]
while r.has_next():
 name,b,rec=r.read_next();m=deserialize_message(b,types[name]);t=m.header.stamp.sec*10**9+m.header.stamp.nanosec;rows.setdefault(name,[]).append([t,rec-t])
 if name.endswith('/chassis_imu'):
  g=m.angular_velocity;a=m.linear_acceleration;imu.append([t*1e-9,g.x,g.y,g.z,a.x,a.y,a.z])
out={}
for n,a in rows.items():
 a=np.array(a,dtype=np.int64);dt=np.diff(a[:,0]);out[n]={'samples':len(a),'header_duration_s':float((a[-1,0]-a[0,0])*1e-9),'nonincreasing':int((dt<=0).sum()),'dt_ms_quantiles':np.quantile(dt*1e-6,[0,.5,.95,.99,1]).tolist(),'record_minus_header_ms_quantiles':np.quantile(a[:,1]*1e-6,[.01,.5,.95,.99]).tolist()}
a=np.array(imu);np.save('experiments/EXP-0024/motion-chassis-imu.npy',a);out['chassis_gyro_norm_max_rad_s']=float(np.linalg.norm(a[:,1:4],axis=1).max());out['chassis_acceleration_range_m_s2']=np.ptp(a[:,4:],axis=0).tolist()
open('experiments/EXP-0024/motion-input-audit.json','w').write(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
