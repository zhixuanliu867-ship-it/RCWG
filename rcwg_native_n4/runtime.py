"""Approved single-run controller inside a watchdog child; no Python preexec_fn."""
from pathlib import Path
import json,os,signal,subprocess,time
from rcwg_native.evidence import canonical,sha,write,read,seal,reread,no_symlink
from rcwg_native.metrology import Driver,Limits,LinuxFS,FacilityFault,pairs
from rcwg_native.supervisor import audit_worker
from .evidence import Journal
from .statistics import classify_oom,sample_gaps

def verify_membership(pid,group,affinity):
    actual=Path(f'/proc/{pid}/cgroup').read_text().strip()
    expected='0::/'+str(Path(group).relative_to('/sys/fs/cgroup'))
    observed=sorted(os.sched_getaffinity(pid))
    if actual!=expected or observed!=list(affinity):raise FacilityFault('PRE_EXEC_MEMBERSHIP_OR_AFFINITY_MISMATCH')
    return {'membership':actual,'affinity':observed}

def process_evidence(directory,group,affinity,leader,offspring):
    records=[];errors=[];expected='0::/'+str(Path(group).relative_to('/sys/fs/cgroup'))
    for path in sorted(Path(directory).glob('process-*.txt')):
        raw=path.read_text()
        try:
            lines=raw.splitlines();pid=int(lines[0]);parent=int(lines[1]);cpus=[int(x) for x in lines[3].split(',') if x]
            if lines[2]!=expected or cpus!=list(affinity) or path.name!=f'process-{pid}.txt':raise ValueError('PROCESS_BINDING_MISMATCH')
            if pid!=leader and parent!=leader:raise ValueError('UNEXPECTED_PARENT')
            records.append({'pid':pid,'ppid':parent,'membership':lines[2],'affinity':cpus,'raw':raw})
        except (ValueError,IndexError) as e:errors.append({'file':path.name,'raw':raw,'error':str(e)})
    pids=[r['pid'] for r in records]
    if len(set(pids))!=len(pids) or leader not in pids or len(pids)!=offspring+1:errors.append({'error':'PROCESS_DENOMINATOR_INCOMPLETE'})
    return {'status':'PASS' if not errors else 'INCONCLUSIVE','expected_processes':offspring+1,'records':records,'errors':errors}

def host_event_evidence(service):
    result={}
    for path in ['/proc/vmstat','/proc/pressure/memory','/proc/meminfo']:
        try:result[path]={'raw':Path(path).read_text(),'missing':None}
        except OSError as e:result[path]={'raw':None,'missing':type(e).__name__}
    for name,args in [('service',['systemctl','show',service,'--property=Result,ExecMainCode,ExecMainStatus,ActiveState,SubState,ControlGroup']),('kernel_oom',['journalctl','-k','-b','-n','50','--no-pager','--output=json','--grep=oom-kill|Killed process|Out of memory'])]:
        try:
            p=subprocess.run(args,capture_output=True,timeout=2)
            result[name]={'command':args,'exit_code':p.returncode,'stdout':p.stdout[:262144].decode(errors='replace'),'stderr':p.stderr[:8192].decode(errors='replace'),'truncated':len(p.stdout)>262144,'privilege_escalation':False}
        except (OSError,subprocess.SubprocessError) as e:result[name]={'missing':type(e).__name__,'privilege_escalation':False}
    return result

def context_snapshot(root):
    """Accessible run, local/hierarchical and ancestor raw counters; no log privilege."""
    keys=['memory.events','memory.events.local','memory.max','memory.current','memory.peak','memory.stat','memory.pressure','cpu.stat','cpu.pressure','io.stat','io.pressure','pids.current','pids.max','cgroup.events','cgroup.procs']
    out={};p=Path(root)
    while p.is_relative_to('/sys/fs/cgroup'):
        row={}
        for key in keys:
            try:row[key]={'raw':(p/key).read_text(),'missing':None}
            except OSError as e:row[key]={'raw':None,'missing':type(e).__name__}
        out[str(p)]=row
        if p==Path('/sys/fs/cgroup'):break
        p=p.parent
    return out

