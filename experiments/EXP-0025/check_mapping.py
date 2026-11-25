"""Observe map creation and save via the author's service. No control topics."""
import json,time,os,numpy as np,rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from geometry_msgs.msg import PoseArray
from std_srvs.srv import Empty
from tf2_ros import Buffer,TransformListener
rclpy.init();node=Node('verify_dddmr_real_mapping');buffer=Buffer();listener=TransformListener(buffer,node);stats={};subscriptions=[];last={};poses=[]
def cb(m,name):
 stats[name]=stats.get(name,0)+1
 if isinstance(m,PointCloud2):last[name]={'points':m.width*m.height,'frame':m.header.frame_id}
 else:poses.append(len(m.poses));last[name]={'poses':len(m.poses),'frame':m.header.frame_id}
for topic,cls in [('/dddmr/lidar_points',PointCloud2),('/ground_cloud',PointCloud2),('/laser_cloud_sharp',PointCloud2),('/laser_cloud_less_flat',PointCloud2),('/key_poses',PoseArray)]:
 from rclpy.qos import QoSProfile,DurabilityPolicy
 qos=QoSProfile(depth=10)
 if topic in ['/laser_cloud_sharp','/laser_cloud_less_flat']:qos.durability=DurabilityPolicy.TRANSIENT_LOCAL
 subscriptions.append(node.create_subscription(cls,topic,lambda m,t=topic:cb(m,t),qos))
end=time.monotonic()+float(os.environ.get('MAP_OBSERVE_SECONDS','94'))
while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.1)
client=node.create_client(Empty,'/save_mapped_point_cloud');save={'service_available':client.wait_for_service(timeout_sec=5.)}
if save['service_available']:
 future=client.call_async(Empty.Request());rclpy.spin_until_future_complete(node,future,timeout_sec=30.);save['response_received']=future.done() and future.exception() is None
result={'received_messages':stats,'last_messages':last,'maximum_key_poses':max(poses,default=0),'save':save,'tf':{}}
for frame in ['base_link','dddmr_lidar','odom']:
 try:
  tf=buffer.lookup_transform('map',frame,rclpy.time.Time());p=tf.transform.translation;result['tf'][frame]={'xyz':[p.x,p.y,p.z]}
 except Exception as e:result['tf'][frame]={'error':str(e)}
open('/results/mapping-check-v1.json','w').write(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));node.destroy_node();rclpy.try_shutdown()
