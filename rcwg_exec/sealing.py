"""Artifact and complete-run reread against externally retained identities."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from rcwg_spec.common import canonical,digest
from rcwg_spec.binding import ExpectedManifest,validate_evidence
from rcwg_spec.compiler import validate_workflow
from .datasets import open_regular
from .errors import ExecFault
from .journal import read_json,read_journal,validate_node_events


def bytes_at(path):
    with os.fdopen(open_regular(path),'rb') as stream:return stream.read()


def validate_artifact(directory,*,expected,task,plan,compiled,creation_window=None):
    directory=Path(directory)
    raw=bytes_at(directory/'result.json');value=read_json(directory/'result.json')
    meta=read_json(directory/'artifact.json');binding=read_json(directory/'artifact_binding.json')
    fields={'artifact_id','content_sha256','type','producer','serialized_bytes','rows','created_ns','released_ns','format','source_refs'}
    if type(meta) is not dict or set(meta)!=fields:raise ExecFault('ARTIFACT_METADATA_SHAPE')
    actual=hashlib.sha256(raw).hexdigest()
    if (type(value) is not list or type(meta['rows']) is not int or meta['rows']!=len(value)
            or type(meta['serialized_bytes']) is not int or meta['serialized_bytes']!=len(raw)
            or meta['content_sha256']!=actual or meta['artifact_id']!='sha256:'+actual):
        raise ExecFault('ARTIFACT_CONTENT_MISMATCH')
    if (meta['producer']!=plan['result'] or meta['source_refs']!=sorted(d['id'] for d in task['datasets'])
            or meta['type']!=compiled['typed_graph']['result']['type']['kind']
            or type(meta['created_ns']) is not int or meta['created_ns']<0
            or meta['released_ns'] is not None or meta['format']!='json'):
        raise ExecFault('ARTIFACT_METADATA_MISMATCH')
    if binding!={'schema_version':'EXEC001_ARTIFACT_BINDING_0.1','execution_key':expected['execution_key'],
                 'artifact_sha256':actual,'artifact_metadata_sha256':digest(meta)}:
        raise ExecFault('ARTIFACT_EXECUTION_BINDING')
    if creation_window is not None and not creation_window[0]<=meta['created_ns']<=creation_window[1]:
        raise ExecFault('ARTIFACT_CREATION_CLOCK')
    return meta


def validate_measurements(measurements,terminal):
    if measurements.get('scope')!='ENGINEERING_DIAGNOSTIC_ONLY' or measurements.get('formal_ready') is not False:
        raise ExecFault('MEASUREMENT_SCOPE')
    if (measurements.get('process_cpu_scope')!='worker_kernel_interval_excludes_startup_compilation_and_verifier'
            or measurements.get('rss_scope')!='worker_process_lifetime_including_startup_and_compilation_not_isolated_ram'):
        raise ExecFault('MEASUREMENT_PROCESS_SCOPE')
    for key in ('worker_peak_ram_bytes','physical_copy_bytes','block_io_bytes','budget_within'):
        if measurements.get(key) is not None:raise ExecFault('MEASUREMENT_OVERCLAIM')
    elapsed=measurements.get('elapsed_ns');completed=measurements.get('completed_wall_ns')
    if type(elapsed) is not int or elapsed<0:raise ExecFault('MEASUREMENT_ELAPSED')
    if terminal=='COMPLETED':
        if type(completed) is not int or completed!=elapsed:raise ExecFault('MEASUREMENT_COMPLETION')
    elif completed is not None:raise ExecFault('MEASUREMENT_CENSORED')
    for key in ('process_cpu_ns','worker_execution_wall_ns','process_lifetime_rss_hwm_bytes'):
        value=measurements.get(key)
        if value is not None and (type(value) is not int or value<0):raise ExecFault('MEASUREMENT_TYPE')
    for key in ('verifier_wall_ns_separate','verifier_cpu_ns_separate','supervisor_process_cpu_ns'):
        if type(measurements.get(key)) is not int or measurements[key]<0:raise ExecFault('MEASUREMENT_TYPE')
    if measurements.get('process_cpu_ns') is None and measurements.get('worker_measurement_reason')!='NO_FINAL_WORKER_OBSERVATION':
        raise ExecFault('MEASUREMENT_MISSING_REASON')
    return True


def seal_directory(store,manifest,expected):
    files={}
    for path in sorted(store.root.rglob('*')):
        if path.is_symlink():raise ExecFault('SEALED_PATH_SYMLINK')
        if path.is_file():files[str(path.relative_to(store.root))]=hashlib.sha256(bytes_at(path)).hexdigest()
    seal={'schema_version':'EXEC001_RUN_SEAL_1.0','manifest_hash':manifest.manifest_hash,
          'execution_key':expected['execution_key'],'files':files,'formal_ready':False}
    return store.write_json('seal.json',seal)


def reopen_run(directory,*,manifest:ExpectedManifest,seal_sha256:str):
    directory=Path(directory)
    if hashlib.sha256(bytes_at(directory/'seal.json')).hexdigest()!=seal_sha256:raise ExecFault('RUN_SEAL_MISMATCH')
    seal=read_json(directory/'seal.json');expected=manifest.as_dict()['expected_records'][0]
    if (seal.get('schema_version')!='EXEC001_RUN_SEAL_1.0' or seal.get('manifest_hash')!=manifest.manifest_hash
            or seal.get('execution_key')!=expected['execution_key'] or seal.get('formal_ready') is not False):
        raise ExecFault('RUN_SEAL_IDENTITY')
    actual_names=set()
    for path in directory.rglob('*'):
        if path.is_symlink():raise ExecFault('SEALED_PATH_SYMLINK')
        if path.is_file() and path!=directory/'seal.json':actual_names.add(str(path.relative_to(directory)))
    if set(seal['files'])!=actual_names:raise ExecFault('RUN_SEAL_FILE_SET')
    for name,expected_hash in seal['files'].items():
        path=directory/name
        if not path.resolve().is_relative_to(directory.resolve()):raise ExecFault('RUN_SEAL_PATH')
        if hashlib.sha256(bytes_at(path)).hexdigest()!=expected_hash:raise ExecFault('RUN_FILE_CHANGED')
    if bytes_at(directory/'expected_manifest.json')!=canonical(manifest.as_dict()):
        # Compare canonical content below as well; do not accept a rewritten denominator.
        raise ExecFault('EXPECTED_MANIFEST_CHANGED')
    task=read_json(directory/'task.json');plan=read_json(directory/'plan.json')
    if digest(task)!=expected['input_hash'] or digest(plan)!=expected['plan_hash']:raise ExecFault('RUN_INPUT_IDENTITY')
    report=read_json(directory/'report.json');measurements=read_json(directory/'measurements.json')
    verification=read_json(directory/'verification.json');sidecar=read_json(directory/'sidecar.json');ledger=read_json(directory/'events.json')
    bound=validate_evidence(manifest,[sidecar],{expected['record_id']:ledger})
    if (report['execution_key']!=expected['execution_key'] or report['expected_manifest_hash']!=manifest.manifest_hash
            or report['terminal_status']!=sidecar['terminal_status'] or report['verification']!=verification
            or report['measurements']!=measurements or verification['status']!=sidecar['verification']['status']):
        raise ExecFault('RUN_REPORT_BINDING')
    validate_measurements(measurements,report['terminal_status'])
    parent=read_journal(directory/'supervisor.journal.jsonl',execution_key=expected['execution_key'],
        manifest_hash=manifest.manifest_hash,origin='supervisor',pid=report['parent_pid'])['events']
    if (not parent or parent[0]['event']!='run_started' or parent[-1]['event']!='run_finished'
            or parent[-1]['status']!=report['terminal_status']
            or parent[-1]['payload']['elapsed_ns']!=measurements['elapsed_ns']):
        raise ExecFault('SUPERVISOR_JOURNAL_BOUNDARY')
    if report['terminal_status']=='COMPLETED':
        artifact=validate_artifact(directory/'worker',expected=expected,task=task,plan=plan,compiled=validate_workflow(task,plan),
            creation_window=(parent[0]['monotonic_ns'],parent[-1]['monotonic_ns']))
        if report['artifact']!=artifact:raise ExecFault('RUN_ARTIFACT_BINDING')
    worker=directory/'worker.journal.jsonl'
    if worker.exists():
        try:
            journal=read_journal(worker,execution_key=expected['execution_key'],manifest_hash=manifest.manifest_hash,
                origin='worker',pid=report['worker_pid'],allow_partial=report['terminal_status']!='COMPLETED')
            validate_node_events(journal['events'],plan,completed=report['terminal_status']=='COMPLETED')
        except ExecFault as exc:
            # An invalid journal is preserved as facility-failure evidence, never
            # promoted to a successfully observed execution.
            if report['terminal_status']!='INFRA_FAILURE' or report.get('journal_error')!=exc.code:raise
    return {'status':'EXEC001_RUN_REOPENED','evidence':bound,'terminal_status':report['terminal_status'],
            'verification':verification['status'],'formal_ready':False}
