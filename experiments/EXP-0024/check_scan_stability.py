"""Independent scan-to-scan rigid alignment check, without inertial prediction."""
import json
import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import PointCloud2
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
r=rosbag2_py.SequentialReader()
r.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0024/standing-three-sensors',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
clouds=[]
while r.has_next():
 n,b,_=r.read_next()
 if not n.endswith('/cloud'):continue
 m=deserialize_message(b,PointCloud2);f={x.name:x.offset for x in m.fields}
 a=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1).astype(float)
 norms=np.linalg.norm(a,axis=1);a=a[(norms>.5)&(norms<8)&np.isfinite(a).all(1)]
 clouds.append(a)
def align(a,b):
 tree=cKDTree(b);R=np.eye(3);t=np.zeros(3)
 for _ in range(35):
  trans=a@R.T+t;dist,idx=tree.query(trans)
  good=dist<.25
  if good.sum()<30:break
  src=trans[good];dst=b[idx[good]]
  u,_,vt=np.linalg.svd((src-src.mean(0)).T@(dst-dst.mean(0)))
  rot=vt.T@np.diag([1,1,np.linalg.det(vt.T@u.T)])@u.T
  shift=dst.mean(0)-rot@src.mean(0)
  R=rot@R;t=rot@t+shift
  if np.linalg.norm(shift)<1e-5 and Rotation.from_matrix(rot).magnitude()<1e-5:break
 return {'xyz_m':t.tolist(),'angle_deg':float(np.rad2deg(Rotation.from_matrix(R).magnitude())),'median_nearest_error_m':float(np.median(dist)),'points':len(a)}
print(json.dumps({str(i):align(clouds[i],clouds[0]) for i in [20,80,160,250,310]},indent=2))
