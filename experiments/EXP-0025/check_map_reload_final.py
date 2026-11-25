import json,time,rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy
from sensor_msgs.msg import PointCloud2
from geometry_msgs.msg import PoseArray
from dddmr_sys_core.srv import GetKeyFrameCloud
rclpy.init();n=Node('verify_saved_dddmr_map');qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL);result={};subs=[]
def cb(m,t):result[t]={'frame':m.header.frame_id,('poses' if isinstance(m,PoseArray) else 'points'):(len(m.poses) if isinstance(m,PoseArray) else m.width*m.height)}
for t,cls in [('/map1/key_poses',PoseArray),('/map1/mapcloud',PointCloud2),('/map1/mapsurface',PointCloud2),('/map1/mapground',PointCloud2)]:subs.append(n.create_subscription(cls,t,lambda m,t=t:cb(m,t),qos))
end=time.monotonic()+12
while time.monotonic()<end and len(result)<4:rclpy.spin_once(n,timeout_sec=.1)
client=n.create_client(GetKeyFrameCloud,'/map1/get_key_frame_cloud');result['keyframe_service']={'available':client.wait_for_service(timeout_sec=3.)}
if result['keyframe_service']['available']:
 for idx in [0,23]:
  req=GetKeyFrameCloud.Request();req.key_frame_number=idx;f=client.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=5.)
  if f.done() and f.exception() is None:
   r=f.result();result['keyframe_service'][str(idx)]={key:getattr(r,key).width for key in ['key_frame_corner','key_frame_surface','key_frame_ground','key_frame_cloud_base_link']}
open('/results/map-reload-check-final.json','w').write(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));n.destroy_node();rclpy.try_shutdown()
assert result.get('/map1/key_poses',{}).get('poses')==24,'Wrong pose count'
assert all(result.get(t,{}).get('points',0)>0 for t in ['/map1/mapcloud','/map1/mapsurface','/map1/mapground']),'Missing map content'
assert result['keyframe_service'].get('23',{}).get('key_frame_ground',0)>0,'Last key frame unavailable'
