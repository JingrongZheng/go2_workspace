"""Observe offline dynamic replay. It never publishes robot control."""
import json,time,os,numpy as np,rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from scipy.spatial.transform import Rotation
from tf2_ros import Buffer,TransformListener
rclpy.init();node=Node('inspect_real_motion');buffer=Buffer();listener=TransformListener(buffer,node);poses=[];clouds=[]
def odom(m):
 p=m.pose.pose.position;q=m.pose.pose.orientation
 poses.append([m.header.stamp.sec+m.header.stamp.nanosec*1e-9,p.x,p.y,p.z,q.x,q.y,q.z,q.w])
def cloud(m):
 f={x.name:x.offset for x in m.fields};p=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1)
 clouds.append(p[np.isfinite(p).all(1)][::3])
subs=[node.create_subscription(Odometry,'/odom',odom,100),node.create_subscription(PointCloud2,'/cloud_registered',cloud,10)]
end=time.monotonic()+float(os.environ.get('MOTION_OBSERVE_SECONDS','125'))
while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.1)
result={'poses':len(poses),'clouds':len(clouds)}
if poses:
 a=np.array(poses);r=Rotation.from_quat(a[:,4:]);rpy=r.as_euler('xyz',degrees=True);relative=a[:,1:4]-a[0,1:4]
 result.update({'duration_s':float(a[-1,0]-a[0,0]),'xyz_range_m':np.ptp(a[:,1:4],axis=0).tolist(),'max_displacement_m':float(np.linalg.norm(relative,axis=1).max()),'last_displacement_m':float(np.linalg.norm(relative[-1])),'first_rpy_deg':rpy[0].tolist(),'last_rpy_deg':rpy[-1].tolist(),'minimum_body_z_up':float(r.apply(np.tile([0.,0.,1.],(len(a),1)))[:,2].min())})
 for label,mask in [('initial',a[:,0]<a[0,0]+3),('final',a[:,0]>a[-1,0]-5)]:
  result[label+'_position_range_m']=np.ptp(a[mask,1:4],axis=0).tolist()
 np.save('/results/motion-body-poses.npy',a)
if clouds:np.save('/results/motion-registered.npy',np.concatenate(clouds))
result['tf']={}
for frame in ['base_link','go2_chassis_imu','radar','utlidar_lidar','lidar_link']:
 try:
  t=buffer.lookup_transform('odom',frame,rclpy.time.Time());q=t.transform.rotation;p=t.transform.translation;result['tf'][frame]={'xyz':[p.x,p.y,p.z],'quaternion_xyzw':[q.x,q.y,q.z,q.w]}
 except Exception as e:result['tf'][frame]={'error':str(e)}
open('/results/motion-pipeline-check.json','w').write(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));node.destroy_node();rclpy.try_shutdown()
assert len(poses)>100,'Insufficient odometry'
assert result['minimum_body_z_up']>.8,'Body frame flipped or tilted excessively'
assert all('error' not in x for x in result['tf'].values()),'TF chain missing'
