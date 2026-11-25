"""Synthetic moving-sensor test: both accumulated scans must match one scene."""
import sys,json,argparse,numpy as np,rclpy
from pathlib import Path
from scipy.spatial.transform import Rotation
from sensor_msgs.msg import PointCloud2,PointField
from nav_msgs.msg import Odometry
sys.path.insert(0,'/go2-real')
from mapping_cloud import MappingCloud
rclpy.init();node=MappingCloud(argparse.Namespace(cloud_topic='/test_cloud',ground_z=-.317,frames=2))
class Capture:
 def __init__(self):self.messages=[]
 def publish(self,m):self.messages.append(m)
capture=Capture();node.output=capture
Rbc=node.body_from_cloud;tbc=node.sensor_origin
def rt(t):return Rotation.from_rotvec([0,0,t]),np.array([2*t,-t,0])
for t in [0.,.1]:
 m=Odometry();m.header.frame_id='odom';m.child_frame_id='base_link';m.header.stamp.nanosec=round(t*1e9);R,p=rt(t);m.pose.pose.position.x,m.pose.pose.position.y,m.pose.pose.position.z=map(float,p);m.pose.pose.orientation.x,m.pose.pose.orientation.y,m.pose.pose.orientation.z,m.pose.pose.orientation.w=map(float,R.as_quat());node.odom(m)
scene=np.array([[2.,1.,.5],[3.,-1.,.3],[4.,.4,1.],[2.5,-.2,.1]])
for begin in [.01,.04]:
 offsets=np.array([0.,.005,.01,.02],dtype='<f4');raw=[]
 for target,dt in zip(scene,offsets):
  R,p=rt(begin+float(dt));body=R.inv().apply(target-p);raw.append(Rbc.T@(body-tbc))
 packed=np.column_stack([raw,np.ones(4),offsets]).astype('<f4');m=PointCloud2();m.header.frame_id=node.source_frame;m.header.stamp.nanosec=round(begin*1e9);m.width=4;m.height=1;m.point_step=20;m.row_step=80;m.fields=[PointField(name=x,offset=4*i,datatype=PointField.FLOAT32,count=1) for i,x in enumerate(['x','y','z','intensity','time'])];m.data=packed.tobytes();node.cloud(m)
assert len(capture.messages)==1
m=capture.messages[0];actual=np.frombuffer(m.data,dtype='<f4').reshape(-1,4)[:,:3];end=m.header.stamp.sec+m.header.stamp.nanosec*1e-9;R,p=rt(end);expected=R.inv().apply(np.vstack([scene,scene])-p-R.apply(tbc));error=float(abs(actual-expected).max());assert error<2e-6,(error,actual,expected)
print(json.dumps({'moving_scan_accumulation_max_coordinate_error_m':error,'points':m.width,'frame':m.header.frame_id,'output_time_s':end}));node.destroy_node();rclpy.try_shutdown()
