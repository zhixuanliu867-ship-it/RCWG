"""Externally bounded FULL001 worker, reusing native process-tree and N4 driver APIs."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import uuid
from rcwg_full.evidence import ROOT,exclusive_directory,read,write,sha,canonical,source_hashes
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.events import verify_journal
from rcwg_native.supervisor import stop_group,live_group
from rcwg_native.metrology import unavailable
from rcwg_full.compiler.public_task import validate_public_task
from rcwg_full.runtime.binding import build_context
from rcwg_spec.binding import freeze_expected,seal_events,make_sidecar,validate_evidence,EVENT_TYPES


def context_for(task,catalog,build,*,condition_id='C0',mode='ENGINEERING_NATIVE',verifier_identity='full001-independent-v1',replay_sha256=None,execution_profile=None,service_binding=None):
    checked=validate_public_task(task);manifest=json.loads(read(Path(build)/'BUILD.json'));source=source_hashes()
    from rcwg_full.runtime.scheduling_profile import validate_profile
    profile=validate_profile(task,execution_profile)
    return build_context(task,condition_id=condition_id,data_manifest=catalog.bindings(),
        runtime={'revision':'full001-runtime-1','mode':mode,'semantic_replay_sha256':replay_sha256 or 'NOT_CONFIGURED','data_manifest_sha256':sha(canonical(catalog.manifest)),'native_binaries':{k:v['sha256'] for k,v in manifest['binaries'].items()},'python':manifest['python'],'batch_rows':1024,'batch_target_bytes':4*1024*1024,'queue_batches':2,'queue_bytes':8*1024*1024,**({'scheduling_profile':profile} if profile else {}),**({'semantic_service':service_binding,'semantic_concurrency':4} if service_binding else {})},
        cache_policy={'revision':'full001-cache-1','cross_run':False},verifier={'revision':verifier_identity},
        metric_spec={'revision':'full001-metric-1'},measurement_profile={'revision':'full001-engineering-uncalibrated-1','event_source_id':'full001-worker','clock_id':'monotonic_ns','host_calibrated':False},
        operator_registry={'revision':'full001-operators-1','sha256':sha(read(ROOT/'specs/full001/operators.json'))},
        source_manifest={'revision':'full001-source-1','files':source,'public_sources':checked['source_manifest']})


def execute(task,plan,data_manifest,*,build,output,mode='ENGINEERING_NATIVE',condition_id='C0',verify=None,cancel=None,driver=None,timeout_s=None,semantic_replay=None,execution_profile=None,semantic_service=None,admission=None,frozen_binding=None):
    if mode not in {'ENGINEERING_NATIVE','ENGINEERING_REPLAY','FORMAL'}:raise ValueError('MODE_REQUIRES_SEPARATE_ADMISSION')
    if mode=='FORMAL' and (not admission or admission.get('status')!='ADMITTED' or driver is None or not getattr(driver,'full001_authorization',None)):raise PermissionError('FORMAL_ADMISSION_REQUIRED')
    if semantic_service is not None and ((mode=='FORMAL')!=(semantic_service.mode=='LIVE')):raise ValueError('SERVICE_MODE_BINDING')
    if semantic_service is not None and semantic_replay is not None:raise ValueError('MULTIPLE_SEMANTIC_SERVICES')
    if semantic_replay is not None and mode!='ENGINEERING_REPLAY':raise ValueError('REPLAY_MODE_FORBIDDEN')
    replay=None if semantic_replay is None else {'path':str(Path(semantic_replay).absolute()),'sha256':sha(read(semantic_replay))}
    out=exclusive_directory(output);ident=driver.ident if driver else 'r'+uuid.uuid4().hex;states=[];cleanup=[]
    def transition(state,**detail):
        record={'sequence':len(states),'state':state,'monotonic_ns':time.monotonic_ns(),**detail};states.append(record);write(out/('lifecycle-%03d.json'%len(states)),record)
    transition('DECLARED');catalog=DataCatalog(data_manifest)
    context=context_for(task,catalog,build,condition_id=condition_id,mode=mode,replay_sha256=replay['sha256'] if replay else None,execution_profile=execution_profile,service_binding=semantic_service.client.binding if semantic_service else None)
    compiler_source=b''.join(read(p) for p in sorted((ROOT/'rcwg_full/compiler').glob('*.py')))
    expected=freeze_expected(context,[{'record_id':ident,'record_role':'MODEL','plan':plan,'compiler_source':compiler_source,'generation_id':ident,'repeat_id':'r1','repeat_role':'PRIMARY_REPEAT'}])
    write(out/'expected.json',expected.as_dict())
    request={'run_id':ident,'mode':mode,'task':task,'plan':plan,'data_manifest':str(Path(data_manifest).absolute()),'data_manifest_sha256':sha(read(data_manifest)),'native_mode':'performance','go_record':str((out/'go.json').absolute())}
    if replay is not None:request['semantic_replay']=replay
    if execution_profile is not None:request['execution_profile']=execution_profile
    if frozen_binding is not None:request['frozen_binding']=frozen_binding
    worker=out/'worker';worker.mkdir()
    report={'run_id':ident,'mode':mode,'expected_manifest_sha256':expected.manifest_hash,'terminal_status':'UNKNOWN','execution_started':False,
        'failure':None,'verification':{'status':'UNKNOWN','reason':'NOT_EXECUTED'},'measurements':unavailable(),'formal_ready':False,'paid_calls':None if semantic_service and semantic_service.mode=='LIVE' else 0}
    timeout_s=task['resources']['wall_timeout_s'] if timeout_s is None else timeout_s
    if not 0<float(timeout_s)<=3600:raise ValueError('WALL_TIMEOUT_RANGE')
    proc=None;handshake=None;reason=None;handles=[];worker_report=None;broker=None
    if driver:
        sequence=[0]
        def persist(stage,value):
            sequence[0]+=1;write(out/('counter-%05d.json'%sequence[0]),{'stage':stage,'evidence':value})
        driver.persist=persist
    try:
        transition('PREPARING')
        if driver:
            if not driver.fs.is_real or driver.ident!=ident:raise ValueError('CGROUP_DRIVER_IDENTITY')
            if not getattr(driver,'full001_authorization',None):raise PermissionError('FULL001_LAUNCH_RECEIPT_REQUIRED')
            driver.prepare()
            pids=driver.full001_authorization['pids_max'];driver.fs.write(ident,'pids.max',str(pids))
            if driver.fs.read(ident,'pids.max').strip()!=str(pids):raise ValueError('PIDS_READBACK_MISMATCH')
        if semantic_service is not None:
            from rcwg_full.services.broker import SemanticBroker
            broker=SemanticBroker(semantic_service);request['semantic_connection']=broker.connection()
        write(out/'request.json',request)
        for name in ['stdout.log','stderr.log']:handles.append((out/name).open('xb'))
        env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP'}}
        env.update(LANG='C.UTF-8',LC_ALL='C.UTF-8',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',ARROW_NUM_THREADS='1',PYTHONUTF8='1')
        command=[sys.executable,'-m','rcwg_full.runtime.worker','--request',str((out/'request.json').absolute()),'--build',str(Path(build).absolute()),'--output',str(worker.absolute())]
        from rcwg_full.runtime.launch import Handshake
        handshake=Handshake(driver,build,command)
        proc=subprocess.Popen(handshake.command,cwd=ROOT,stdout=handles[0],stderr=handles[1],env=env,start_new_session=True,close_fds=True,pass_fds=handshake.pass_fds)
        handshake.spawned();transition('SPAWNED',pid=proc.pid);deadline=time.monotonic()+float(timeout_s);next_sample=time.monotonic()
        while proc.poll() is None:
            ack=handshake.ready(proc,out/'go.json',ident)
            if ack is not None:
                report['execution_started']=True;report['launch_ack']=ack
                transition('RUNNING',pid=proc.pid,exec_started_monotonic_ns=handshake.go_ns)
                deadline=time.monotonic()+float(timeout_s)
            if cancel and cancel():reason='OWNER_CANCELLED';break
            if time.monotonic()>=deadline:reason='WALL_TIMEOUT';break
            if driver and time.monotonic()>=next_sample:driver.sample();next_sample+=.1
            time.sleep(.005)
        if handshake.go_ns is None:raise ValueError('LAUNCH_GO_MISSING')
        report['observed_elapsed_ns']=time.monotonic_ns()-handshake.go_ns
        transition('STOPPING',cause=reason)
        if driver:driver.kill()
        report['process_group_final']=stop_group(proc);transition('DRAINING')
        for handle in handles:handle.close()
        handles=[]
        if reason:
            report['terminal_status']='TIMEOUT' if reason=='WALL_TIMEOUT' else 'UNKNOWN';report['failure']={'code':reason,'attribution':'deadline' if reason=='WALL_TIMEOUT' else 'owner'}
        else:
            worker_report=json.loads(read(worker/'worker-report.json'))
            if worker_report['run_id']!=ident or worker_report['source']!=source_hashes():raise ValueError('WORKER_IDENTITY_OR_SOURCE')
            events=verify_journal(worker/'events.jsonl',run_id=ident)
            if events[0]['event_kind']!='run_started' or events[-1]['event_kind']!='run_finished':raise ValueError('RUN_BOUNDARIES')
            if (proc.returncode==0)!=(worker_report['terminal_status']=='COMPLETED') or events[-1]['status']!=worker_report['terminal_status']:raise ValueError('WORKER_EXIT_STATUS')
            report.update(terminal_status=worker_report['terminal_status'],failure=worker_report['failure'],worker=worker_report)
            report['exec_elapsed_ns']=worker_report.get('exec_elapsed_ns')
    except BaseException as exc:
        report.update(terminal_status='INFRA_FAILURE',failure={'code':type(exc).__name__,'detail':str(exc),'attribution':'facility'})
    finally:
        for handle in handles:handle.close()
        if handshake is not None:handshake.close()
        if proc:
            try:report['process_group_final']=stop_group(proc)
            except Exception as exc:cleanup.append({'stage':'PROCESS_TREE','cause':str(exc)})
        transition('MEASURING')
        if driver:
            try:report['measurements']=driver.finish()
            except Exception as exc:
                report['measurements']=getattr(exc,'report',None) or getattr(exc,'partial_report',None) or driver.last_report or unavailable()
                cleanup.append({'stage':'COUNTERS_OR_CLEANUP','cause':str(exc)})
        report['cleanup_failures']=cleanup
        if broker:
            broker.close();report['semantic_requests']=broker.snapshot()
            if report['semantic_requests']['inflight']:report['service_reconciliation_required']=True
    # Independent verifier is controller-side, after worker exit, and never sent to worker.
    if report['terminal_status']=='COMPLETED' and verify is not None:
        begin=time.monotonic_ns()
        try:report['verification']=verify(json.loads(read(worker/'result.json')),out)
        except Exception as exc:report['verification']={'status':'UNKNOWN','reason':'VERIFIER_'+type(exc).__name__}
        report['verifier_wall_ns']=time.monotonic_ns()-begin
    if worker_report is not None:
        observed=verify_journal(worker/'events.jsonl',run_id=ident)
        projection=[{'event':e['event_kind'],'monotonic_ns':e['monotonic_ns'],'status':e['status'],'payload':{**e['payload'],'full_event_hash':e['event_hash']}} for e in observed if e['event_kind'] in EVENT_TYPES]
        if projection[-1]['status']==report['terminal_status']:
            events=seal_events(expected,ident,projection);sidecar=make_sidecar(expected,ident,events,terminal_status=report['terminal_status'],verification_status=report['verification']['status'])
            report['binding_validation']=validate_evidence(expected,[sidecar],{ident:events});write(out/'bound-events.json',events);write(out/'sidecar.json',sidecar)
    report['lifecycle']=states;write(out/'report.json',report)
    inventory={p.relative_to(out).as_posix():sha(read(p)) for p in out.rglob('*') if p.is_file()}
    write(out/'seal.json',{'run_id':ident,'files':inventory,'status':'SEALED','formal_ready':False});return report
