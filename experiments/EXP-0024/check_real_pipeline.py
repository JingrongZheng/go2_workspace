"""Read-only static integration check of shared launch, odometry and TF."""
import json,time,numpy as np,rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from scipy.spatial.transform import Rotation
from tf2_ros import Buffer,TransformListener
rclpy.init();node=Node('check_real_static_pipeline');buffer=Buffer();listener=TransformListener(buffer,node);poses=[];clouds=[]
def odom(m):
 p=m.pose.pose.position;q=m.pose.pose.orientation;poses.append([p.x,p.y,p.z,q.x,q.y,q.z,q.w])
def cloud(m):
 f={x.name:x.offset for x in m.fields};p=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1);clouds.append(p[np.isfinite(p).all(1)])
subs=[node.create_subscription(Odometry,'/odom',odom,100),node.create_subscription(PointCloud2,'/cloud_registered',cloud,10)]
end=time.monotonic()+37
while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.1)
result={'poses':len(poses),'clouds':len(clouds)}
if poses:
 a=np.array(poses);result.update({'xyz_range_m':np.ptp(a[:,:3],axis=0).tolist(),'first_rpy_deg':Rotation.from_quat(a[0,3:]).as_euler('xyz',degrees=True).tolist(),'last_rpy_deg':Rotation.from_quat(a[-1,3:]).as_euler('xyz',degrees=True).tolist(),'body_z_world':Rotation.from_quat(a[-1,3:]).apply([0,0,1]).tolist()})
 np.save('/results/shared-profile-body-poses.npy',a)
if clouds:
 p=np.concatenate(clouds)[::5];np.save('/results/shared-profile-registered.npy',p);p=p[np.linalg.norm(p,axis=1)<6];rng=np.random.default_rng(43);best=None
 for _ in range(500):
  p0,p1,p2=p[rng.choice(len(p),3,replace=False)];n=np.cross(p1-p0,p2-p0);l=np.linalg.norm(n)
  if l<1e-8:continue
  n/=l
  if abs(n[2])<.95:continue
  if n[2]<0:n=-n
  d=-n@p0;mask=np.abs(p@n+d)<.025
  if best is None or mask.sum()>best[0]:best=(int(mask.sum()),n,d)
 if best:result['dominant_horizontal_plane']={'inliers':best[0],'normal':best[1].tolist(),'offset':float(best[2]),'tilt_deg':float(np.rad2deg(np.arccos(best[1][2])))}
result['tf']={}
for frame in ['base_link','go2_chassis_imu','radar','utlidar_lidar','lidar_link']:
 try:
  t=buffer.lookup_transform('odom',frame,rclpy.time.Time());q=t.transform.rotation;p=t.transform.translation;result['tf'][frame]={'xyz':[p.x,p.y,p.z],'quaternion_xyzw':[q.x,q.y,q.z,q.w]}
 except Exception as e:result['tf'][frame]={'error':str(e)}
print(json.dumps(result,indent=2));open('/results/shared-profile-check.json','w').write(json.dumps(result,indent=2)+'\n')
node.destroy_node();rclpy.shutdown()
assert len(poses)>100,'Insufficient odometry'
assert max(result['xyz_range_m'])<.1,'Static position drift exceeds 10cm'
assert result['body_z_world'][2]>.95,'Body frame points downward or tilts excessively'
assert 'dominant_horizontal_plane' in result and result['dominant_horizontal_plane']['tilt_deg']<5,'Floor/map orientation inconsistent'
assert all('error' not in x for x in result['tf'].values()),'TF chain missing'
