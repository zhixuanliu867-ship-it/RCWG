"""Minimal serialization compatibility for the inherited audited transport."""
import json,hashlib
from pathlib import Path
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(v,bytes):p.write_bytes(v)
    elif isinstance(v,str):p.write_text(v,encoding='utf-8')
    else:p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
