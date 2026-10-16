"""Release-local utilities. No import starts an experiment or makes a paid call."""
from pathlib import Path
import json, hashlib, os, math
ROOT = Path(__file__).resolve().parents[1]
def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,default=str,allow_nan=False)
def write(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def config(): return load(ROOT/'environment.json')
def rate(n,d,reason='empty denominator'):
    return {'numerator':n,'denominator':d,'value':n/d if d else None,'status':'MEASURED' if d else 'NOT_APPLICABLE','reason':None if d else reason}
def canonical(v): return dump(v)
def equal(a,b,path=''):
    """Exact identifiers/counts; only declared continuous measurements get tolerance."""
    if isinstance(b,bool): return type(a) is bool and a==b
    if isinstance(b,(int,float)):
        if type(a) not in (int,float) or not math.isfinite(a): return False
        tolerant=any(x in path.lower() for x in ('consumption','amount','ratio','mean','median','duration','1476','1483'))
        return abs(a-b)<= (0.01 if ('consumption' in path or 'amount' in path or '1476' in path or '1483' in path) else max(1e-6,abs(b)*1e-4)) if tolerant else type(a) is int and a==b
    if isinstance(b,dict): return isinstance(a,dict) and set(a)==set(b) and all(equal(a[k],v,path+'.'+k) for k,v in b.items())
    if isinstance(b,list):
        if not isinstance(a,list) or len(a)!=len(b): return False
        # Outer collections are multisets; nested row positions retain their meaning.
        if path.count('[]')==0:
            remaining=list(a)
            for v in b:
                i=next((i for i,x in enumerate(remaining) if equal(x,v,path+'[]')),None)
                if i is None:return False
                remaining.pop(i)
            return True
        return all(equal(x,y,path+'[]') for x,y in zip(a,b))
    return type(a) is type(b) and a==b
def union_seconds(spans):
    spans=sorted((float(a),float(b)) for a,b in spans if b>=a)
    total=0.; end=None
    for a,b in spans:
        total+=b-max(a,end if end is not None else a) if end is None or b>end else 0
        end=max(b,end if end is not None else b)
    return total
