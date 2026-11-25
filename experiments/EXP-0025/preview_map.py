from pathlib import Path
import json,numpy as np,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation
root=Path('.work/dddmr-real/maps/EXP-0025-v1/2026_11_25_07_32_44')
def pcd(p):
 lines=p.read_text().splitlines();i=lines.index('DATA ascii');return np.loadtxt(lines[i+1:],ndmin=2)
features=pcd(root/'map.pcd')[:,:3];ground=pcd(root/'ground.pcd')[:,:3];poses=pcd(root/'poses.pcd');surfaces=[]
for i,pose in enumerate(poses):
 p=pcd(root/'pcd'/f'{i}_surface.pcd')[:,:3];surfaces.append(Rotation.from_euler('xyz',pose[4:7]).apply(p)+pose[:3])
surface=np.concatenate(surfaces);fig=plt.figure(figsize=(12,5),layout='constrained');ax=fig.add_subplot(121)
for p,color,name,size in [(ground,'#9ccca2','Observed/patched ground',3),(surface,'#777777','Surface features',5),(features,'#2364aa','Edge features',9)]:ax.scatter(p[:,0],p[:,1],c=color,s=size,label=name,alpha=.8)
ax.plot(poses[:,0],poses[:,1],c='#cc5511',lw=2,label='Keyframe path');ax.set(xlabel='map x (m)',ylabel='map y (m)',title='Partial map: short manual scan');ax.set_aspect('equal');ax.grid(alpha=.2);ax.legend(fontsize=8,loc='upper left')
ax=fig.add_subplot(122,projection='3d');ax.scatter(ground[:,0],ground[:,1],ground[:,2],c='#9ccca2',s=2,alpha=.5);ax.scatter(surface[:,0],surface[:,1],surface[:,2],c='#777777',s=4);ax.scatter(features[:,0],features[:,1],features[:,2],c='#2364aa',s=7);ax.plot(poses[:,0],poses[:,1],poses[:,2],c='#cc5511',lw=2);ax.set(xlabel='x (m)',ylabel='y (m)',zlabel='z (m)',title='DDDMR saved geometry');ax.view_init(elev=28,azim=-57);ax.set_box_aspect((1,1,.45));fig.savefig('experiments/EXP-0025/map-preview-v1.png',dpi=160)
points=ground;c=points.mean(0);_,_,v=np.linalg.svd(points-c,full_matrices=False);normal=v[-1]*np.sign(v[-1,2]);stats={'keyframes':len(poses),'edge_map_points':len(features),'ground_map_points':len(ground),'per_keyframe_surface_points_aggregate':len(surface),'ground_plane_tilt_in_map_deg':float(np.rad2deg(np.arccos(normal[2]))),'ground_plane_residual_m_quantiles':np.quantile(abs((points-c)@normal),[.5,.95]).tolist(),'scope':'Partial view from short manual path, not a complete navigable room map'};Path('experiments/EXP-0025/map-geometry-v1.json').write_text(json.dumps(stats,indent=2)+'\n');print(json.dumps(stats,indent=2))
