"""Refresh byte-level hashes after an intentional public release change."""
from pathlib import Path
import hashlib,json
R=Path(__file__).resolve().parents[1]
files={}
for p in sorted(R.rglob('*')):
    if not p.is_file() or any(x in p.parts for x in ['__pycache__','reproduced']):continue
    rel=p.relative_to(R).as_posix()
    if rel=='provenance/public_manifest.json':continue
    data=p.read_bytes();files[rel]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
(R/'provenance/public_manifest.json').write_text(json.dumps({'release':'WELD-20261016','files':files},indent=2)+'\n',encoding='utf8')
print('Manifest:',len(files),'files')
