"""F1 serial-pull reference runtime and real SPEC001B evidence binding.

This is a bounded offline correctness backend, not the formal native executor.
Only a single root data chain is admitted. Unsupported scheduling/storage/graph
features produce a facility gap before execution; they are not model failures.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import hashlib
import platform
from pathlib import Path
import resource
import time

from rcwg_spec.common import canonical,digest,ContractError
from rcwg_spec.compiler import validate_workflow
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.binding import build_context,freeze_expected,seal_events,make_sidecar,validate_evidence
from . import PROFILE
from .errors import ExecFault
from .datasets import FileRegistry
from .kernels import RowFrame,ProjectedRow,evaluate,filter_rows,filter_batch_rows,project_rows,select_topk
from .store import PrivateStore
from .verifier import verify_f1

ROOT=Path(__file__).resolve().parents[1]
SUPPORTED={'scan':{'sequential'},'filter':{'scalar','vectorized'},
           'project':{'column_view','copy'},'top_k':{'full_sort','streaming_heap'},'emit':{'json_artifact'}}

class ClockControl:
    def __init__(self, seconds):self.start=time.perf_counter_ns();self.deadline=self.start+int(seconds*1e9)
    def tick(self):
        if time.perf_counter_ns()>self.deadline:raise ExecFault('WALL_TIMEOUT','budget')


def preflight(task,plan,compiled=None):
    compiled=compiled if compiled is not None else validate_workflow(task,plan)
    if compiled['status']!='IR_VALIDATED':return {'status':compiled['status'],'diagnostics':compiled['diagnostics']}
    gaps=[]
    def gap(code,node=None):gaps.append({'code':code,'node_id':node})
    if task['output_contract'].get('type')!='ordered_records':gap('OUTPUT_PROFILE_GAP')
    nodes={n['id']:n for n in plan['nodes']}
    for n in plan['nodes']:
        op=n['operator'];impl=n['implementation']
        if op not in SUPPORTED or impl not in SUPPORTED[op]:gap('KERNEL_GAP',n['id'])
        if n.get('regions'):gap('CONTROL_REGION_GAP',n['id'])
        if n.get('after'):gap('EXPLICIT_AFTER_GAP',n['id'])
        if n.get('storage')=='disk':gap('DISK_BACKEND_GAP',n['id'])
        if any(n.get('resources',{}).get(k,1)!=1 for k in ('cpu_slots','max_parallelism')):
            gap('NODE_PARALLELISM_GAP',n['id'])
    # The starter executes one complete data chain. It never prunes dead nodes,
    # consumes a stream twice or silently inserts broadcast/materialization.
    chain=[];ref=plan['result'];visited=set()
    while '.' in ref and not ref.startswith('$'):
        name,_=ref.split('.')
        if name in visited:gap('CHAIN_GAP');break
        visited.add(name);chain.append(name);n=nodes[name]
        if len(n['inputs'])!=1:gap('MULTI_INPUT_GAP',name);break
        ref=next(iter(n['inputs'].values()))
    if set(chain)!=set(nodes):gap('UNUSED_OR_FANOUT_NODES_GAP')
    if not ref.startswith('$input.') or sum(n['operator']=='scan' for n in plan['nodes'])!=1:
        gap('SOURCE_CHAIN_GAP')
    if gaps:return {'status':'RUNTIME_IMPLEMENTATION_GAP','gaps':gaps,'attribution':'facility','formal_ready':False}
    return {'status':'REFERENCE_PROFILE_READY','chain':list(reversed(chain)),'formal_ready':False}


def _source_snapshot(directory):
    return canonical({str(p.relative_to(ROOT)):p.read_text(encoding='utf8')
                      for p in sorted((ROOT/directory).glob('*.py'))})


def run_f1_reference(task,plan,*,registry:FileRegistry,recipe:dict,output:Path,
                     condition_id='DEV-C0',record_id='dev-run-0',generation_id='handcrafted-0',
                     repeat_id='r0',max_materialized_rows=100000):
    """Execute a fixed, trusted dev fixture through the actual submitted WorkIR.

    `recipe` stays entirely on the verifier side. It never enters any kernel or
    generated request. No statistical/benchmark claim is emitted by this API.
    `output` is an owner-selected fresh private directory, not a plan field.
    """
    task=deepcopy(task);plan=deepcopy(plan);recipe=deepcopy(recipe)
    compiled=validate_workflow(task,plan);ready=preflight(task,plan,compiled)
    if ready['status']!='REFERENCE_PROFILE_READY':return {**ready,'execution_started':False}
    if type(max_materialized_rows) is not int or not 0<max_materialized_rows<=1000000:
        raise ExecFault('ENGINEERING_CAP_INVALID')
    checked=validate_public_task(task)
    if set(registry.entries)!={s['id'] for s in task['datasets']}:raise ExecFault('REGISTRY_TASK_MISMATCH')
    # Re-bind this exact task, not the task which happened to create a registry.
    source_meta={s['id']:s for s in checked['source_manifest']}
    for e in registry.entries.values():
        s=source_meta[e.source_id]
        if (s.get('data_sha256')!=e.expected_sha256 or s.get('revision')!=e.revision
            or s.get('schema_hash')!=e.schema_hash):raise ExecFault('REGISTRY_TASK_MISMATCH')
    runtime_bytes=_source_snapshot('rcwg_exec');compiler_bytes=_source_snapshot('rcwg_spec')
    components={
        'runtime':{'revision':PROFILE,'python':platform.python_version(),
                   'source_sha256':hashlib.sha256(runtime_bytes).hexdigest(),
                   'execution_policy':'serial-pull-reference','max_materialized_rows':max_materialized_rows,
                   'filter_vectorized':'bounded_batch_mask_python_reference_not_SIMD','formal_native_kernel':False},
        'cache_policy':{'revision':'EXEC001_RUN_LOCAL_0.1','cross_run_results':False,
                        'data_cache':'observed_uncontrolled','input_precheck_reads':True},
        'verifier':{'revision':'F1_INDEPENDENT_SORT_V1','recipe_sha256':digest(recipe),
                    'source_sha256':hashlib.sha256((ROOT/'rcwg_exec/verifier.py').read_bytes()).hexdigest()},
        'metric_spec':{'revision':'EXEC001_DIAGNOSTIC_0.1','mode':'engineering_only'},
        'measurement_profile':{'revision':'EXEC001_LOCAL_OBSERVATION_0.1','event_source_id':'local-worker',
                               'clock_id':'perf-counter-local','isolated_cgroup':False,
                               'timeline_semantics':'iterator-active-inclusive-not-physical-parallelism'},
        'operator_registry':{'revision':PROFILE,'implementations':{k:sorted(v) for k,v in SUPPORTED.items()}},
        'source_manifest':{'revision':'EXEC001_OWNER_REGISTRY_0.1','public_sources':checked['source_manifest']}}
    context=build_context(task,condition_id=condition_id,data_manifest=registry.manifest(),**components)
    manifest=freeze_expected(context,[{'record_id':record_id,'record_role':'MODEL','plan':plan,
        'compiler_source':compiler_bytes,'generation_id':generation_id,'repeat_id':repeat_id,'repeat_role':'PRIMARY_REPEAT'}])
    expected=manifest.as_dict()['expected_records'][0];execution_key=expected['execution_key']
    store=PrivateStore(output)
    # Durable expected denominator precedes the first execution event.
    store.write_json('expected_manifest.json',manifest.as_dict());store.write_json('task.json',task)
    store.write_json('plan.json',plan);store.write_json('compiler_report.json',compiled)
    observations=[]
    def emit(kind,status,payload):
        if kind != 'node_queued':
            observations.append({'event':kind,'status':status,'monotonic_ns':time.perf_counter_ns(),'payload':deepcopy(payload)})
    from .engine import execute_chain
    executed=execute_chain(task,plan,registry=registry,compiled=compiled,store=store,
        execution_key=execution_key,manifest_hash=manifest.manifest_hash,
        max_materialized_rows=max_materialized_rows,emit=emit)
    terminal=executed['terminal_status'];failure=executed['failure'];artifact=executed['artifact']
    elapsed=executed['elapsed_ns'];cpu=executed['process_cpu_ns']
    counters=executed['node_counters'];states=executed['node_states']
    verifier0=time.perf_counter_ns()
    if terminal=='COMPLETED' and artifact is not None:
        entry=registry.entries.get(recipe.get('source_id'))
        verification=verify_f1(task=task,recipe=recipe,data_path=entry.path if entry else Path('/nonexistent'),
                              artifact_path=store.root/'result.json',artifact_meta=artifact,max_rows=max_materialized_rows)
    else:verification={'status':'UNKNOWN','reason':'RUN_INCOMPLETE'}
    verifier_ns=time.perf_counter_ns()-verifier0
    ledger=seal_events(manifest,record_id,observations)
    sidecar=make_sidecar(manifest,record_id,ledger,terminal_status=terminal,verification_status=verification['status'])
    evidence=validate_evidence(manifest,[sidecar],{record_id:ledger})
    # Run-level CPU is measured; node active intervals overlap nested pulls and
    # must not be summed or interpreted as parallel execution.
    measurements={'profile':PROFILE,'scope':'ENGINEERING_DIAGNOSTIC_ONLY',
        'completed_wall_ns':elapsed if terminal=='COMPLETED' else None,'elapsed_ns':elapsed,
        'process_cpu_ns':cpu,'verifier_wall_ns_separate':verifier_ns,
        'process_lifetime_rss_hwm_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 if platform.system()=='Linux' else None,
        'worker_peak_ram_bytes':None,'worker_peak_ram_reason':'NO_ISOLATED_CGROUP',
        'physical_copy_bytes':None,'physical_copy_reason':'NOT_INSTRUMENTED',
        'block_io_bytes':None,'block_io_reason':'NOT_MEASURED',
        'remote_gpu_seconds':None,'remote_gpu_reason':'NOT_APPLICABLE_NO_API',
        'budget_within':None,'budget_reason':'REQUIRED_MEMORY_NOT_VERIFIED',
        'node_counters':counters,'measurement_validity':'NOT_CALIBRATED','formal_ready':False}
    store.write_json('events.json',ledger);store.write_json('sidecar.json',sidecar)
    store.write_json('verification.json',verification);store.write_json('measurements.json',measurements)
    report={'status':'EXEC001_REFERENCE_COMPLETE' if terminal=='COMPLETED' else 'EXEC001_REFERENCE_TERMINATED',
        'profile':PROFILE,'terminal_status':terminal,'failure':failure,'verification':verification,
        'artifact':artifact,'execution_key':execution_key,'expected_manifest_hash':manifest.manifest_hash,
        'evidence_binding':evidence,'measurements':measurements,'static_status':compiled['status'],
        'node_states':states,'execution_started':True,'formal_ready':False,'real_model_requests':0,
        'cloud_mutations':0,'kernel_backend':'PYTHON_REFERENCE','native_formal_comparability':'NOT_VALIDATED'}
    store.write_json('report.json',report)
    return report
