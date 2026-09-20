#!/usr/bin/env python3
"""Create an allowlisted reproducible source archive locally; never submit a build."""
import argparse,gzip,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_spec.common import canonical
from rcwg_cloud.source import RUNTIME_DIRS,RUNTIME_FILES

def build_context(repo,output):
    repo=Path(repo);output=Path(output)
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo)
    if git('status','--porcelain','--untracked-files=normal').strip():raise ValueError('CLEAN_COMMITTED_SOURCE_REQUIRED')
    commit=git('rev-parse','HEAD').decode().strip();entries={}
    for entry in git('ls-tree','-rz','HEAD').split(b'\0'):
        if not entry:continue
        meta,name=entry.split(b'\t',1);mode,kind,oid=meta.split();name=name.decode('utf-8')
        allowed=(name.split('/')[0] in RUNTIME_DIRS or name in RUNTIME_FILES)
        if not allowed:continue
        if mode not in (b'100644',b'100755') or kind!=b'blob':raise ValueError('BUILD_SOURCE_NONREGULAR')
        parts=Path(name).parts
        if any(p in ('runs','.venv','.git','__pycache__','.config','private','credentials') for p in parts) or name.endswith(('.pyc','.zip','.sqlite','.pem','.key')):raise ValueError('BUILD_SOURCE_PRIVATE_PATH')
        raw=git('cat-file','blob',oid.decode())
        # Existing public guard is also required before commit; this is defense
        # in depth against high-signal credential material in an allowed file.
        import re
        if re.search(rb'(?:ghp_[A-Za-z0-9]{30,}|ya29\.[A-Za-z0-9_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)',raw):raise ValueError('BUILD_SOURCE_CREDENTIAL_PATTERN')
        entries[name]=raw
    ignore=b'.git\nruns\n.venv\n**/__pycache__\n**/*.pyc\n'
    entries['.dockerignore']=ignore;entries['.gcloudignore']=ignore
    closure={'version':'CLOUD001_IMAGE_SOURCE_1','git_commit':commit,'files':{k:hashlib.sha256(v).hexdigest() for k,v in sorted(entries.items())}}
    entries['IMAGE_SOURCE.json']=canonical(closure)
    buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as compressed,tarfile.open(fileobj=compressed,mode='w') as tar:
        for name,raw in sorted(entries.items()):
            info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o644;info.mtime=0;info.uid=info.gid=0
            tar.addfile(info,io.BytesIO(raw))
    output.parent.mkdir(parents=True,exist_ok=True)
    raw=buffer.getvalue()
    with output.open('xb') as f:f.write(raw)
    result={'version':'CLOUD001_BUILD_SOURCE_PROOF_1','git_commit':commit,'source_archive_sha256':hashlib.sha256(raw).hexdigest(),
       'source_archive_bytes':len(raw),'image_source_sha256':hashlib.sha256(entries['IMAGE_SOURCE.json']).hexdigest(),'files':closure['files'],
       'cloud_build_submitted':False,'image_digest':None,'private_inputs_included':False}
    with output.with_suffix(output.suffix+'.json').open('xb') as f:f.write(canonical(result))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);args=p.parse_args()
    result=build_context(ROOT,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='files'},indent=2))
