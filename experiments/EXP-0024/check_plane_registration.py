"""Independent fixed-map point-to-plane registration, without inertial input."""
import json,numpy as np,rosbag2_py
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import PointCloud2
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0024/standing-three-sensors',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
scans=[]
while r.has_next():
 t,b,s=r.read_next()
 if not t.endswith('/cloud'):continue
 m=deserialize_message(b,PointCloud2);f={x.name:x.offset for x in m.fields};p=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1);p=p[np.isfinite(p).all(1)&(np.linalg.norm(p,axis=1)>.5)&(np.linalg.norm(p,axis=1)<8)];scans.append(p)
b=np.concatenate(scans[:20]);b=b[np.unique(np.floor(b/.05),axis=0,return_index=True)[1]];tree=cKDTree(b);out={}
for idx in [40,100,200,300]:
 a=scans[idx];R=np.eye(3);t=np.zeros(3)
 for step in range(20):
  p=a@R.T+t;d,ii=tree.query(p,k=8);nb=b[ii];center=nb.mean(1);cov=(nb-center[:,None,:]).transpose(0,2,1)@(nb-center[:,None,:]);vals,vecs=np.linalg.eigh(cov);n=vecs[:,:,0];res=(n*(p-center)).sum(1)
  mask=(d[:,-1]<.5)&(vals[:,1]>.05*vals[:,2])&(vals[:,0]<.2*vals[:,1])&(np.abs(res)<.15)
  H=np.concatenate([n,np.cross(p,n)],axis=1)[mask];rr=res[mask]
  dx=np.linalg.lstsq(H,-rr,rcond=1e-5)[0];rot=Rotation.from_rotvec(dx[3:]).as_matrix();R=rot@R;t=rot@t+dx[:3]
  if np.linalg.norm(dx)<1e-5:break
 out[idx]={'xyz':t.tolist(),'angle_deg':float(np.rad2deg(Rotation.from_matrix(R).magnitude())),'matched':int(mask.sum()),'median_error_m':float(np.median(np.abs(rr))),'singular_values':np.linalg.svd(H,compute_uv=False).tolist()}
print(json.dumps(out,indent=2))
