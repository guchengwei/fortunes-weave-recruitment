import itertools, collections
from pathlib import Path
import json
ASSETS = Path(__file__).resolve().parents[2] / "src/assets"
def support_cost(row):
    return max(0, (row["support"] or 0) - 1) if row["status"] == "recruit" else 0
OUT=ASSETS
D=json.loads((OUT/"recruitment-data.json").read_text())
rows=D["rows"]; routes=D["routes"]; eligible=D["targets"]
def options(name,story):
 return [x for x in rows if x['name']==name and (x['status'] in ['recruit','free'] or story and x['status']=='story')]
def cost(x,mode):
 r=0 if x['status']=='story' else x['renown'];s=support_cost(x)
 return r,s

def prune(states):
 # one representative per coordinate, then exact 2D dominance pruning
 best={}
 for a,b,p in states:
  if a not in best or b<best[a][0]:best[a]=(b,p)
 front=[]; low=float('inf')
 for a,(b,p) in sorted(best.items()):
  if b<low:front.append((a,b,p));low=b
 return front

def additive(story):
 states=[(0,0,[])]
 for name in eligible:
  states=prune([(a+cost(x,'')[0],b+cost(x,'')[1],p+[x]) for a,b,p in states for x in options(name,story)])
 return [dict(r=a,s=b,assignment=p) for a,b,p in states]

def threshold(story):
 # Shared renown gate per route. Baseline 2 in all four routes, including free recruits.
 states=[]; valid=0
 for caps in itertools.product(range(2,11),repeat=4):
  chosen=[]
  for name in eligible:
   opts=[x for x in options(name,story) if x['status']=='story' or x['renown']<=caps[routes.index(x['route'])]]
   if not opts:break
   chosen.append(min(opts,key=lambda x:(support_cost(x), x['renown'] or 0,routes.index(x['route']))))
  else:
   valid+=1
   actual=[max([2]+[x['renown'] for x in chosen if x['route']==r and x['status']!='story']) for r in routes]
   states.append((sum(actual),sum(support_cost(x) for x in chosen),chosen))
 front=[dict(r=a,s=b,caps=[max([2]+[x['renown'] for x in p if x['route']==r and x['status']!='story']) for r in routes],assignment=p) for a,b,p in prune(states)]
 return front,valid

results={}
for story in [False,True]:
 prefix='inclusive' if story else 'strict'
 f,v=threshold(story);a=additive(story)
 prod=[min(options(n,story),key=lambda x:(cost(x,'')[0]*cost(x,'')[1],sum(cost(x,'')),routes.index(x['route']))) for n in eligible]
 results[prefix]=dict(threshold=f,additive=a,product=dict(value=sum(cost(x,'')[0]*cost(x,'')[1] for x in prod),r=sum(cost(x,'')[0] for x in prod),s=sum(cost(x,'')[1] for x in prod),assignment=prod),enumerated=9**4,feasible=v)
 print(prefix,'threshold',[(x['r'],x['s'],x['caps']) for x in f],'additive',[(x['r'],x['s']) for x in a], 'product',results[prefix]['product']['value'])
 for mode in ['threshold','additive']:
  for p in results[prefix][mode]:
   assert len(p['assignment'])==len(eligible)
   assert {x['name'] for x in p['assignment']}==set(eligible)
OUT.joinpath('optimization-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
