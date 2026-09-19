"""Parent-owned deadline, process-group cleanup and independent verification."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from rcwg_spec.binding import seal_events,make_sidecar,validate_evidence,TERMINAL,EVENT_TYPES
from rcwg_spec.common import canonical,digest,ContractError
from rcwg_spec.compiler import validate_workflow
from . import PROFILE
from .context import ROOT,prepare_manifest,source_closure,SUPERVISOR_REVISION
from .errors import ExecFault
from .journal import Journal,read_json,read_journal,validate_node_events
from .runner import preflight
from .sealing import bytes_at,validate_artifact,validate_measurements,seal_directory,reopen_run
from .store import PrivateStore
from .verifier import verify_f1
from .worker import FAULTS


def _signal_group(pid,signum):
    try:os.killpg(pid,signum);return True
    except ProcessLookupError:return False


def _cleanup(process,terminate):
    actions=[]
    if terminate:
        if _signal_group(process.pid,signal.SIGTERM):actions.append('SIGTERM_PROCESS_GROUP')
        try:process.wait(timeout=.3)
        except subprocess.TimeoutExpired:
            if _signal_group(process.pid,signal.SIGKILL):actions.append('SIGKILL_PROCESS_GROUP')
            process.wait(timeout=2)
    else:process.wait()
    # Even a crashed/exited leader can leave children in its private group.
    if _signal_group(process.pid,signal.SIGKILL):actions.append('SIGKILL_REMAINING_GROUP')
    return actions


def _event(record):
    return {'event':record['event'],'status':record['status'],'monotonic_ns':record['monotonic_ns'],
            'payload':{**record['payload'],'event_origin':record['origin'],'observer_pid':record['pid']}}


def run_f1_supervised(task,plan,*,registry,recipe,output,condition_id='DEV-C0',record_id='dev-run-0',
                      generation_id='handcrafted-0',repeat_id='r0',max_materialized_rows=100000,
                      cancel_event=None,_fault='none'):
    """Execute only the fixed F1 profile, with a separate process for each run.

    _fault is a trusted engineering test control, bound into runtime identity;
    it is never read from WorkIR or a provider response. It cannot run commands.
    """
    task=deepcopy(task);plan=deepcopy(plan);recipe=deepcopy(recipe)
    compiled=validate_workflow(task,plan);ready=preflight(task,plan,compiled)
    if ready['status']!='REFERENCE_PROFILE_READY':return {**ready,'execution_started':False,'formal_ready':False}
    if sys.platform!='linux':return {'status':'RUNTIME_IMPLEMENTATION_GAP','gaps':[{'code':'LINUX_SUPERVISOR_REQUIRED'}],
                                   'execution_started':False,'formal_ready':False}
    if type(max_materialized_rows) is not int or not 0<max_materialized_rows<=1000000:raise ExecFault('ENGINEERING_CAP_INVALID')
    if type(_fault) is not str or _fault not in FAULTS:raise ExecFault('FAULT_POLICY_INVALID')
    manifest=prepare_manifest(task,plan,registry,recipe,condition_id=condition_id,record_id=record_id,
        generation_id=generation_id,repeat_id=repeat_id,max_materialized_rows=max_materialized_rows,fault=_fault)
    expected=manifest.as_dict()['expected_records'][0];key=expected['execution_key']
    closure=source_closure();store=PrivateStore(Path(output))
    store.write_json('expected_manifest.json',manifest.as_dict());store.write_json('task.json',task)
    store.write_json('plan.json',plan);store.write_json('compiler_report.json',compiled)
    # The private recipe is never included in the worker request.
    store.write_json('verification_recipe.json',recipe)
    request={'task':task,'plan':plan,'expected_manifest':manifest.as_dict(),
             'locations':{k:str(v.path) for k,v in registry.entries.items()},'allowed_root':str(registry.allowed_root),
             'max_materialized_rows':max_materialized_rows,'fault':_fault}
    request_sha=store.write_json('worker_request.json',request)
    journal=Journal(store.root/'supervisor.journal.jsonl',execution_key=key,manifest_hash=manifest.manifest_hash,origin='supervisor')
    start=journal.append('run_started','RUNNING',{'scope':'parent_supervision','manifest_hash':manifest.manifest_hash,
                                               'request_sha256':request_sha,'worker_started':False})
    deadline=start['monotonic_ns']+int(task['resources']['wall_timeout_s']*1e9)
    cpu0=time.process_time_ns();process=None;worker=None;worker_events=[];journal_error=None
    terminal='INFRA_FAILURE';failure=None;cleanup=[];artifact=None;partial=False
    out_fd=os.open(store.root/'worker.stdout.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    err_fd=os.open(store.root/'worker.stderr.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        process=subprocess.Popen([sys.executable,'-I','-B',str(ROOT/'rcwg_exec/worker.py'),
            '--request',str(store.root/'worker_request.json'),'--sha256',request_sha],
            cwd=ROOT,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONHASHSEED':'0'},
            stdin=subprocess.DEVNULL,stdout=out_fd,stderr=err_fd,start_new_session=True,close_fds=True)
        journal.append('worker_spawned','RUNNING',{'worker_pid':process.pid,'process_group':process.pid})
        stop=None
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():stop='OWNER_CANCELLED';break
            if time.perf_counter_ns()>=deadline:stop='WALL_TIMEOUT';break
            time.sleep(.005)
        cleanup=_cleanup(process,stop is not None)
        if stop=='OWNER_CANCELLED':terminal='UNKNOWN';failure={'code':stop,'attribution':'owner'}
        elif stop=='WALL_TIMEOUT':terminal='TIMEOUT';failure={'code':stop,'attribution':'budget'}
        elif process.returncode!=0:failure={'code':'WORKER_EXIT_NONZERO','attribution':'facility','exit_code':process.returncode}
        else:
            worker=read_json(store.root/'worker/worker_report.json')
            if (worker['execution_key']!=key or worker['manifest_hash']!=manifest.manifest_hash
                    or worker['request_sha256']!=request_sha or worker['source_closure_hash']!=digest(closure)
                    or worker['worker_pid']!=process.pid or worker['terminal_status'] not in TERMINAL):
                raise ExecFault('WORKER_REPORT_BINDING')
            terminal=worker['terminal_status'];failure=worker['failure']
    except (ExecFault,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        terminal='INFRA_FAILURE';failure={'code':getattr(exc,'code','SUPERVISOR_ERROR'),'attribution':'facility',
                                         'exception_type':type(exc).__name__}
    except KeyboardInterrupt:
        terminal='UNKNOWN';failure={'code':'OWNER_CANCELLED','attribution':'owner'}
    finally:
        if process is not None and process.poll() is None:cleanup.extend(_cleanup(process,True))
        os.close(out_fd);os.close(err_fd)
    if process is not None:
        journal.append('worker_exited',terminal,{'worker_pid':process.pid,'exit_code':process.returncode,'cleanup':cleanup})
    journal_path=store.root/'worker.journal.jsonl'
    if journal_path.exists():
        try:
            read=read_journal(journal_path,execution_key=key,manifest_hash=manifest.manifest_hash,
                origin='worker',pid=process.pid if process else None,allow_partial=terminal!='COMPLETED')
            worker_events=read['events'];partial=read['partial_tail']
            validate_node_events(worker_events,plan,completed=terminal=='COMPLETED')
            if terminal=='COMPLETED' and (not worker_events or worker_events[0]['event']!='worker_started'
                    or worker_events[-1]['event']!='worker_finished' or worker_events[-1]['status']!=terminal):
                raise ExecFault('WORKER_JOURNAL_TERMINAL')
        except (ExecFault,ValueError,KeyError,TypeError) as exc:
            journal_error=getattr(exc,'code','JOURNAL_INVALID');worker_events=[]
            terminal='INFRA_FAILURE';failure={'code':journal_error,'attribution':'facility'}
    elif terminal=='COMPLETED':terminal='INFRA_FAILURE';failure={'code':'WORKER_JOURNAL_MISSING','attribution':'facility'}
    if source_closure()!=closure:
        terminal='INFRA_FAILURE';failure={'code':'SOURCE_CHANGED_DURING_EXECUTION','attribution':'facility'}
    if terminal=='COMPLETED':
        try:
            artifact=validate_artifact(store.root/'worker',expected=expected,task=task,plan=plan,compiled=compiled,
                creation_window=(start['monotonic_ns'],time.perf_counter_ns()))
            if worker['artifact']!=artifact:raise ExecFault('WORKER_ARTIFACT_MISMATCH')
        except (ExecFault,OSError,ValueError,KeyError,TypeError) as exc:
            terminal='INFRA_FAILURE';failure={'code':getattr(exc,'code','ARTIFACT_INVALID'),'attribution':'facility'}
    # A result delivered after the parent's hard deadline is censored, even if
    # the child finished before the next poll. Verification remains separate.
    now=time.perf_counter_ns()
    if terminal=='COMPLETED' and now>deadline:
        terminal='TIMEOUT';failure={'code':'WALL_TIMEOUT','attribution':'budget'}
    elapsed=now-start['monotonic_ns'];supervisor_cpu=time.process_time_ns()-cpu0
    finish=journal.append('run_finished',terminal,{'failure':failure,'elapsed_ns':elapsed,
        'completed_wall_ns':elapsed if terminal=='COMPLETED' else None,'worker_pid':process.pid if process else None})
    journal.close()
    observations=[_event(start)]
    observations.extend(_event(e) for e in worker_events if e['event'] in EVENT_TYPES-{'run_started','run_finished'})
    observations.append(_event(finish))
    verifier0=time.perf_counter_ns();vcpu0=time.process_time_ns()
    if terminal=='COMPLETED':
        entry=registry.entries.get(recipe.get('source_id'))
        verification=verify_f1(task=task,recipe=recipe,data_path=entry.path if entry else Path('/nonexistent'),
            artifact_path=store.root/'worker/result.json',artifact_meta=artifact,max_rows=max_materialized_rows)
    else:verification={'status':'UNKNOWN','reason':'RUN_INCOMPLETE'}
    verifier_ns=time.perf_counter_ns()-verifier0;verifier_cpu=time.process_time_ns()-vcpu0
    ledger=seal_events(manifest,record_id,observations)
    sidecar=make_sidecar(manifest,record_id,ledger,terminal_status=terminal,verification_status=verification['status'])
    bound=validate_evidence(manifest,[sidecar],{record_id:ledger})
    measurements={'profile':PROFILE,'scope':'ENGINEERING_DIAGNOSTIC_ONLY','elapsed_ns':elapsed,
        'completed_wall_ns':elapsed if terminal=='COMPLETED' else None,'wall_scope':'parent_launch_cleanup_and_integrity_checks_excludes_verifier',
        'process_cpu_ns':worker['process_cpu_ns'] if worker else None,
        'worker_execution_wall_ns':worker['elapsed_ns'] if worker else None,
        'worker_measurement_reason':'OBSERVED_WORKER_PROCESS' if worker else 'NO_FINAL_WORKER_OBSERVATION',
        'process_lifetime_rss_hwm_bytes':worker['process_lifetime_rss_hwm_bytes'] if worker else None,
        'supervisor_process_cpu_ns':supervisor_cpu,'verifier_wall_ns_separate':verifier_ns,'verifier_cpu_ns_separate':verifier_cpu,
        'worker_peak_ram_bytes':None,'worker_peak_ram_reason':'NO_ISOLATED_CGROUP','physical_copy_bytes':None,
        'physical_copy_reason':'NOT_INSTRUMENTED','block_io_bytes':None,'block_io_reason':'NOT_MEASURED',
        'budget_within':None,'budget_reason':'REQUIRED_MEMORY_NOT_VERIFIED',
        'node_counters':worker['node_counters'] if worker else {},'measurement_validity':'NOT_CALIBRATED','formal_ready':False}
    validate_measurements(measurements,terminal)
    report={'status':'EXEC001_SUPERVISED_COMPLETE' if terminal=='COMPLETED' else 'EXEC001_SUPERVISED_TERMINATED',
        'profile':PROFILE,'supervisor_revision':SUPERVISOR_REVISION,'terminal_status':terminal,'failure':failure,
        'verification':verification,'artifact':artifact,'execution_key':key,'expected_manifest_hash':manifest.manifest_hash,
        'evidence_binding':bound,'measurements':measurements,'static_status':compiled['status'],
        'node_states':worker['node_states'] if worker else {},'execution_started':process is not None,
        'worker_pid':process.pid if process else None,'parent_pid':os.getpid(),
        'worker_exit_code':process.returncode if process else None,'process_group_cleanup':cleanup,
        'worker_partial_journal':partial,'journal_error':journal_error,'fault_injection':_fault,
        'formal_ready':False,'real_model_requests':0,'cloud_mutations':0,'kernel_backend':'PYTHON_REFERENCE',
        'native_formal_comparability':'NOT_VALIDATED'}
    for name,value in [('events',ledger),('sidecar',sidecar),('verification',verification),('measurements',measurements),('report',report)]:
        store.write_json(name+'.json',value)
    seal_hash=seal_directory(store,manifest,expected)
    reread=reopen_run(store.root,manifest=manifest,seal_sha256=seal_hash)
    return {**report,'seal_sha256':seal_hash,'reread':reread}
