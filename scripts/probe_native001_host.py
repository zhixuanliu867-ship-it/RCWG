"""Read-only host/delegation observations; never enables controllers or moves PIDs."""
from pathlib import Path
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_native.evidence import bootstrap,write

def probe():
    membership=Path('/proc/self/cgroup').read_text().strip()
    relative=membership.split('0::',1)[1] if membership.startswith('0::') else None
    current=Path('/sys/fs/cgroup')/relative.lstrip('/') if relative else None
    roots=[Path('/sys/fs/cgroup'),Path('/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service')]
    if current:roots.extend([current,current.parent])
    observations=[]
    for root in dict.fromkeys(roots):
        item={'path':str(root),'exists':root.is_dir(),'writable':os.access(root,os.W_OK),'files':{}}
        if root.is_dir():
            item['owner_uid']=root.stat().st_uid
            for name in ['cgroup.controllers','cgroup.subtree_control','cgroup.type','cgroup.events','memory.max','cpu.max']:
                try:item['files'][name]=(root/name).read_text().strip()
                except OSError:item['files'][name]=None
        observations.append(item)
    return {'schema':'NATIVE001_HOST_CAPABILITY_V1','python':platform.python_version(),'kernel':platform.release(),'libc':platform.libc_ver(),'uid':os.getuid(),'gid':os.getgid(),
            'systemd':subprocess.check_output(['systemctl','--version'],text=True).splitlines()[0],
            'compiler_paths':{c:shutil.which(c) for c in ['g++','clang++','c++']},'affinity':sorted(os.sched_getaffinity(0)),
            'current_membership':membership,'cgroup_observations':observations,'cgroup_writes':0,'model_requests':0,'cloud_calls':0,'system_installs':0,
            'delegation_authorized':False,'formal_isolation_verified':False,'formal_ready':False,'budget_within':None}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();out=bootstrap(args.output);result=probe();write(out/'HOST_CAPABILITY.json',result);print(json.dumps(result,indent=2))
