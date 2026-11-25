import json,struct,time
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2
rclpy.init()
node=rclpy.create_node('readonly_cloud_transform_check')
pending={}; pairs=[]
def receive(msg,key):
 stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
 fields={f.name:f.offset for f in msg.fields}
 a={}
 endian='>' if msg.is_bigendian else '<'
 for i in range(msg.width):
  o=i*msg.point_step
  t=struct.unpack_from(endian+'f',msg.data,o+fields['time'])[0]
  v=struct.unpack_from(endian+'f',msg.data,o+fields['intensity'])[0]
  p=[struct.unpack_from(endian+'f',msg.data,o+fields[k])[0] for k in 'xyz']
  if np.isfinite(p).all():a[t,v]=p
 pending[key,stamp]=a
 other=pending.get((1-key,stamp))
 if other is not None:
  raw,base=(a,other) if key==0 else (other,a)
  pairs.extend((raw[k],base[k]) for k in raw.keys()&base.keys())
 if len(pending)>100: pending.pop(next(iter(pending)))
subs=[node.create_subscription(PointCloud2,n,lambda m,k=i:receive(m,k),qos_profile_sensor_data) for i,n in enumerate(['/utlidar/cloud','/utlidar/cloud_base'])]
end=time.monotonic()+5
while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.1)
a,b=np.asarray(pairs).transpose(1,0,2)
u,sv,vt=np.linalg.svd((a-a.mean(0)).T@(b-b.mean(0)))
R=vt.T@np.diag([1,1,np.linalg.det(vt.T@u.T)])@u.T
t=b.mean(0)-R@a.mean(0)
print(json.dumps({'pairs':len(a),'rotation_matrix':R.tolist(),'translation_m':t.tolist(),'median_error_m':float(np.median(np.linalg.norm(a@R.T+t-b,axis=1)))}))
node.destroy_node();rclpy.shutdown()
