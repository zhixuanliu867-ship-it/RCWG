"""Private external-track interchange, without inventing an upstream execution."""
import json,re
from pathlib import Path
from rcwg_full.evidence import ROOT,read,write,sha,digest,exclusive_directory
from rcwg_full.campaign.sealing import relative_file
from rcwg_full.compiler.public_task import validate_public_task


def registry():return json.loads(read(ROOT/'specs/full001/external_tracks.json'))


def prepare(track_id,task,*,upstream_snapshot=None,adaptation,output):
    tracks={row['id']:row for row in registry()['tracks']}
    if track_id not in tracks:raise ValueError('EXTERNAL_TRACK_UNKNOWN')
    public=validate_public_task(task)['normalized_task']
    if type(adaptation) is not dict or set(adaptation)!={'mapping_revision','preserved_semantics','changed_semantics','unsupported_obligations'}:
        raise ValueError('EXTERNAL_ADAPTATION_FIELDS')
    if not adaptation['mapping_revision'] or any(type(adaptation[k]) is not list for k in ['preserved_semantics','changed_semantics','unsupported_obligations']):raise ValueError('EXTERNAL_ADAPTATION_VALUES')
    blockers=[];snapshot=None
    if upstream_snapshot is None:blockers.append('UPSTREAM_SNAPSHOT_NOT_PINNED')
    else:
        snapshot=dict(upstream_snapshot)
        if (snapshot.get('upstream_url')!=tracks[track_id]['upstream_url'] or
            not re.fullmatch('[0-9a-f]{40}',snapshot.get('revision','')) or not snapshot.get('files')):raise ValueError('UPSTREAM_SNAPSHOT_IDENTITY')
        root=snapshot.pop('local_root')
        for name,expected in snapshot['files'].items():
            if sha(read(relative_file(root,name)))!=expected:raise ValueError('UPSTREAM_SNAPSHOT_FILE_CHANGED')
        if snapshot.get('license_status')!='VERIFIED':blockers.append('UPSTREAM_LICENSE_NOT_VERIFIED')
        if not snapshot.get('dependency_lock_sha256'):blockers.append('UPSTREAM_DEPENDENCIES_NOT_PINNED')
    blockers.append('UPSTREAM_NATIVE_MAPPING_NOT_EXECUTED')
    if adaptation['unsupported_obligations']:blockers.append('UNSUPPORTED_PUBLIC_OBLIGATIONS')
    out=exclusive_directory(output)
    task_hash=write(out/'task_public.json',public)
    protocol={'original':tracks[track_id]['original_protocol'],'original_source':tracks[track_id]['upstream_url'],
        'adapted':adaptation,'comparison_scope':'RCWG_ADAPTED_EXTERNAL_TRACK','primary_ledger_eligible':False}
    protocol_hash=write(out/'protocol.json',protocol)
    package={'schema_version':'FULL001_EXTERNAL_INTERCHANGE_1','track_id':track_id,'upstream_snapshot':snapshot,
        'ledger_role':'EXTERNAL_REPLICATION','task_id':task['task_id'],'task_sha256':task_hash,'protocol_sha256':protocol_hash,
        'status':'PREPARED_NOT_RUN','blockers':blockers,'actual_upstream_runs':0,'original_reproduction_claim':False,
        'execution_authorized':False,'formal_ready':False}
    package['manifest_hash']=digest(package);write(out/'manifest.json',package);return package


def import_observation(package_path,record,*,artifact_root,output):
    """Bind an externally produced observation; do not independently certify it."""
    package_path=Path(package_path)
    package=json.loads(read(package_path));root=package_path.parent
    if package['manifest_hash']!=digest({k:v for k,v in package.items() if k!='manifest_hash'}):raise ValueError('EXTERNAL_PACKAGE_HASH')
    for name,key in [('task_public.json','task_sha256'),('protocol.json','protocol_sha256')]:
        if sha(read(root/name))!=package[key]:raise ValueError('EXTERNAL_PACKAGE_FILE')
    required={'track_id','package_hash','attempt_id','mode','upstream_revision','command','exit_code','artifacts','metrics'}
    if type(record) is not dict or set(record)!=required:raise ValueError('EXTERNAL_OBSERVATION_FIELDS')
    if record['package_hash']!=package['manifest_hash'] or record['track_id']!=package['track_id']:raise ValueError('EXTERNAL_OBSERVATION_BINDING')
    if record['mode'] not in {'ENGINEERING_REPLAY','UPSTREAM_EXECUTION'}:raise ValueError('EXTERNAL_OBSERVATION_MODE')
    snapshot=package['upstream_snapshot']
    if record['mode']=='UPSTREAM_EXECUTION' and (snapshot is None or record['upstream_revision']!=snapshot['revision']):raise ValueError('UPSTREAM_REVISION_UNBOUND')
    if type(record['command']) is not list or not record['command'] or not all(type(v) is str for v in record['command']):raise ValueError('EXTERNAL_COMMAND')
    if type(record['exit_code']) is not int or type(record['artifacts']) is not dict or not record['artifacts']:raise ValueError('EXTERNAL_EVIDENCE_REQUIRED')
    for name,expected in record['artifacts'].items():
        if sha(read(relative_file(artifact_root,name)))!=expected:raise ValueError('EXTERNAL_ARTIFACT_CHANGED')
    result={'schema_version':'FULL001_EXTERNAL_OBSERVATION_1','status':'IMPORTED_UNVERIFIED',
        'record':record,'ledger_role':'EXTERNAL_REPLICATION','primary_ledger_eligible':False,
        'native_mapping_status':'PENDING_INDEPENDENT_VALIDATION','original_reproduction_claim':False,
        'formal_ready':False,'observation_hash':digest(record)}
    write(output,result);return result
