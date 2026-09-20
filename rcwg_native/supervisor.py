"""Bounded process supervisor; cgroup writes require a separately approved driver."""
from pathlib import Path
import json
import os
import signal
import subprocess
import time
from .evidence import canonical,sha,read,write,bootstrap,seal,reread,source_hashes,closure_hashes,no_symlink,run_id
from .metrology import FacilityFault,unavailable

def binary_binding(build,mode):
    build=no_symlink(build)
    m=read(build/'SOURCE_AND_BINARY_MANIFEST.json')
    if m.get('status')!='BUILD_PASS' or m.get('source')!=source_hashes():raise FacilityFault('BUILD_SOURCE_BINDING_MISMATCH')
    record=m['binaries'][mode]
    if Path(record['name']).name!=record['name']:raise FacilityFault('BINARY_PATH_INVALID')
    binary=no_symlink(build/record['name'])
    if sha(binary.read_bytes())!=record['sha256']:raise FacilityFault('BINARY_HASH_MISMATCH')
    return binary,m

def live_group(pgid):
    # A zombie cannot execute or retain user memory; retain its observation separately.
    live=[];zombie=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid:(zombie if fields[0]=='Z' else live).append(int(p.name))
        except (OSError,ValueError,IndexError):continue
    return {'live':live,'zombie':zombie}

def stop_group(proc):
    for sig in [signal.SIGTERM,signal.SIGKILL]:
        try:os.killpg(proc.pid,sig)
        except ProcessLookupError:pass
        try:proc.wait(timeout=0.15)
        except subprocess.TimeoutExpired:pass
        if not live_group(proc.pid)['live']:break
    try:proc.wait(timeout=1)
    except subprocess.TimeoutExpired:raise FacilityFault('LEADER_REMAINS')
    state=live_group(proc.pid)
    if state['live']:raise FacilityFault('DESCENDANTS_REMAIN')
    return state

def audit_worker(directory,expected):
    directory=Path(directory);request=read(directory/'request.json');report=read(directory/'worker.report.json')
    request_hash=sha((directory/'request.json').read_bytes())
    if request_hash!=expected['request_sha256'] or report.get('request_sha256')!=request_hash or report.get('run_id')!=expected['run_id']:raise FacilityFault('WORKER_BINDING_MISMATCH')
    raw=(directory/'worker.events.jsonl').read_bytes()
    if raw and not raw.endswith(b'\n'):raise FacilityFault('TRUNCATED_EVENTS')
    events=[];seen={};previous=-1
    nodes={n['id']:n for n in request['nodes']}
    for seq,line in enumerate(raw.splitlines()):
        try:event=json.loads(line)
        except (ValueError,UnicodeError):raise FacilityFault('MALFORMED_EVENTS') from None
        ident=event.get('node_id');node=nodes.get(ident)
        if (event.get('sequence')!=seq or event.get('run_id')!=expected['run_id'] or event.get('request_sha256')!=request_hash
            or type(event.get('monotonic_ns')) is not int or event['monotonic_ns']<previous or not node
            or event.get('operator')!=node['operator'] or event.get('implementation')!=node['implementation']):raise FacilityFault('EVENT_BINDING_INVALID')
        previous=event['monotonic_ns'];kind=event.get('kind');state=seen.get(ident)
        if (kind=='node_started' and state is None):seen[ident]='started'
        elif kind=='node_finished' and state=='started':seen[ident]='finished'
        else:raise FacilityFault('NODE_LIFECYCLE_INVALID')
        events.append(event)
    if report.get('terminal_status')=='COMPLETED':
        if set(seen)!=set(nodes) or any(v!='finished' for v in seen.values()):raise FacilityFault('NODE_COMPLETION_INCOMPLETE')
        result_raw=(directory/'result.json').read_bytes();result=json.loads(result_raw)
        if type(result) is not list or report.get('rows')!=len(result) or report.get('serialized_bytes')!=len(result_raw):raise FacilityFault('RESULT_METADATA_INVALID')
    return report,events

