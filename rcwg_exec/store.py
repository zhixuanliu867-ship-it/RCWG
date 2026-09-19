"""Private exclusive write, with result bytes and identity sealed separately."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from rcwg_spec.common import canonical
from .errors import ExecFault

NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
class PrivateStore:
    def __init__(self, root: Path):
        root=Path(root)
        # Reject symlink components, including ancestors, before creating files.
        if any(p.is_symlink() for p in [root,*root.parents]): raise ExecFault('OUTPUT_SYMLINK')
        root.parent.mkdir(parents=True,exist_ok=True)
        root.mkdir(mode=0o700,exist_ok=False)
        self.root=root.resolve()
    def write_bytes(self,name,data):
        if not NAME.fullmatch(name):raise ExecFault('OUTPUT_NAME')
        temporary=self.root/('.'+name+'.'+uuid.uuid4().hex+'.part')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        # link is atomic and never replaces an existing target. Incomplete writes
        # remain .part files and can never masquerade as a sealed artifact.
        os.link(temporary,self.root/name,follow_symlinks=False)
        temporary.unlink()
        directory=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return hashlib.sha256(data).hexdigest()
    def write_json(self,name,obj):return self.write_bytes(name,canonical(obj))
    def artifact(self,rows,*,producer,source_refs,type_label,execution_key):
        content=canonical([dict(frame.values) for frame in rows]);h=self.write_bytes('result.json',content)
        meta={'artifact_id':'sha256:'+h,'content_sha256':h,'type':type_label,
              'producer':producer,'serialized_bytes':len(content),'rows':len(rows),
              'created_ns':time.perf_counter_ns(),'released_ns':None,'format':'json',
              'source_refs':source_refs}
        self.write_json('artifact.json',meta)
        self.write_json('artifact_binding.json',{'schema_version':'EXEC001_ARTIFACT_BINDING_0.1',
                         'execution_key':execution_key,'artifact_sha256':h,
                         'artifact_metadata_sha256':hashlib.sha256(canonical(meta)).hexdigest()})
        return meta
