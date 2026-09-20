"""Per-run cgroup v2 interfaces. Reading the host never grants write authority."""
from dataclasses import dataclass
from pathlib import Path
import math
import os
import time
from .evidence import no_symlink, run_id

class FacilityFault(RuntimeError):
    pass

@dataclass(frozen=True)
class Limits:
    memory_max: int=134217728
    cpu_quota_us: int=100000
    cpu_period_us: int=100000
    swap_max: int=0
    affinity: tuple=(0,)
    threads: int=1
    timeout_s: float=30.0
    def validate(self):
        integers=(self.memory_max,self.cpu_quota_us,self.cpu_period_us,self.swap_max,self.threads)
        if any(type(v) is not int for v in integers):raise FacilityFault('LIMIT_TYPE_INVALID')
        if not 16777216<=self.memory_max<=536870912 or not 1000<=self.cpu_quota_us<=100000 or self.cpu_period_us!=100000 or self.swap_max!=0 or self.threads!=1:
            raise FacilityFault('LIMIT_PROFILE_UNSUPPORTED')
        if not self.affinity or any(type(v) is not int or v<0 for v in self.affinity) or len(set(self.affinity))!=len(self.affinity):raise FacilityFault('AFFINITY_INVALID')
        if not isinstance(self.timeout_s,(int,float)) or isinstance(self.timeout_s,bool) or not math.isfinite(self.timeout_s) or not 0<self.timeout_s<=120:raise FacilityFault('TIMEOUT_INVALID')

class LinuxFS:
    is_real=True
    def __init__(self,root,*,approval):
        self.root=no_symlink(root)
        if not approval or approval.get('approved') is not True or approval.get('delegated_root')!=str(self.root) or approval.get('permission')!='NATIVE001_N4_PER_RUN_CGROUP':
            raise FacilityFault('BLOCKED_RUNTIME_HOST_APPROVAL')
        if self.root==Path('/sys/fs/cgroup') or not self.root.is_relative_to('/sys/fs/cgroup'):
            raise FacilityFault('SHARED_OR_NON_CGROUP_ROOT_REJECTED')
        if not self.root.is_dir() or self.root.stat().st_uid!=os.getuid() or not os.access(self.root,os.W_OK):
            raise FacilityFault('BLOCKED_RUNTIME_HOST_APPROVAL')
        enabled=set((self.root/'cgroup.subtree_control').read_text().split())
        if not {'cpu','memory','io'}<=enabled:raise FacilityFault('CONTROLLER_DELEGATION_REQUIRED')
        self.owned={}
    def create(self,name):
        path=self.root/run_id(name);path.mkdir(mode=0o700)
        self.owned[name]=(path.stat().st_dev,path.stat().st_ino)
    def _path(self,name,key):
        if name not in self.owned or '/' in key or key.startswith('.'):
            raise FacilityFault('CGROUP_SCOPE_VIOLATION')
        path=no_symlink(self.root/name)
        if (path.stat().st_dev,path.stat().st_ino)!=self.owned[name]:raise FacilityFault('CGROUP_IDENTITY_CHANGED')
        return no_symlink(path/key)
    def read(self,name,key):return self._path(name,key).read_text()
    def write(self,name,key,value):
        fd=os.open(self._path(name,key),os.O_WRONLY|os.O_NOFOLLOW)
        try:
            raw=str(value).encode();n=os.write(fd,raw)
            if n!=len(raw):raise FacilityFault('CGROUP_SHORT_WRITE')
        finally:os.close(fd)
    def remove(self,name):
        path=self._path(name,'cgroup.events').parent
        path.rmdir();del self.owned[name]
    def child_entry_fd(self,name):return os.open(self._path(name,'cgroup.procs'),os.O_WRONLY|os.O_NOFOLLOW)

class FakeFS:
    """Explicit SIMULATED implementation, never an isolation attestation."""
    is_real=False
    def __init__(self,fail=None,initial=None):self.groups={};self.ops=[];self.fail=fail;self.initial=initial or {}
    def _op(self,*a):
        self.ops.append(a)
        if self.fail==a[0] or self.fail==':'.join(a[:2]):raise OSError('SIMULATED_FAILURE')
    def create(self,name):
        self._op('create',name)
        if name in self.groups:raise FileExistsError(name)
        self.groups[name]={'cpu.stat':'usage_usec 0\nnr_throttled 0\nthrottled_usec 0\n','memory.peak':'0','memory.current':'0','memory.events':'oom 0\noom_kill 0\n','io.stat':'','cgroup.events':'populated 0\n','cgroup.procs':'',**self.initial}
    def write(self,name,key,value):
        self._op('write',key)
        self.groups[name][key]=str(value)
        if key=='cgroup.kill':self.groups[name]['cgroup.events']='populated 0\n';self.groups[name]['cgroup.procs']=''
    def read(self,name,key):self._op('read',key);return self.groups[name][key]
    def remove(self,name):self._op('remove',name);del self.groups[name]

def pairs(raw):
    result={}
    for line in raw.splitlines():
        parts=line.split()
        if len(parts)!=2 or parts[0] in result:raise ValueError('MALFORMED_COUNTER')
        value=int(parts[1])
        if value<0:raise ValueError('NEGATIVE_COUNTER')
        result[parts[0]]=value
    return result