def one(slot,plan,directory,authorization=None):
    from .approval import validate
    if authorization is None:raise FacilityFault('EXPLICIT_OWNER_RECEIPT_REQUIRED')
    approved,receipt,manifest=validate(*authorization)
    if approved!=plan or slot not in manifest['slots']:raise FacilityFault('SLOT_NOT_AUTHORIZED')
    out=Path(directory);journal=Journal(out/'journal');journal.emit('DECLARED',slot)
    result={'run_id':slot['run_id'],'slot_sha256':sha(canonical(slot)),'terminal_status':'INFRA_FAILURE','verification':'UNKNOWN','budget_within':None,'calibrated':False,'formal_ready':False,'measurements':None,'cleanup':None,'expected_slots':1}
    fs=LinuxFS(plan['delegated_root'],approval={'approved':True,'delegated_root':plan['delegated_root'],'permission':'NATIVE001_N4_PER_RUN_CGROUP'})
    limits=Limits(memory_max=slot['memory_max'],cpu_quota_us=slot['cpu_quota_us'],affinity=(plan['host']['affinity'][0],),timeout_s=slot['timeout_s'])
    driver=Driver(fs,slot['run_id'],limits);driver.persist=journal.emit
    proc=None;handles=[];fds=[];reason=None;start=time.monotonic_ns();worker_start=None
    group=Path(plan['delegated_root'])/slot['run_id'];before=None;after=None;report=None
    try:
        driver.prepare();fs.write(slot['run_id'],'pids.max',str(slot['pids_max']))
        if fs.read(slot['run_id'],'pids.max').strip()!=str(slot['pids_max']):raise FacilityFault('PIDS_READBACK_MISMATCH')
        before=context_snapshot(group);journal.emit('BEFORE',before)
        result['host_events_before']=host_event_evidence(plan['service']);journal.emit('HOST_BEFORE',result['host_events_before'])
        for name in ['worker.stdout.json','worker.stderr.log']:
            f=(out/name).open('xb');handles.append(f)
        cmd=[plan['binaries']['calibration']['path'],slot['mode'],str(slot['batch'])];stdin=subprocess.DEVNULL
        if slot['mode']=='f1':
            bundle=read(slot['input_path']);raw=canonical(bundle['request'])+b'\n';write(out/'request.json',raw)
            f=(out/'request.json').open('rb');handles.append(f);stdin=f;cmd=[plan['binaries']['f1']['path']]
            write(out/'expected_manifest.json',{'run_id':slot['run_id'],'request_sha256':sha(raw),'input_sha256':slot['input_sha256'],'slot_sha256':result['slot_sha256']})
        entry=fs.child_entry_fd(slot['run_id']);ack_r,ack_w=os.pipe();go_r,go_w=os.pipe();fds=[entry,ack_r,ack_w,go_r,go_w];os.set_blocking(ack_r,False)
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','RCWG_N4_ISOLATED':'receipt-gated-v1'}
        args=[plan['binaries']['launcher']['path'],'--n4-launch',str(entry),str(ack_w),str(go_r),str(limits.affinity[0]),'--',*cmd]
        journal.emit('SPAWNING',{'argv':args,'monotonic_ns':time.monotonic_ns()})
        proc=subprocess.Popen(args,cwd=out,env=env,stdin=stdin,stdout=handles[0],stderr=handles[1],pass_fds=(entry,ack_w,go_r),start_new_session=True,close_fds=True)
        os.close(entry);fds.remove(entry);os.close(ack_w);fds.remove(ack_w)
        deadline=time.monotonic()+slot['timeout_s'];next_sample=time.monotonic();ack=b'';pid_membership=None;cancel_at=time.monotonic()+(slot.get('cancel_after_s') or 100000)
        while True:
            try:
                chunk=os.read(ack_r,64)
                if chunk:ack+=chunk
            except BlockingIOError:pass
            if ack and worker_start is None:
                worker_start=time.monotonic_ns()
                if ack.decode()!=str(proc.pid):raise FacilityFault('LAUNCH_ACK_PID_MISMATCH')
                observed=verify_membership(proc.pid,group,limits.affinity);pid_membership=observed['membership']
                journal.emit('LAUNCH_ACK',{'pid':proc.pid,'ack':ack.decode(),**observed})
                if os.write(go_w,b'1')!=1:raise FacilityFault('LAUNCH_GO_FAILED')
            if proc.poll() is not None:break
            now=time.monotonic()
            if now>=deadline:reason='TIMEOUT';break
            if now>=cancel_at:reason='CANCELLED';break
            if slot['sampler'] and now>=next_sample:
                driver.sample();next_sample=now+0.1
            time.sleep(0.005)
        if not ack:raise FacilityFault('LAUNCH_HANDSHAKE_MISSING')
        result['launch_ack']={'pid':proc.pid,'ack':ack.decode(),'membership':pid_membership,'group_expected':str(group)}
        if reason:driver.kill()
        proc.wait(timeout=2)
        journal.emit('WORKER_EXIT',{'returncode':proc.returncode,'reason':reason,'monotonic_ns':time.monotonic_ns()})
        after=context_snapshot(group);journal.emit('AFTER',after)
        result['terminal_status']=reason or ('COMPLETED' if proc.returncode==0 else 'PROCESS_FAILED')
        result['returncode']=proc.returncode
        if slot.get('fault')=='collection':driver.fs.read=lambda *a:(_ for _ in ()).throw(OSError('PREREGISTERED_COLLECTION_FAULT'))
        if slot.get('fault')=='controller':journal.emit('EXPECTED_CONTROLLER_EXIT',{'code':88});os._exit(88)
    except Exception as e:result['reason']=type(e).__name__+':'+str(e)
    finally:
        for f in handles:f.close()
        for fd in fds:os.close(fd)
        try:result['measurements']=driver.finish()
        except Exception as e:
            result['measurements']=getattr(e,'report',None) or driver.last_report
            result['terminal_status']='INFRA_FAILURE';result['reason']='FINALIZE:'+str(e)
        if proc:
            try:proc.wait(timeout=1)
            except subprocess.TimeoutExpired:result['terminal_status']='INFRA_FAILURE';result['reason']='PROCESS_NOT_REAPED'
    result['controller_wall_ns_before_verifier']=time.monotonic_ns()-start
    result['worker_observed_ns']=None if worker_start is None else time.monotonic_ns()-worker_start
    result['context_before']=before;result['context_after']=after
    result['host_events_after']=host_event_evidence(plan['service']);journal.emit('HOST_AFTER',result['host_events_after'])
    if proc and slot['mode']!='f1':result['process_evidence']=process_evidence(out,group,limits.affinity,proc.pid,slot['offspring_total_max'])
    result['kernel_oom_cause']={'status':'UNKNOWN','reason':'No uniquely bound kernel victim record; event coincidence insufficient; no privileged journal access requested'}
    verify_start=time.monotonic_ns()
    try:
        if result['terminal_status']=='COMPLETED':
            if slot['mode']=='f1':
                # Preserve raw stdout under the established audit interface.
                write(out/'worker.report.json',(out/'worker.stdout.json').read_bytes())
                report,events=audit_worker(out,read(out/'expected_manifest.json'))
                result['verification']='PASS' if read(out/'result.json')==read(slot['input_path'])['gold'] else 'FAIL'
                result['worker_report']=report;result['worker_exec_wall_ns']=report['worker_exec_wall_ns']
            else:
                report=read(out/'worker.stdout.json');result['worker_exec_wall_ns']=report['wall_ns']
                result['verification']='PASS' if report['mode']==slot['mode'] and report['batch']==slot['batch'] else 'FAIL';result['worker_report']=report
    except Exception as e:result['verification']='UNKNOWN';result['terminal_status']='INFRA_FAILURE';result['reason']='VERIFY:'+str(e)
    result['verifier_wall_ns']=time.monotonic_ns()-verify_start
    if result['measurements']:
        result['cleanup']=result['measurements'].get('cleanup');result['sample_gaps']=sample_gaps(result['measurements'].get('memory_current_samples',[]))
    anchor=journal.emit('TERMINAL',result);write(out/'JOURNAL_ANCHOR.json',{'sha256':anchor});write(out/'terminal.json',result)
    try:
        if slot.get('fault')=='seal':raise OSError('PREREGISTERED_SEAL_FAULT')
        anchor=seal(out);reread(out,anchor);write(out/'seal.anchor',anchor.encode())
    except Exception as e:
        write(out/'ARCHIVE_FAILURE.json',{'error':str(e),'retained_terminal_sha256':sha((out/'terminal.json').read_bytes())})
        raise FacilityFault('ARCHIVE_FAILED') from e
    return result
