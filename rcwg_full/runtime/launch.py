"""Versioned launcher adapter; N4 membership check and Driver remain shared."""
from pathlib import Path
import json
import math
import os
import time
from rcwg_full.evidence import read,sha,write
from rcwg_native.metrology import FacilityFault,Limits,LinuxFS,Driver
from rcwg_native_n4.runtime import verify_membership
from rcwg_full.campaign.sealing import validate_receipt


class FullLimits(Limits):
    def validate(self):
        values=(self.memory_max,self.cpu_quota_us,self.cpu_period_us,self.swap_max,self.threads)
        if any(type(v) is not int for v in values):raise FacilityFault('FULL001_LIMIT_TYPES')
        if (not 16777216<=self.memory_max<=1024**4 or self.cpu_period_us!=100000 or
            not 1000<=self.cpu_quota_us<=800000 or self.swap_max!=0 or not 1<=self.threads<=8):raise FacilityFault('FULL001_LIMITS')
        if (not self.affinity or len(self.affinity)>8 or len(set(self.affinity))!=len(self.affinity) or
            any(type(v) is not int or not 0<=v<1024 for v in self.affinity)):raise FacilityFault('FULL001_AFFINITY')
        if type(self.timeout_s) not in {int,float} or not math.isfinite(self.timeout_s) or not 0<self.timeout_s<=3600:raise FacilityFault('FULL001_TIMEOUT')


def approved_driver(host_scope,receipt,task,run_id,*,source_hash,build_hash):
    """No controller enabling, system service mutation or calibration is implicit."""
    from rcwg_full.evidence import digest,safe_path
    validate_receipt(receipt,action='HOST',subject_hash=digest(host_scope),actor_role='Owner')
    if host_scope.get('revision')!='FULL001_HOST_SCOPE_1' or host_scope.get('source_hash')!=source_hash or host_scope.get('build_hash')!=build_hash:
        raise PermissionError('HOST_SOURCE_BUILD_SCOPE')
    if digest(task) not in host_scope.get('task_hashes',[]):raise PermissionError('HOST_TASK_NOT_APPROVED')
    if run_id not in host_scope.get('run_ids',[]):raise PermissionError('HOST_RUN_NOT_APPROVED')
    if os.name!='posix':raise PermissionError('LINUX_CGROUP_REQUIRED')
    root=safe_path(host_scope['delegated_root'])
    # LinuxFS's narrow file operations and identity tracking are reused. The
    # approval here is FULL001's exact receipt, not the historical 888-slot plan.
    fs=LinuxFS(root,approval={'approved':True,'delegated_root':str(root),'permission':'NATIVE001_N4_PER_RUN_CGROUP'})
    resources=task['resources'];affinity=tuple(host_scope['affinity'])
    if len(affinity)!=resources['cpu_slots']:raise PermissionError('HOST_CPU_SLOT_BINDING')
    limits=FullLimits(memory_max=resources['worker_memory_limit_bytes'],cpu_quota_us=100000*resources['cpu_slots'],
                      affinity=affinity,threads=resources['cpu_slots'],timeout_s=resources['wall_timeout_s'])
    limits.validate()
    driver=Driver(fs,run_id,limits);driver.full001_authorization={'scope_hash':digest(host_scope),'receipt_hash':digest(receipt),
       'pids_max':host_scope['pids_max'],'output_file_max_bytes':host_scope['output_file_max_bytes']}
    return driver


class Handshake:
    def __init__(self,driver,build,command):
        self.driver=driver;self.fds=[];self.ack=b'';self.go_ns=None
        self.ack_r,self.ack_w=os.pipe();self.go_r,self.go_w=os.pipe()
        self.fds=[self.ack_r,self.ack_w,self.go_r,self.go_w];os.set_blocking(self.ack_r,False)
        if driver:
            auth=getattr(driver,'full001_authorization',None)
            if auth is None:raise PermissionError('FULL001_LAUNCH_RECEIPT_REQUIRED')
            manifest=json.loads(read(Path(build)/'BUILD.json'));entry=manifest['binaries']['launcher']
            path=Path(build)/entry['name']
            if sha(read(path))!=entry['sha256']:raise ValueError('LAUNCHER_HASH')
            fd=driver.fs.child_entry_fd(driver.ident);self.fds.append(fd)
            self.pass_fds=(fd,self.ack_w,self.go_r)
            self.command=[str(path),'--full001-launch',str(fd),str(self.ack_w),str(self.go_r),
                ','.join(map(str,driver.limits.affinity)),str(auth['output_file_max_bytes']),str(math.ceil(driver.limits.timeout_s*driver.limits.threads)+1),'--',*command]
        else:
            self.pass_fds=(self.ack_w,self.go_r)
            self.command=[*command,'--ack-fd',str(self.ack_w),'--go-fd',str(self.go_r)]

    def spawned(self):
        for fd in self.pass_fds:
            os.close(fd);self.fds.remove(fd)

    def ready(self,proc,go_path,run_id):
        if self.go_ns is not None:return None
        try:
            chunk=os.read(self.ack_r,64)
            if chunk:self.ack+=chunk
        except BlockingIOError:return None
        # Only decide at EOF, so a short pipe read cannot look like a wrong PID.
        if chunk:return None
        if not self.ack or self.ack.decode('ascii')!=str(proc.pid):raise FacilityFault('LAUNCH_ACK_PID_MISMATCH')
        evidence={'pid':proc.pid,'ack':self.ack.decode(),'membership':'NOT_MEASURED_ENGINEERING'}
        if self.driver:
            evidence.update(verify_membership(proc.pid,self.driver.fs.root/run_id,self.driver.limits.affinity))
        prepared_ns=time.monotonic_ns()
        write(go_path,{'run_id':run_id,'exec_started_monotonic_ns':prepared_ns,
            'clock_scope':'PREPARE_MARKER_ONLY_CONTROLLER_REPORT_HAS_ACTUAL_GO_CLOCK','launcher':evidence})
        self.go_ns=time.monotonic_ns()
        if os.write(self.go_w,b'1')!=1:raise FacilityFault('LAUNCH_GO_FAILED')
        return evidence

    def close(self):
        for fd in self.fds:
            try:os.close(fd)
            except OSError:pass
        self.fds=[]
