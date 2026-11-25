import json,numpy as np,rosbag2_py
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import PointCloud2
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0024/motion-trial-02',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''));g=json.load(open('shared/dddmr/real/go2_published_cloud_geometry.json'));R=np.array(g['rotation_matrix']);t=np.array(g['translation_m']);clouds=[]
while r.has_next() and len(clouds)<25:
 n,b,_=r.read_next()
 if not n.endswith('/cloud'):continue
 m=deserialize_message(b,PointCloud2);f={x.name:x.offset for x in m.fields};p=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1);p=p@R.T+t;clouds.append(p[np.isfinite(p).all(1)])
p=np.concatenate(clouds)[::4];p=p[(np.linalg.norm(p[:,:2],axis=1)<5)&(np.linalg.norm(p[:,:2],axis=1)>.5)];rng=np.random.default_rng(42);best=None
for _ in range(500):
 a,b,c=p[rng.choice(len(p),3,replace=False)];n=np.cross(b-a,c-a);l=np.linalg.norm(n)
 if l<1e-8:continue
 n/=l
 if n[2]<0:n=-n
 if n[2]<.95:continue
 d=-n@a;z=-d/n[2]
 if not -.6<z<-.1:continue
 mask=np.abs(p@n+d)<.02
 if best is None or mask.sum()>best[0]:best=(mask.sum(),n,d,mask)
_,n,d,mask=best;pts=p[mask];center=pts.mean(0);_,_,v=np.linalg.svd(pts-center,full_matrices=False);n=v[-1];n*=np.sign(n[2]);d=-n@center
out={'ground_z_in_base_m':float(-d/n[2]),'normal_in_base':n.tolist(),'inliers':int(mask.sum()),'median_residual_m':float(np.median(np.abs(pts@n+d))),'source':'EXP-0024 motion-trial-02 first 25 clouds; no assumed ground height'}
open('experiments/EXP-0025/ground-reference.json','w').write(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
