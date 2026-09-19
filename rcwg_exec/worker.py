"""Fixed worker entry point: no model code, command, URI or verifier recipe."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import resource
import signal
import sys
import time

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_spec.common import canonical,digest
from rcwg_spec.binding import ExpectedManifest
from rcwg_spec.compiler import validate_workflow
from rcwg_exec.context import source_closure,compiler_source
from rcwg_exec.datasets import FileRegistry,open_regular
from rcwg_exec.engine import execute_chain
from rcwg_exec.errors import ExecFault
from rcwg_exec.journal import Journal,read_json
from rcwg_exec.runner import preflight
from rcwg_exec.store import PrivateStore

FAULTS={'none','stall','crash','nonzero','partial_artifact','spawn_descendant','drop_report',
        'partial_journal','corrupt_journal','artifact_binding','artifact_metadata'}


def run(request_path,expected_hash):
    request_path=Path(request_path)
    with os.fdopen(open_regular(request_path),'rb') as f:raw=f.read()
    if hashlib.sha256(raw).hexdigest()!=expected_hash:raise ExecFault('WORKER_REQUEST_HASH')
    request=read_json(request_path)
    manifest=ExpectedManifest(canonical(request['expected_manifest']))
    payload=manifest.as_dict();expected=payload['expected_records'][0]
    task=request['task'];plan=request['plan'];fault=request['fault']
    if (digest(task)!=expected['input_hash'] or digest(plan)!=expected['plan_hash']
            or hashlib.sha256(compiler_source()).hexdigest()!=expected['compiler_hash']):
        raise ExecFault('WORKER_INPUT_IDENTITY')
    runtime=payload['context']['authoritative_metadata']['runtime']
    if source_closure()!=runtime['source_closure'] or digest(source_closure())!=runtime['source_closure_hash']:
        raise ExecFault('WORKER_SOURCE_CHANGED')
    if fault not in FAULTS or runtime['fault_injection']!=fault:raise ExecFault('WORKER_FAULT_POLICY')
    journal=Journal(request_path.parent/'worker.journal.jsonl',execution_key=expected['execution_key'],
                    manifest_hash=manifest.manifest_hash,origin='worker')
    store=None
    try:
        journal.append('worker_started','RUNNING',{'pid':os.getpid(),'ppid':os.getppid(),'request_sha256':expected_hash,
                                                 'recipe_present':False,'environment_keys':sorted(os.environ)})
        if fault=='stall':time.sleep(30)
        if fault=='crash':os._exit(71)
        if fault=='nonzero':raise ExecFault('CONTROLLED_WORKER_EXCEPTION')
        if fault in {'partial_journal','corrupt_journal'}:
            journal.stream.write(b'{"interrupted":' if fault=='partial_journal' else b'{}\n')
            os.fsync(journal.stream.fileno());os._exit(73)
        if fault=='spawn_descendant':
            child=os.fork()
            if child==0:
                time.sleep(30);os._exit(0)
            journal.append('child_spawned','RUNNING',{'child_pid':child,'process_group':os.getpgrp()})
            def stop(signum,frame):
                try:os.waitpid(child,0)
                except ChildProcessError:pass
                os._exit(128+signum)
            signal.signal(signal.SIGTERM,stop)
            time.sleep(30)
        store=PrivateStore(request_path.parent/'worker')
        if fault=='partial_artifact':
            fd=os.open(store.root/'.result.json.incomplete.part',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            os.write(fd,b'[{');os.fsync(fd);os.close(fd);os._exit(72)
        registry=FileRegistry(task,{k:Path(v) for k,v in request['locations'].items()},allowed_root=Path(request['allowed_root']))
        if registry.manifest()!=payload['context']['authoritative_metadata']['data_manifest']:
            raise ExecFault('WORKER_DATA_MANIFEST')
        compiled=validate_workflow(task,plan)
        if preflight(task,plan,compiled)['status']!='REFERENCE_PROFILE_READY':raise ExecFault('WORKER_PREFLIGHT_CHANGED')
        def emit(event,status,body):
            # The parent owns whole-run boundaries; worker records its own real
            # boundaries separately, without claiming the process already exited.
            event={'run_started':'kernel_started','run_finished':'kernel_finished'}.get(event,event)
            journal.append(event,status,body)
        result=execute_chain(task,plan,registry=registry,compiled=compiled,store=store,
            execution_key=expected['execution_key'],manifest_hash=manifest.manifest_hash,
            max_materialized_rows=request['max_materialized_rows'],emit=emit)
        result.update(worker_pid=os.getpid(),execution_key=expected['execution_key'],manifest_hash=manifest.manifest_hash,
                      request_sha256=expected_hash,source_closure_hash=digest(source_closure()),
                      process_lifetime_rss_hwm_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        if fault in {'artifact_binding','artifact_metadata'} and result['artifact']:
            filename='artifact_binding.json' if fault=='artifact_binding' else 'artifact.json'
            value=read_json(store.root/filename)
            if fault=='artifact_binding':value['execution_key']='0'*64
            else:value['serialized_bytes']+=1
            with (store.root/filename).open('wb') as stream:
                stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
        if fault!='drop_report':store.write_json('worker_report.json',result)
        journal.append('worker_finished',result['terminal_status'],{'worker_report_written':fault!='drop_report'})
        return 0
    except (ExecFault,OSError,ValueError,KeyError,TypeError,MemoryError,RecursionError) as exc:
        journal.append('worker_exception','INFRA_FAILURE',{'code':getattr(exc,'code','WORKER_INTERNAL_ERROR'),
                                                         'exception_type':type(exc).__name__})
        return 70
    finally:journal.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--sha256',required=True)
    a=p.parse_args()
    try:return run(a.request,a.sha256)
    except (ExecFault,OSError,ValueError,KeyError,TypeError,RecursionError) as exc:
        print('WORKER_ENTRY_ERROR:'+getattr(exc,'code',type(exc).__name__),file=sys.stderr)
        return 70


if __name__=='__main__':raise SystemExit(main())
