import json,math,collections
from pathlib import Path
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from pathlib import Path
import json
ASSETS = Path(__file__).resolve().parents[2] / "src/assets"
def support_cost(row):
    return max(0, (row["support"] or 0) - 1) if row["status"] == "recruit" else 0
O=ASSETS;D=json.loads((O/"recruitment-data.json").read_text());RES=json.loads((O/"optimization-results.json").read_text());routes=D["routes"]

# Always use story coverage where available: avoid redundant recruits to pad route counts.
storynames={x['name'] for x in D['rows'] if x['status']=='story'}
names=[n for n in D['targets'] if n not in storynames]
auto=[next(x for x in D['rows'] if x['name']==n and x['status']=='story') for n in D['targets'] if n in storynames]
opts=[x for x in D['rows'] if x['name'] in names and x['status'] in ['recruit','free']]
N=len(opts); M=N+2
rv=np.array([x['renown'] for x in opts]+[0,0],float)
sv=np.array([support_cost(x) for x in opts]+[0,0],float)
pv=rv*sv;dv=np.array([0]*N+[1,-1],float)
A=[];lo=[];hi=[]
def add(a,l,h):A.append(a);lo.append(l);hi.append(h)
for n in names:add([int(x['name']==n) for x in opts]+[0,0],1,1)
for r in routes:
 counts=[int(x['route']==r) for x in opts]
 add(counts+[-1,0],-np.inf,0)
 add(counts+[0,-1],0,np.inf)
bounds=Bounds([0]*M,[1]*N+[len(names),len(names)])
def run(obj,extra=[]):
 aa=A+[e[0] for e in extra];ll=lo+[e[1] for e in extra];hh=hi+[e[2] for e in extra]
 z=milp(obj,integrality=np.ones(M),bounds=bounds,constraints=LinearConstraint(np.array(aa),ll,hh),options={'mip_rel_gap':0})
 if z.status==2:return None
 assert z.success,z.message
 return z

def pack(z):
 ass=[x for i,x in enumerate(opts) if z.x[i]>.5]+auto
 counts=[sum(x['route']==r and x['status']!='story' for x in ass) for r in routes]
 return dict(r=int(round(rv@z.x)),s=int(round(sv@z.x)),value=int(round(pv@z.x)),counts=counts,delta=max(counts)-min(counts),assignment=ass)
# Replace 2D representatives by the most balanced at each exact cost coordinate.
for p in RES['inclusive']['additive']:
 z=run(dv,[(rv,p['r'],p['r']),(sv,p['s'],p['s'])]); assert z
 p.update(pack(z))
p=RES['inclusive']['product'];z=run(dv,[(pv,p['value'],p['value'])]);p.update(pack(z))
maxdelta=max(p['delta'] for p in RES['inclusive']['additive'])
points=[]
for d in range(maxdelta+1):
 smax=len(names)*3
 while True:
  extra=[(dv,-np.inf,d),(sv,-np.inf,smax)]
  z=run(rv,extra)
  if z is None:break
  r=int(round(rv@z.x));z=run(sv,extra+[(rv,r,r)])
  s=int(round(sv@z.x));z=run(dv,[(rv,r,r),(sv,s,s)])
  p=pack(z);points.append(p);smax=s-1
 print('delta cap',d,'points',len(points),flush=True)
# exact 3D dominance pruning
unique={(p['r'],p['s'],p['delta']):p for p in points}
front=[p for key,p in unique.items() if not any(all(a<=b for a,b in zip(k,key)) and k!=key for k in unique)]
front.sort(key=lambda p:(p['delta'],p['r'],p['s']))
RES['inclusive']['balanced_frontier']=front
(O/'optimization-results.json').write_text(json.dumps(RES,ensure_ascii=False,indent=2))
for d in range(maxdelta+1):
 ps=[p for p in front if p['delta']<=d]
 if ps:
  p=min(ps,key=lambda p:(p['r']+p['s'],p['delta'],p['s']))
  print('cap',d,'C',p['r']+p['s'],'R,S',p['r'],p['s'],'counts',p['counts'])
# Validate every witness against original data and exact costs.
for p in front+RES['inclusive']['additive']+[RES['inclusive']['product']]:
 assert {x['name'] for x in p['assignment']}==set(D['targets'])
 assert len(p['assignment'])==len(D['targets'])
 assert all(x in D['rows'] for x in p['assignment'])
 assert p['r']==sum(x['renown'] for x in p['assignment'] if x['status'] in ['recruit','free'])
 assert p['s']==sum(support_cost(x) for x in p['assignment'])
 assert sum(p['counts'])==len(names)==32
# Independent scalar lower bound for the additive unconstrained case.
low=sum(min((x['renown'])+support_cost(x) for x in opts if x['name']==n) for n in names)
assert low==min(p['r']+p['s'] for p in front)
print('Verified 3D points',len(front),'independent lower bound',low)
