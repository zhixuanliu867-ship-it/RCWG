"""Parent-owned identity, frozen before any worker is started."""
from __future__ import annotations
import hashlib
from pathlib import Path
import platform
from rcwg_spec.common import canonical,digest
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.binding import build_context,freeze_expected
from . import PROFILE
from .runner import SUPPORTED
from .errors import ExecFault

ROOT=Path(__file__).resolve().parents[1]
SUPERVISOR_REVISION='EXEC001_SUPERVISED_SERIAL_PULL_1.0'


def source_closure():
    files=[p for folder in ('rcwg_boot','rcwg_spec','rcwg_exec') for p in sorted((ROOT/folder).glob('*.py'))]
    files += [ROOT/'configs/boot.json',ROOT/'specs/exec001/runtime_contract.json']
    for folder in ('specs/reference_v1_0','specs/spec001a','specs/spec001b','prompts/v1_1'):
        files.extend(p for p in sorted((ROOT/folder).rglob('*')) if p.is_file())
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def compiler_source():
    return canonical({str(p.relative_to(ROOT)):p.read_text(encoding='utf8') for p in sorted((ROOT/'rcwg_spec').glob('*.py'))})


def prepare_manifest(task,plan,registry,recipe,*,condition_id,record_id,generation_id,repeat_id,max_materialized_rows,fault):
    checked=validate_public_task(task)
    expected={s['id']:s for s in checked['source_manifest']}
    if set(registry.entries)!=set(expected):raise ExecFault('REGISTRY_TASK_MISMATCH')
    for key,entry in registry.entries.items():
        source=expected[key]
        if (source.get('data_sha256')!=entry.expected_sha256 or source.get('revision')!=entry.revision
                or source.get('schema_hash')!=entry.schema_hash):raise ExecFault('REGISTRY_TASK_MISMATCH')
    closure=source_closure()
    context=build_context(task,condition_id=condition_id,data_manifest=registry.manifest(),
        runtime={'revision':SUPERVISOR_REVISION,'kernel_profile':PROFILE,'python':platform.python_version(),
                 'source_closure':closure,'source_closure_hash':digest(closure),'max_materialized_rows':max_materialized_rows,
                 'fault_injection':fault,'worker_process_isolated':True,'network_calls':False,'formal_native_kernel':False},
        cache_policy={'revision':'EXEC001_RUN_LOCAL_1.0','cross_run_results':False,'data_cache':'observed_uncontrolled','input_precheck_reads':True},
        verifier={'revision':'F1_INDEPENDENT_SORT_V1','recipe_sha256':digest(recipe),
                  'source_sha256':closure['rcwg_exec/verifier.py'],'execution_scope':'parent_after_worker_exit'},
        metric_spec={'revision':'EXEC001_DIAGNOSTIC_1.0','mode':'engineering_only'},
        measurement_profile={'revision':'EXEC001_SUPERVISOR_OBSERVATION_1.0','event_source_id':'supervised-runner',
                             'clock_id':'linux-monotonic-host','isolated_cgroup':False,
                             'wall_scope':'parent_launch_cleanup_and_integrity_checks_excludes_verifier',
                             'cpu_scope':'worker_kernel_interval_excludes_startup_compilation_and_verifier',
                             'node_intervals':'inclusive_iterator_activity_not_physical_concurrency'},
        operator_registry={'revision':PROFILE,'implementations':{k:sorted(v) for k,v in SUPPORTED.items()}},
        source_manifest={'revision':'EXEC001_OWNER_REGISTRY_1.0','public_sources':checked['source_manifest']})
    return freeze_expected(context,[{'record_id':record_id,'record_role':'MODEL','plan':plan,
         'compiler_source':compiler_source(),'generation_id':generation_id,'repeat_id':repeat_id,'repeat_role':'PRIMARY_REPEAT'}])
