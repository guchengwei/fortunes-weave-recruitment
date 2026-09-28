import json,itertools,collections
from pathlib import Path
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from pathlib import Path
import json
ASSETS = Path(__file__).resolve().parents[2] / "src/assets"
def support_cost(row):
    return max(0, (row["support"] or 0) - 1) if row["status"] == "recruit" else 0
W=ASSETS;D=json.loads((W/"recruitment-data.json").read_text());RES=json.loads((W/"optimization-results.json").read_text());routes=D["routes"];names=D["targets"]

auto=[x for x in D['rows'] if x['status']=='story' and x['name'] in names]
opts=[x for x in D['rows'] if x['status'] in ('free','recruit')];N=len(opts);M=N+2
by={n:[x for x in opts if x['name']==n] for n in names};need={n:min(2,len(by[n])+sum(x['name']==n for x in auto))-sum(x['name']==n for x in auto) for n in names}
comb={n:list(itertools.combinations(by[n],need[n])) for n in names}
rv=np.array([x['renown'] for x in opts]+[0,0],float);sv=np.array([support_cost(x) for x in opts]+[0,0],float);pv=rv*sv;dv=np.array([0]*N+[1,-1],float)
A=[];lo=[];hi=[]
for n in names:A.append([int(x['name']==n) for x in opts]+[0,0]);lo.append(need[n]);hi.append(need[n])
for r in routes:
 c=[int(x['route']==r) for x in opts];A.extend([c+[-1,0],c+[0,-1]]);lo.extend([-np.inf,0]);hi.extend([0,np.inf])
def run(obj,ex=[]):
 z=milp(obj,integrality=np.ones(M),bounds=Bounds([0]*M,[1]*N+[75,75]),constraints=LinearConstraint(np.array(A+[x[0] for x in ex]),lo+[x[1] for x in ex],hi+[x[2] for x in ex]),options={'mip_rel_gap':0})
 if z.status==2:return None
 assert z.success,z.message
 return z

def pack(z):
 ass=[x for j,x in enumerate(opts) if z.x[j]>.5]+auto;c=[sum(x['route']==r and x['status']!='story' for x in ass) for r in routes]
 return dict(r=round(rv@z.x),s=round(sv@z.x),value=round(pv@z.x),counts=c,delta=max(c)-min(c),assignment=ass)

def frontier(cap=None):
 out=[];smax=225;ex=[] if cap is None else [(dv,-np.inf,cap)]
 while True:
  ext=ex+[(sv,-np.inf,smax)];z=run(rv,ext)
  if z is None:break
  r=round(rv@z.x);z=run(sv,ext+[(rv,r,r)]);s=round(sv@z.x);z=run(dv,[(rv,r,r),(sv,s,s)]);out.append(pack(z));smax=s-1
 return out
mind=round(dv@run(dv).x);print('Minimum headcount gap',mind,flush=True)
add=frontier();points=add[:];print('Unconstrained frontier',[(p['r'],p['s']) for p in add],flush=True)
for cap in sorted(set([mind,2])):
 f=frontier(cap);points+=f;print('Balance cap',cap,'points',len(f),flush=True)
z=run(pv);v=round(pv@z.x);z=run(dv,[(pv,v,v)]);prod=pack(z)
# Enumerate all shared-threshold combinations; for each cap use minimum support witness.
best={}
for caps in itertools.product(range(2,11),repeat=4):
 ass=[]
 for n in names:
  valid=[xs for xs in comb[n] if all(x['renown']<=caps[routes.index(x['route'])] for x in xs)]
  if not valid:break
  ass.extend(min(valid,key=lambda xs:(sum(support_cost(x) for x in xs),sum(x['renown'] for x in xs))))
 else:
  actual=[max([2]+[x['renown'] for x in ass if x['route']==r]) for r in routes];r=sum(actual);s=sum(support_cost(x) for x in ass)
  if r not in best or s<best[r]['s']:best[r]=dict(r=r,s=s,caps=actual,assignment=ass+auto)
th=[];low=999
for r,p in sorted(best.items()):
 if p['s']<low:th.append(p);low=p['s']
unique={(p['r'],p['s'],p['delta']):p for p in points};bf=[p for k,p in unique.items() if not any(q!=k and all(a<=b for a,b in zip(q,k)) for q in unique)]
RES['twice']=dict(additive=add,balanced_frontier=bf,threshold=th,product=prod,min_delta=mind,recruit_count=sum(need.values()),exception_names=[n for n in D['characters'] if sum(x['name']==n and x['status']!='no' for x in D['rows'])<2])
for p in add+bf+th+[prod]:
 ass=p['assignment'];assert len(ass)==87;assert len({(x['name'],x['route']) for x in ass})==87
 for n in names:assert sum(x['name']==n for x in ass)==min(2,len(by[n])+sum(x['name']==n for x in auto))
 assert p['s']==sum(support_cost(x) for x in ass)
 if 'caps' not in p:assert p['r']==sum(x['renown'] for x in ass if x['status']!='story')
# Independent separable lower bounds.
assert min(p['r'] for p in add)==sum(min(sum(x['renown'] for x in xs) for xs in comb[n]) for n in names)
assert min(p['s'] for p in add)==sum(min(sum(support_cost(x) for x in xs) for xs in comb[n]) for n in names)
(W/'optimization-results.json').write_text(json.dumps(RES,ensure_ascii=False,indent=2))
print('Verified 43 people twice + 7 once; 75 recruitments + 18 story joins',flush=True)