def execute(request,*,build,output,context,verify=None,driver=None,cancel=None,timeout_s=30.0,spawn=subprocess.Popen,archive=seal):
    """The context/verifier recipe stays parent-side. No worker receives gold."""
    ident=run_id(request['run_id']);out=bootstrap(output);start=time.monotonic_ns();states=[]
    def transition(state):
        states.append({'sequence':len(states),'state':state,'monotonic_ns':time.monotonic_ns()})
        write(out/('lifecycle-%02d.json'%len(states)),states[-1])
    transition('DECLARED')
    raw=canonical(request)+b'\n';write(out/'request.json',raw)
    expected={'revision':'NATIVE001_EXPECTED_V1','run_id':ident,'expected_slots':1,'request_sha256':sha(raw),'context':context,'source_closure':closure_hashes(),'formal_ready':False}
    # Binding failures remain a declared slot, rather than disappearing from the denominator.
    binary=None;binding_failure=None
    try:binary,manifest=binary_binding(build,request['mode']);expected['build_manifest']=manifest
    except (FacilityFault,OSError,ValueError,KeyError) as exc:binding_failure=str(exc)
    anchor=write(out/'expected_manifest.json',expected)
    result={'run_id':ident,'expected_manifest_sha256':anchor,'expected_slots':1,'terminal_status':'INFRA_FAILURE','failure':None,'execution_started':False,'verification':{'status':'UNKNOWN','reason':'NOT_EXECUTED'},'measurements':unavailable(),'formal_ready':False,'budget_within':None,'evidence_kind':'LOCAL_NATIVE_UNISOLATED','model_requests':0,'count_requests':0,'cloud_calls':0}
    proc=None;group_state=None;report=None;entry_fd=None;reason=None;files=[]
    if driver:
        counter_seq=[0]
        def persist_counter(stage,value):
            counter_seq[0]+=1
            write(out/('counter-%05d.json'%counter_seq[0]),{'stage':stage,'evidence':value})
        driver.persist=persist_counter
    try:
        transition('PREPARING')
        if binding_failure:raise FacilityFault(binding_failure)
        if not 0<float(timeout_s)<=120:raise FacilityFault('TIMEOUT_INVALID')
        if driver:
            if not driver.fs.is_real:raise FacilityFault('SIMULATED_DRIVER_CANNOT_LAUNCH_NATIVE')
            if driver.ident!=ident:raise FacilityFault('CGROUP_RUN_ID_MISMATCH')
            if not set(driver.limits.affinity)<=set(os.sched_getaffinity(0)):raise FacilityFault('AFFINITY_UNAVAILABLE')
            driver.prepare();entry_fd=driver.fs.child_entry_fd(ident)
        def enter_group():
            # Only async-safe OS actions occur between fork and exec; data/native loads follow exec.
            os.write(entry_fd,str(os.getpid()).encode());os.close(entry_fd);os.sched_setaffinity(0,driver.limits.affinity)
        request_file=(out/'request.json').open('rb');files.append(request_file)
        for name in ['worker.report.json','worker.stderr.log']:
            fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);files.append(os.fdopen(fd,'wb'))
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        proc=spawn([str(binary)],cwd=out,stdin=files[0],stdout=files[1],stderr=files[2],env=env,
                   start_new_session=True,close_fds=True,pass_fds=() if entry_fd is None else (entry_fd,),preexec_fn=enter_group if driver else None)
        result['execution_started']=True;transition('RUNNING');deadline=time.monotonic()+float(timeout_s);next_sample=time.monotonic()
        while proc.poll() is None:
            if cancel and cancel():reason='OWNER_CANCELLED';break
            if time.monotonic()>=deadline:reason='WALL_TIMEOUT';break
            if driver and time.monotonic()>=next_sample:driver.sample();next_sample+=0.1
            time.sleep(0.005)
        transition('STOPPING')
        if driver:driver.kill()
        group_state=stop_group(proc);transition('DRAINING')
        for f in files:f.close()
        files=[]
        if reason:
            result['terminal_status']='TIMEOUT' if reason=='WALL_TIMEOUT' else 'CANCELLED';result['failure']={'code':reason,'attribution':'deadline' if reason=='WALL_TIMEOUT' else 'owner'}
        else:
            if proc.returncode not in (0,2):raise FacilityFault('NATIVE_PROCESS_CRASH')
            report,events=audit_worker(out,expected)
            if (report['terminal_status']=='COMPLETED')!=(proc.returncode==0):raise FacilityFault('EXIT_STATUS_MISMATCH')
            result['terminal_status']=report['terminal_status'];result['failure']=report.get('failure');result['worker']=report
            result['actual_dispatch']=[{'node_id':e['node_id'],'operator':e['operator'],'implementation':e['implementation'],'sequence':e['sequence']} for e in events if e['kind']=='node_finished']
        if closure_hashes()!=expected['source_closure'] or sha(binary.read_bytes())!=expected['build_manifest']['binaries'][request['mode']]['sha256']:raise FacilityFault('SOURCE_OR_BINARY_CHANGED_DURING_RUN')
    except (FacilityFault,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        result['terminal_status']='INFRA_FAILURE';result['failure']={'code':str(exc) if isinstance(exc,FacilityFault) else type(exc).__name__,'attribution':'facility'}
    finally:
        for f in files:f.close()
        if entry_fd is not None:os.close(entry_fd)
        if proc:
            try:group_state=stop_group(proc)
            except (FacilityFault,OSError) as exc:result['terminal_status']='INFRA_FAILURE';result['failure']={'code':str(exc),'attribution':'facility'}
        transition('MEASURING')
        if driver:
            try:
                result['measurements']=driver.finish()
                if (result['measurements'].get('oom_kill_delta') or 0)>0 and result['execution_started']:
                    result['terminal_status']='INFRA_FAILURE';result['failure']={'code':'OOM_CAUSE_UNRESOLVED','attribution':'UNKNOWN','evidence':'Event co-occurrence does not exclude ancestor/global OOM'}
            except (FacilityFault,OSError,KeyError,ValueError) as exc:
                result['measurements']={**(getattr(exc,'report',None) or getattr(exc,'partial_report',None) or driver.last_report or unavailable()),'facility_status':'MEASUREMENT_OR_CLEANUP_FAILED','reason':str(exc)}
                result['terminal_status']='INFRA_FAILURE';result['failure']={'code':'CGROUP_CLEANUP_OR_MEASUREMENT_FAILED','attribution':'facility'}
    result['process_group_final']=group_state
    result['controller_wall_ns_before_verifier']=time.monotonic_ns()-start
    verify_start=time.monotonic_ns()
    if result['terminal_status']=='COMPLETED' and verify:
        try:result['verification']=verify(out)
        except Exception as exc:result['verification']={'status':'UNKNOWN','reason':'VERIFIER_'+type(exc).__name__}
    result['verifier_wall_ns']=time.monotonic_ns()-verify_start
    result['completed_wall_ns']=report['worker_exec_wall_ns'] if report and result['terminal_status']=='COMPLETED' else None
    result['lifecycle']=states
    write(out/'report.json',result)
    try:
        transition('SEALED');result['seal_sha256']=archive(out);reread(out,result['seal_sha256'])
    except Exception as exc:
        result['archive_status']='FAILED';result['archive_failure']=type(exc).__name__;result['terminal_status']='INFRA_FAILURE'
        write(out/'ARCHIVE_FAILURE.json',result)
    else:result['archive_status']='PASS'
    return result
