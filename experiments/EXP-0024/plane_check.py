import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

def planes(points):
 rng=np.random.default_rng(9)
 points=points[np.isfinite(points).all(1)]
 points=points[np.linalg.norm(points,axis=1)<5]
 if len(points)>25000:points=points[rng.choice(len(points),25000,replace=False)]
 result=[]
 for _ in range(4):
  best=np.zeros(len(points),dtype=bool)
  for _ in range(250):
   a,b,c=points[rng.choice(len(points),3,replace=False)]
   n=np.cross(b-a,c-a); norm=np.linalg.norm(n)
   if norm<1e-5:continue
   n/=norm; d=-n@a
   mask=np.abs(points@n+d)<.025
   if mask.sum()>best.sum():best=mask
  if best.sum()<100:break
  selected=points[best];center=selected.mean(0)
  _,_,vt=np.linalg.svd(selected-center,full_matrices=False)
  n=vt[-1];d=-n@center
  result.append({'count':int(best.sum()),'normal':n.tolist(),'offset_m':float(d),'center':center.tolist()})
  points=points[~best]
 return result

if __name__=='__main__':
 import sys
 print(json.dumps(planes(np.load(sys.argv[1])),indent=2))
