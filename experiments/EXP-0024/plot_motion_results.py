import json,numpy as np,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation
base='experiments/EXP-0024/'
a=np.load(base+'motion-02-body-poses.npy');ind=np.load(base+'motion-02-independent-poses.npy');geo=json.load(open('shared/dddmr/real/go2_published_cloud_geometry.json'));Rbc=np.array(geo['rotation_matrix']);tbc=np.array(geo['translation_m']);Rwb0=Rotation.from_quat(a[0,4:]).as_matrix();Rwc0=Rwb0@Rbc;twc0=a[0,1:4]+Rwb0@tbc;Rl=Rotation.from_quat(ind[:,4:8]).as_matrix();body_in_cloud=-Rbc.T@tbc
ind_body=twc0+(ind[:,1:4]+np.einsum('nij,j->ni',Rl,body_in_cloud))@Rwc0.T
p=a[:,1:4]-a[0,1:4];ip=ind_body-a[0,1:4];t=a[:,0]-a[0,0];it=ind[:,0]-a[0,0]
fig,axs=plt.subplots(1,2,figsize=(11,4.5),layout='constrained');ax=axs[0]
ax.plot(p[:,0],p[:,1],label='Point-LIO (L2 + chassis IMU)',lw=1.7);ax.plot(ip[:,0],ip[:,1],ls='--',lw=1.2,label='Independent scan registration');ax.scatter(*p[0,:2],c='green',s=40,label='Start',zorder=4);ax.scatter(*p[-1,:2],c='red',marker='x',s=50,label='Finish',zorder=4);ax.axis('equal');ax.grid(alpha=.3);ax.set(xlabel='x displacement (m)',ylabel='y displacement (m)',title='Trial 02: estimated trajectory');ax.legend(fontsize=8)
ax=axs[1]
for i,name in enumerate('xyz'):ax.plot(t,p[:,i],label=name)
ax.set(xlabel='Time from first pose (s)',ylabel='Displacement (m)',title='Position during motion and final stop');ax.grid(alpha=.3);ax.legend();fig.savefig(base+'motion-02-trajectory.png',dpi=170)
summary=json.load(open(base+'motion-02-independent-check.json'));summary['max_independent_body_displacement_m']=float(np.linalg.norm(ip,axis=1).max());open(base+'motion-02-independent-check.json','w').write(json.dumps(summary,indent=2)+'\n');print('Independent body max:',summary['max_independent_body_displacement_m'])
