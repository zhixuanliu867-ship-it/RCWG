"""Controller-only projections from immutable attempt evidence; private by default."""
from collections import defaultdict
from pathlib import Path
import hashlib,json
from rcwg_full.evidence import digest,read,safe_path
from rcwg_full.campaign.sealing import relative_file
from rcwg_full.runtime.events import verify_journal


def file_hash(path):
    with safe_path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def index_attempt(api,campaign_id,run_id,runner,slot_id):
    slot=runner.store.slot(slot_id);attempt=slot['active_attempt']
    if attempt is None:return {'status':'NO_PHYSICAL_ATTEMPT','files':0,'nodes':0,'buffers':0}
    row=runner.store.db.execute('SELECT evidence FROM attempts WHERE id=?',(attempt,)).fetchone()
    evidence=json.loads(row['evidence'])
    outcome=relative_file(runner.root,evidence['result_file'])
    if file_hash(outcome)!=evidence['result_sha256']:raise ValueError('CONTROL_OUTCOME_IDENTITY')
    directory=outcome.parent;native=directory/'native';events=[];documents=[]
    base={'campaign_id':campaign_id,'run_id':run_id,'attempt_id':attempt,'visibility':'PRIVATE'}
    if (native/'seal.json').is_file():
        seal=json.loads(read(native/'seal.json'))
        if seal.get('status')!='SEALED':raise ValueError('CONTROL_NATIVE_UNSEALED')
        for name,expected in seal['files'].items():
            if file_hash(relative_file(native,name))!=expected:raise ValueError('CONTROL_NATIVE_ARTIFACT_CHANGED')
        journal=native/'worker/events.jsonl'
        if journal.is_file():events=verify_journal(journal,run_id=seal['run_id'])
    for path in sorted(directory.rglob('*')):
        safe_path(path)
        if not path.is_file():continue
        relative=path.relative_to(runner.root).as_posix()
        documents.append(('artifact',digest({'run':run_id,'file':relative}),{**base,'kind':'EVIDENCE_FILE',
            'relative_path':relative,'bytes':path.stat().st_size,'sha256':file_hash(path)}))
    nodes=defaultdict(list);buffers=defaultdict(list)
    for event in events:
        if event['node_instance'] is not None:nodes[event['node_instance']].append(event)
        if event['event_kind'] in {'buffer_created','buffer_released'}:buffers[event['payload']['buffer_id']].append(event)
    for ident,trace in nodes.items():
        documents.append(('node_instance',digest({'run':run_id,'node':ident}),{**base,'node_instance_id':ident,
            'status':trace[-1]['status'],'first_monotonic_ns':trace[0]['monotonic_ns'],
            'last_monotonic_ns':trace[-1]['monotonic_ns'],'events':trace,'trace_hash':digest(trace)}))
    for ident,trace in buffers.items():
        created=[e for e in trace if e['event_kind']=='buffer_created'];released=[e for e in trace if e['event_kind']=='buffer_released']
        if len(created)!=1 or len(released)>1:raise ValueError('CONTROL_BUFFER_EVENTS')
        documents.append(('artifact',digest({'run':run_id,'buffer':ident}),{**base,'kind':'BUFFER_LIFETIME','buffer_id':ident,
            'capacity_bytes':created[0]['payload'].get('capacity_bytes'),'storage_kind':created[0]['payload'].get('storage_kind'),
            'created_monotonic_ns':created[0]['monotonic_ns'],
            'released_monotonic_ns':released[0]['monotonic_ns'] if released else None,'trace_hash':digest(trace)}))
    result=json.loads(read(outcome))
    documents.append(('metric_summary',digest({'run':run_id,'metrics':True}),{**base,'slot_id':slot_id,
        'status':slot['status'],'ledger_role':slot['definition']['ledger_role'],
        'metrics':{k:result.get(k) for k in ['semantic','budget','timing_valid','exec_elapsed_ns','worker_memory_peak_bytes','measurement']},
        'source_outcome_sha256':evidence['result_sha256']}))
    report=native/'report.json'
    if report.is_file():
        value=json.loads(read(report))
        documents.append(('verification_record',digest({'run':run_id,'verification':True}),{**base,
            'verification':value.get('verification'),'binding_validation':value.get('binding_validation'),
            'source_report_sha256':file_hash(report)}))
    with api.store.transaction():
        for kind,ident,document in documents:
            try:old=api.get(kind,ident)
            except KeyError:api.put(kind,ident,document)
            else:
                if {k:v for k,v in old.items() if k not in {'id','version'}}!=document:raise ValueError('CONTROL_INDEX_IMMUTABLE')
        api.store._audit('evidence_indexed',{'run_id':run_id,'attempt_id':attempt,'records':len(documents),'outcome_sha256':evidence['result_sha256']})
    return {'status':'INDEXED_PRIVATE','files':sum(d[2].get('kind')=='EVIDENCE_FILE' for d in documents),
            'nodes':len(nodes),'buffers':len(buffers),'outcome_sha256':evidence['result_sha256']}
