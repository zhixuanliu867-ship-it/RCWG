"""Canonical, bounded JSON construction for generated sources and private gold."""
import hashlib,os
from rcwg_full.evidence import canonical


class JsonRows:
    def __init__(self,factory,count):self.factory=factory;self.count=count
    def __iter__(self):return iter(self.factory())


def write_json_stream(path,value,*,fragmented=False):
    logical=hashlib.sha256();max_scalar_bytes=0
    with path.open('xb') as file:
        def token(raw):
            nonlocal max_scalar_bytes
            logical.update(raw);file.write(raw);max_scalar_bytes=max(max_scalar_bytes,len(raw))
        def emit(item):
            if isinstance(item,(JsonRows,list,tuple)):
                token(b'[');count=0
                for child in item:
                    if count:token(b',')
                    if fragmented:file.write(b'\n ')
                    emit(child);count+=1
                token(b']')
                if isinstance(item,JsonRows) and count!=item.count:raise ValueError('JSON_STREAM_COUNT')
            elif isinstance(item,dict):
                token(b'{')
                for i,key in enumerate(sorted(item)):
                    if i:token(b',')
                    token(canonical(key));token(b':');emit(item[key])
                token(b'}')
            else:token(canonical(item))
        emit(value);file.write(b'\n');file.flush();os.fsync(file.fileno())
    with path.open('rb') as file:physical=hashlib.file_digest(file,'sha256').hexdigest()
    return logical.hexdigest(),physical,path.stat().st_size,{'maximum_encoded_scalar_bytes':max_scalar_bytes,'whole_collection_materialized':False}
