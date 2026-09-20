"""Exclusive private artifacts and independently supplied integrity anchors."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def sha(value):
    return hashlib.sha256(value).hexdigest()

def no_symlink(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('SYMLINK_PATH_REJECTED')
    return path

def fresh(path):
    path=no_symlink(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.mkdir(mode=0o700)
    return path

def write(path,value):
    path=no_symlink(path)
    raw=value if isinstance(value,bytes) else canonical(value)+b'\n'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    return sha(raw)

def read(path):
    path=no_symlink(path)
    with path.open('rb') as f:raw=f.read()
    return json.loads(raw)

def source_hashes():
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted((ROOT/'native001').glob('*')) if p.is_file()}

def closure_hashes():
    paths=[p for folder in ['native001','rcwg_native','specs/native001'] for p in (ROOT/folder).glob('*') if p.is_file() and p.suffix in {'.cpp','.hpp','.py','.json'}]
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(paths)}

def git_state():
    def get(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
    return {'head':get('rev-parse','HEAD'),'tree':get('rev-parse','HEAD^{tree}'),'index_tree':get('write-tree')}

def bootstrap(output):
    out=fresh(output)
    write(out/'STARTUP.json',{'output':str(out),'python':sys.version,'git':git_state(),'formal_ready':False})
    return out

def run_id(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',value):
        raise ValueError('RUN_ID_INVALID')
    return value

def seal(directory):
    directory=Path(directory)
    files={p.name:sha(p.read_bytes()) for p in sorted(directory.iterdir()) if p.is_file() and p.name!='seal.json'}
    return write(directory/'seal.json',{'revision':'NATIVE001_SEAL_V1','files':files})

def reread(directory,anchor):
    directory=no_symlink(directory)
    raw=(directory/'seal.json').read_bytes()
    if sha(raw)!=anchor:raise ValueError('EXTERNAL_SEAL_ANCHOR_MISMATCH')
    manifest=json.loads(raw)
    for name,digest in manifest['files'].items():
        if Path(name).name!=name or sha(no_symlink(directory/name).read_bytes())!=digest:
            raise ValueError('SEALED_CONTENT_CHANGED')
    return manifest
