"""Worker entry: only trusted prepared files, no gold, installers or live defaults."""
import argparse
import asyncio
import json
import time
import traceback
from pathlib import Path
from rcwg_full.evidence import read,write,source_hashes,sha
from rcwg_full.compiler import FullCompiler
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.events import Journal
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.backend import Backend
from rcwg_full.runtime.scheduler import Scheduler,ExecutionFault


async def execute(request,build,output):
    out=Path(output);sources=source_hashes();started=time.monotonic_ns()
    journal=Journal(out/'events.jsonl',request['run_id']);journal.append('run_started',{'mode':request['mode']},status='RUNNING')
    result={'run_id':request['run_id'],'terminal_status':'INFRA_FAILURE','failure':None,'formal_ready':False,'source':sources,'paid_calls':0,'measurement_profile':'ENGINEERING_UNCALIBRATED'}
    store=None;scheduler=None
    try:
        if request['mode'] not in {'ENGINEERING_NATIVE','ENGINEERING_REPLAY'}:raise ExecutionFault('RUNNER_MODE_NOT_ADMITTED','facility')
        if sha(read(request['data_manifest']))!=request['data_manifest_sha256']:raise ExecutionFault('DATA_MANIFEST_CHANGED','facility')
        native=Native(build,request.get('native_mode','performance'));catalog=DataCatalog(request['data_manifest']).bind(request['task'])
        report=FullCompiler().compile(request['task'],request['plan']);write(out/'compiler.json',report)
        if report['status']!='IR_VALIDATED':raise ExecutionFault(report['status'],'plan' if report['status']=='PLAN_INVALID' else 'facility')
        from rcwg_full.runtime.document_registry import DocumentRegistry
        from rcwg_full.runtime.documents import ReplaySemantic
        semantic=None
        if request.get('semantic_replay'):
            if request['mode']!='ENGINEERING_REPLAY':raise ExecutionFault('REPLAY_MODE_FORBIDDEN','facility')
            replay=request['semantic_replay'];raw=read(replay['path'])
            if sha(raw)!=replay['sha256']:raise ExecutionFault('REPLAY_MANIFEST_CHANGED','facility')
            payload=json.loads(raw)
            if payload.get('revision')!='full001-engineering-replay-1':raise ExecutionFault('REPLAY_MANIFEST_VERSION','facility')
            semantic=ReplaySemantic(payload['responses'],mode=request['mode'],service_id=payload['service_id'])
        documents=DocumentRegistry(catalog,native=native,event=lambda k,v:journal.append(k,v))
        store=ArtifactStore(out/'artifacts',request['run_id'],journal);backend=Backend(native,store,request['task'],documents=documents,semantic=semantic);externals={}
        for alias,meta in report['typed_graph']['input_bindings'].items():
            source=catalog.resolve(meta['source_id']);value=source if meta['type']['kind']=='DatasetRef' else source.value()
            externals[alias]=store.register(value,meta['type'],'external:'+alias,source_refs=[meta['source_id']])
        scheduler=Scheduler(report,request['task'],externals,backend,journal)
        value=await scheduler.run();write(out/'result.json',value)
        if source_hashes()!=sources:raise ExecutionFault('SOURCE_CHANGED_DURING_RUN','facility')
        result['terminal_status']='COMPLETED'
    except BaseException as exc:
        result['terminal_status']='MODEL_FAILURE' if isinstance(exc,ExecutionFault) and exc.attribution=='plan' else 'INFRA_FAILURE'
        result['failure']={'code':getattr(exc,'code',type(exc).__name__),'attribution':getattr(exc,'attribution','facility'),'detail':str(exc)}
        write(out/'failure.traceback.txt',traceback.format_exc().encode('utf-8'))
    finally:
        result['worker_exec_wall_ns']=time.monotonic_ns()-started
        result['buffer_metrics']=store.lifetime_metrics() if store else None
        result['logical_instances']=scheduler.admission.instances if scheduler else 0
        journal.append('run_finished',{'terminal_status':result['terminal_status'],'failure':result['failure']},status=result['terminal_status'])
        journal.seal(out/'journal-seal.json');write(out/'worker-report.json',result)
    return 0 if result['terminal_status']=='COMPLETED' else 1


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--build',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();request=json.loads(read(a.request));return asyncio.run(execute(request,a.build,a.output))

if __name__=='__main__':raise SystemExit(main())
