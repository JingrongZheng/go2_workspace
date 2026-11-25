"""Independent fixed-map scan registration; not ground truth and no control."""
import json,numpy as np,rosbag2_py,time
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import PointCloud2
base='experiments/EXP-0024/';r=rosbag2_py.SequentialReader();r.open(rosbag2_py.StorageOptions(uri=base+'motion-trial-02',storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''));scans=[];times=[]
while r.has_next():
 name,b,s=r.read_next()
 if not name.endswith('/cloud'):continue
 m=deserialize_message(b,PointCloud2);f={x.name:x.offset for x in m.fields};p=np.stack([np.ndarray((m.width,),'<f4',buffer=m.data,offset=f[k],strides=(m.point_step,)) for k in 'xyz'],1);good=np.isfinite(p).all(1)&(np.linalg.norm(p,axis=1)>.5)&(np.linalg.norm(p,axis=1)<8);scans.append(p[good]);pt=np.ndarray((m.width,),'<f4',buffer=m.data,offset=f['time'],strides=(m.point_step,));times.append(m.header.stamp.sec+m.header.stamp.nanosec*1e-9+float(pt.max()))
b=np.concatenate(scans[:25]);b=b[np.unique(np.floor(b/.05),axis=0,return_index=True)[1]];tree=cKDTree(b);R=np.eye(3);t=np.zeros(3);out=[]
for idx in range(25,len(scans),4):
 a=scans[idx]
 for step in range(15):
  p=a@R.T+t;d,ii=tree.query(p,k=8);nb=b[ii];center=nb.mean(1);z=nb-center[:,None,:];vals,vecs=np.linalg.eigh(z.transpose(0,2,1)@z);n=vecs[:,:,0];res=(n*(p-center)).sum(1)
  mask=(d[:,-1]<.6)&(vals[:,1]>.05*vals[:,2])&(vals[:,0]<.2*vals[:,1])&(np.abs(res)<.2)
  if mask.sum()<50:break
  H=np.concatenate([n,np.cross(p,n)],axis=1)[mask];rr=res[mask];weights=1/np.maximum(1,np.abs(rr)/.03);dx=np.linalg.lstsq(H*weights[:,None],-rr*weights,rcond=1e-5)[0]
  if np.linalg.norm(dx[:3])>.2 or np.linalg.norm(dx[3:])>.15:break
  rot=Rotation.from_rotvec(dx[3:]).as_matrix();R=rot@R;t=rot@t+dx[:3]
  if np.linalg.norm(dx)<1e-5:break
 out.append([times[idx],*t,*Rotation.from_matrix(R).as_quat(),int(mask.sum()),float(np.median(np.abs(res[mask])))])
a=np.array(out);np.save(base+'motion-02-independent-poses.npy',a)
summary={'method':'fixed-map robust point-to-plane registration, no IMU, no Point-LIO initialization','map_frames':25,'registered_frames':len(a),'max_lidar_displacement_m':float(np.linalg.norm(a[:,1:4],axis=1).max()),'last_lidar_displacement_m':float(np.linalg.norm(a[-1,1:4])),'median_residual_m':float(np.median(a[:,-1])),'max_residual_m':float(np.max(a[:,-1])),'minimum_matched_points':int(a[:,-2].min())}
# Compare LiDAR poses in the same initial-sensor gauge, without fitting scale.
body=np.load(base+'motion-02-body-poses.npy');geo=json.load(open('shared/dddmr/real/go2_published_cloud_geometry.json'));Rbc=np.array(geo['rotation_matrix']);tbc=np.array(geo['translation_m']);Rwb=Rotation.from_quat(body[:,4:]).as_matrix();Rwc=Rwb@Rbc;twc=body[:,1:4]+np.einsum('nij,j->ni',Rwb,tbc);R0=Rwc[0];t0=twc[0]
errors=[];rot_errors=[]
for row in a:
 k=np.argmin(np.abs(body[:,0]-row[0]))
 if abs(body[k,0]-row[0])>.08:continue
 pred_t=R0.T@(twc[k]-t0);pred_R=R0.T@Rwc[k];errors.append(np.linalg.norm(pred_t-row[1:4]));rot_errors.append(np.rad2deg((Rotation.from_matrix(pred_R).inv()*Rotation.from_quat(row[4:8])).magnitude()))
summary['point_lio_difference_m_quantiles']=np.quantile(errors,[.5,.95,1]).tolist();summary['point_lio_angle_difference_deg_quantiles']=np.quantile(rot_errors,[.5,.95,1]).tolist()
open(base+'motion-02-independent-check.json','w').write(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
