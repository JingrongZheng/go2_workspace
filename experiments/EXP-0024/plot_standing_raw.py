import rosbag2_py,numpy as np,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import PointCloud2
r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0024/standing-three-sensors',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
ps=[];cs=[];n=0
while r.has_next():
 name,b,s=r.read_next()
 if not name.endswith('/cloud'):continue
 m=deserialize_message(b,PointCloud2);f={x.name:x.offset for x in m.fields};p=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1);good=np.isfinite(p).all(1)&(np.linalg.norm(p,axis=1)>.5)&(np.linalg.norm(p,axis=1)<8);ps.append(p[good][::8]);cs.extend([n]*len(ps[-1]));n+=1
p=np.concatenate(ps);fig,axs=plt.subplots(1,3,figsize=(15,5))
for ax,(i,j) in zip(axs,[(0,1),(0,2),(1,2)]):
 ax.scatter(p[:,i],p[:,j],s=.3,c=cs,cmap='turbo',vmin=0,vmax=n);ax.set_xlabel('xyz'[i]);ax.set_ylabel('xyz'[j]);ax.axis('equal');ax.grid()
fig.tight_layout();fig.savefig('experiments/EXP-0024/standing-raw.png',dpi=130)