def block_io(raw):
    result={}
    for line in raw.splitlines():
        bits=line.split();device=bits[0]
        if device in result or len(device.split(':'))!=2 or not all(p.isdigit() for p in device.split(':')):raise ValueError('IO_DEVICE_INVALID')
        fields={}
        for bit in bits[1:]:
            k,v=bit.split('=');n=int(v)
            if k in fields or n<0:raise ValueError('IO_COUNTER_INVALID')
            fields[k]=n
        result[device]=fields
    return result

class Driver:
    def __init__(self,fs,ident,limits):
        self.fs=fs;self.ident=run_id(ident);self.limits=limits;self.created=False;self.baseline=None;self.samples=[]
    def snapshot(self):
        out={};missing={}
        for key,parser in [('cpu.stat',pairs),('memory.peak',int),('memory.current',int),('memory.events',pairs),('io.stat',block_io)]:
            try:
                out[key]=parser(self.fs.read(self.ident,key))
                if isinstance(out[key],int) and out[key]<0:raise ValueError('NEGATIVE_COUNTER')
            except (OSError,KeyError,ValueError) as e:out[key]=None;missing[key]=type(e).__name__
        return {'values':out,'missing':missing}
    def prepare(self):
        self.limits.validate()
        self.fs.create(self.ident);self.created=True
        initial=self.snapshot()
        cpu=initial['values']['cpu.stat']
        if initial['values']['memory.peak']!=0 or not cpu or cpu.get('usage_usec')!=0:
            raise FacilityFault('FRESH_ZERO_ACCOUNTING_REQUIRED')
        settings={'cpu.max':f'{self.limits.cpu_quota_us} {self.limits.cpu_period_us}',
                  'memory.max':str(self.limits.memory_max),'memory.swap.max':str(self.limits.swap_max)}
        for key,value in settings.items():
            self.fs.write(self.ident,key,value)
            if self.fs.read(self.ident,key).strip()!=value:raise FacilityFault('LIMIT_READBACK_MISMATCH')
        # The cgroup.kill interface is mandatory for this version: no untested fallback.
        if self.fs.is_real and not self.fs._path(self.ident,'cgroup.kill').exists():raise FacilityFault('CGROUP_KILL_REQUIRED')
        self.baseline=self.snapshot()
        if self.baseline['missing']:raise FacilityFault('INITIAL_COUNTERS_REQUIRED')
    def sample(self):
        try:
            value=int(self.fs.read(self.ident,'memory.current'))
            if value<0:raise ValueError('NEGATIVE_COUNTER')
        except (OSError,KeyError,ValueError):value=None
        self.samples.append({'monotonic_ns':time.monotonic_ns(),'memory_current_bytes':value})
    def empty(self):return pairs(self.fs.read(self.ident,'cgroup.events')).get('populated')==0
    def kill(self):self.fs.write(self.ident,'cgroup.kill','1')
    def finish(self,*,wait_s=1.0):
        if not self.created:return {'status':'NOT_CREATED','formal_isolation_verified':False,'budget_within':None}
        self.kill();deadline=time.monotonic()+wait_s
        while not self.empty():
            if time.monotonic()>=deadline:raise FacilityFault('DESCENDANTS_REMAIN')
            time.sleep(0.01)
        final=self.snapshot();base=self.baseline or {'values':{}}
        cpu0=base['values'].get('cpu.stat');cpu1=final['values'].get('cpu.stat');cpu=None
        if cpu0 and cpu1 and 'usage_usec' in cpu0 and 'usage_usec' in cpu1:
            cpu=cpu1['usage_usec']-cpu0['usage_usec']
            if cpu<0:cpu=None;final['missing']['cpu.stat']='COUNTER_REGRESSION'
        events0=base['values'].get('memory.events');events1=final['values'].get('memory.events');oom_delta=None
        if events0 is not None and events1 is not None and 'oom_kill' in events0 and 'oom_kill' in events1:
            oom_delta=events1['oom_kill']-events0['oom_kill']
            if oom_delta<0:oom_delta=None;final['missing']['memory.events']='COUNTER_REGRESSION'
        local_oom_delta=None
        if events0 is not None and events1 is not None and 'oom' in events0 and 'oom' in events1:
            local_oom_delta=events1['oom']-events0['oom']
            if local_oom_delta<0:local_oom_delta=None;final['missing']['memory.events']='COUNTER_REGRESSION'
        report={'status':'COUNTERS_OBSERVED' if not final['missing'] else 'MEASUREMENT_MISSING','evidence_kind':'LOCAL_CGROUP_UNCALIBRATED' if self.fs.is_real else 'SIMULATED',
                'cpu_usage_usec':cpu,'worker_peak_ram_bytes':final['values']['memory.peak'],'oom_kill_delta':oom_delta,'run_memory_oom_delta':local_oom_delta,
                'baseline':self.baseline,'final':final,'memory_current_samples':self.samples,'sample_interval_ms':100,
                'library_copy_bytes':None,'dram_bytes':None,'formal_isolation_verified':False,'calibrated':False,'budget_within':None,'formal_ready':False}
        self.fs.remove(self.ident);self.created=False
        return report

def unavailable():
    return {'status':'BLOCKED_RUNTIME_HOST_APPROVAL','evidence_kind':'LOCAL_UNISOLATED',
            'cpu_usage_usec':None,'worker_peak_ram_bytes':None,'oom_kill_delta':None,'block_io':None,
            'library_copy_bytes':None,'dram_bytes':None,'budget_within':None,'calibrated':False,'formal_ready':False,
            'missing_reason':'NO_APPROVED_PER_RUN_CGROUP','memory_current_samples':[]}
