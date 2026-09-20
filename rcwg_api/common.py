"""Strict small JSON records and private exclusive archives."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')

class ApiError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def fail(code: str):
    raise ApiError(code) from None

def canonical(obj) -> bytes:
    try:
        return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (TypeError,ValueError,UnicodeError,RecursionError):
        fail('JSON_VALUE_INVALID')

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def digest(obj) -> str:
    return sha(canonical(obj))

def strict(raw: bytes, *, limit: int = 2_097_152):
    if type(raw) is not bytes or not raw or len(raw)>limit: fail('JSON_BYTE_LIMIT')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:fail('JSON_DUPLICATE_KEY')
            result[key]=value
        return result
    def number(text):
        value=float(text)
        if not math.isfinite(value):fail('JSON_NONFINITE')
        return value
    def constant(_):fail('JSON_NONFINITE')
    try:
        return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_float=number,parse_constant=constant)
    except ApiError:raise
    except (UnicodeError,ValueError,TypeError,RecursionError,OverflowError):fail('JSON_INVALID')

def read(path: Path):
    path=Path(path)
    if path.is_symlink():fail('PRIVATE_SYMLINK')
    return strict(path.read_bytes())

def integer(value, low=0, high=10**12):
    return type(value) is int and low<=value<=high

def private_path(path: Path, *, must_exist=False):
    path=Path(path).absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):fail('PRIVATE_SYMLINK')
    if must_exist and not path.is_file():fail('PRIVATE_FILE_MISSING')
    return path

class Archive:
    def __init__(self, path: Path):
        self.path=private_path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path.mkdir(mode=0o700,exist_ok=False)
    def put(self,name: str,raw: bytes):
        if type(name) is not str or not ID.fullmatch(name) or type(raw) is not bytes:fail('ARCHIVE_NAME')
        fd=os.open(self.path/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        return sha(raw)
    def json(self,name,obj):return self.put(name,canonical(obj))

def seal_tree(path: Path, *, ignore=frozenset()):
    entries={}
    for p in sorted(Path(path).rglob('*')):
        if p.is_symlink():fail('SEAL_SYMLINK')
        if p.is_file() and str(p.relative_to(path)) not in ignore:
            entries[str(p.relative_to(path))]=sha(p.read_bytes())
    return entries
