import json,time
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from nav_msgs.msg import Odometry
from scipy.spatial.transform import Rotation
rclpy.init()
node=Node('inspect_lio_outputs')
clouds=[]; poses=[]
def cloud(msg):
 f={x.name:x.offset for x in msg.fields}
 a=np.stack([np.ndarray((msg.width,),'<f4',buffer=msg.data,offset=f[k],strides=(msg.point_step,)) for k in 'xyz'],1)
 clouds.append(a[np.isfinite(a).all(1)])
def odom(msg):
 q=msg.pose.pose.orientation;p=msg.pose.pose.position
 poses.append([p.x,p.y,p.z,q.x,q.y,q.z,q.w])
subs=[node.create_subscription(PointCloud2,'/cloud_registered',cloud,10),node.create_subscription(Odometry,'/aft_mapped_to_init',odom,10)]
end=time.monotonic()+26
while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.1)
if clouds:
 pts=np.concatenate(clouds)[::5]
 np.save('/results/cube-valid-body-original-plane-registered.npy',pts)
 print('xyz_quantiles',np.quantile(pts,[.01,.1,.5,.9,.99],axis=0).tolist())
if poses:
 a=np.array(poses)
 print(json.dumps({'poses':len(a),'first':a[0].tolist(),'last':a[-1].tolist(),'xyz_range':np.ptp(a[:,:3],axis=0).tolist(),'first_rpy_deg':Rotation.from_quat(a[0,3:]).as_euler('xyz',degrees=True).tolist()}))
 np.save('/results/cube-valid-body-original-plane-poses.npy',a)
else:print('NO ODOM')
node.destroy_node();rclpy.shutdown()
