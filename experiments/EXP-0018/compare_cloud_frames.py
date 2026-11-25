import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
import rosbag2_py
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import PointCloud2

reader = rosbag2_py.SequentialReader()
reader.open(rosbag2_py.StorageOptions(uri='experiments/EXP-0018/cloud-geometry',storage_id='sqlite3'),
            rosbag2_py.ConverterOptions('', ''))
by_time = {}
data = {'/utlidar/cloud': {}, '/utlidar/cloud_base': {}}
while reader.has_next():
    topic, raw, received = reader.read_next()
    msg = deserialize_message(raw, PointCloud2)
    stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
    fields = {f.name:f.offset for f in msg.fields}
    a = np.stack([np.ndarray((msg.width,),'<f4', buffer=msg.data, offset=fields[f], strides=(msg.point_step,))
                  for f in 'xyz'], axis=1)
    t = np.ndarray((msg.width,),'<f4',buffer=msg.data,offset=fields['time'],strides=(msg.point_step,))
    intensity = np.ndarray((msg.width,),'<f4',buffer=msg.data,offset=fields['intensity'],strides=(msg.point_step,))
    by_time[topic,stamp] = {(float(tm),float(v)):p.astype(float) for tm,v,p in zip(t,intensity,a)
                           if np.isfinite(p).all() and np.isfinite(tm) and np.isfinite(v)}
    data[topic][stamp] = a[np.isfinite(a).all(axis=1)]
geom = json.loads(Path('shared/dddmr/real/go2_nominal_geometry.json').read_text())
tf = next(t for t in geom['transforms'] if t['child']=='radar' and t['parent']=='base')
rot = np.array(tf['rotation_matrix'])
translation = np.array(tf['translation_m'])
raw, base = data.values()
keys = sorted(raw.keys() & base.keys())
best = []
for k in keys:
    if not len(raw[k]) or not len(base[k]):
        continue
    distances = cKDTree(raw[k] @ rot.T + translation).query(base[k])[0]
    identity = cKDTree(raw[k]).query(base[k])[0]
    best.append([np.median(distances), np.median(identity), np.mean(distances < .02)])
base_points = np.concatenate(list(base.values()))
local = base_points[(np.hypot(base_points[:,0],base_points[:,1]) > .35) &
                   (np.hypot(base_points[:,0],base_points[:,1]) < 2.5) & (base_points[:,2] < 0)]
hist, edges = np.histogram(local[:,2],bins=np.arange(-.81,.011,.02))
peak = int(np.argmax(hist))
summary = {'exact_header_pairs':len(keys), 'frame_count_raw_and_base':[len(raw),len(base)],
  'median_match_error_m_urdf_then_identity':np.median(best,axis=0)[:2].tolist() if best else None,
  'median_fraction_within_2cm_urdf':float(np.median(best,axis=0)[2]) if best else None,
  'dominant_negative_z_bin_base_cloud_m':edges[peak:peak+2].tolist() if len(local) else None,
  'points_in_dominant_bin':int(hist[peak]), 'local_negative_z_points':len(local)}

pairs = [(a[key],b[key]) for stamp in keys
         for a,b in [(by_time['/utlidar/cloud',stamp],by_time['/utlidar/cloud_base',stamp])]
         for key in a.keys() & b.keys()]
if len(pairs) >= 10:
    from scipy.spatial.transform import Rotation
    a,b = np.asarray(pairs).transpose(1,0,2)
    def fit(a,b):
        u,_,vt = np.linalg.svd((a-a.mean(0)).T @ (b-b.mean(0)))
        mat = vt.T @ np.diag([1,1,np.linalg.det(vt.T @ u.T)]) @ u.T
        return mat,b.mean(0)-mat @ a.mean(0)
    mat,t=fit(a,b)
    for _ in range(3):
        residual = np.linalg.norm(a@mat.T+t-b,axis=1)
        mask=residual < max(.025,3*np.median(residual))
        mat,t=fit(a[mask],b[mask])
    residual=np.linalg.norm(a@mat.T+t-b,axis=1)
    summary['same_point_fit'] = {'matched_points':len(a),'matched_stamps':len(keys),
        'translation_m':t.tolist(),'rpy_xyz_rad':Rotation.from_matrix(mat).as_euler('xyz').tolist(),
        'median_pair_error_m':float(np.median(residual)),
        'fraction_within_2cm':float(np.mean(residual<.02))}
else:
    summary['same_point_fit'] = {'matched_points':len(pairs)}

print(json.dumps(summary,indent=2))
