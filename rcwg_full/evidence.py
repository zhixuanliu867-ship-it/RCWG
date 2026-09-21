"""Small durable I/O primitives shared by FULL001 tools; no implicit network."""
from pathlib import Path
import hashlib
import json
import os
import stat
import tempfile
from datetime import date,datetime,timezone

ROOT=Path(__file__).resolve().parents[1]


def canonical(value):
    def temporal(item):
        if isinstance(item,datetime):
            if item.tzinfo is None:raise ValueError('TIMESTAMP_TIMEZONE')
            return item.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
        if isinstance(item,date):return item.isoformat()
        raise TypeError('CANONICAL_JSON_TYPE')
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=temporal).encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(canonical(value))


def safe_path(path):
    path=Path(path).absolute()
    for parent in [path,*path.parents]:
        if parent.is_symlink():raise ValueError('SYMLINK_FORBIDDEN')
    return path


def exclusive_directory(path):
    path=safe_path(path)
    path.mkdir(parents=True,exist_ok=False,mode=0o700)
    return path


def write(path,value):
    path=safe_path(path)
    data=value if isinstance(value,bytes) else canonical(value)+b'\n'
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    return sha(data)


def read(path):
    path=safe_path(path)
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags)
    with os.fdopen(fd,'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('REGULAR_FILE_REQUIRED')
        return f.read()


def source_hashes():
    result={}
    for folder in ['rcwg_full','native_full001','rcwg_boot','rcwg_spec','rcwg_exec','rcwg_native','rcwg_native_n4','rcwg_api','rcwg_cloud','specs/full001','acceptance/full001','tests','native001_tests','native001_n4_tests']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.so','.pyd'}:
                result[p.relative_to(ROOT).as_posix()]=sha(p.read_bytes())
    for rel in ['native001/json.hpp','environments/full001/requirements.lock','scripts/build_full001.py']:
        p=ROOT/rel
        if p.is_file():result[rel]=sha(p.read_bytes())
    return result
