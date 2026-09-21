"""Independent L0-L4 judgments; missing metrology never becomes zero cost or PASS."""
from pathlib import Path
import json
from rcwg_full.evidence import read,sha,canonical
from rcwg_full.runtime.events import verify_journal
from rcwg_full.verification.compare import check_output,check_paths
from rcwg_full.verification.semantic import verify_semantics


def check_complete_journal(path,*,run_id=None,expected_instances=None):
    events=verify_journal(path,run_id=run_id)
    if not events or events[0]['event_kind']!='run_started' or events[-1]['event_kind']!='run_finished':raise ValueError('JOURNAL_RUN_BOUNDARIES')
    if sum(e['event_kind']=='run_started' for e in events)!=1 or sum(e['event_kind']=='run_finished' for e in events)!=1:raise ValueError('JOURNAL_RUN_BOUNDARIES')
    started={};finished=set()
    for event in events:
        ident=event['node_instance'];kind=event['event_kind']
        if kind=='node_started':
            if ident in started or ident is None:raise ValueError('JOURNAL_NODE_DUPLICATE')
            started[ident]=event['payload']
        elif kind=='node_finished':
            if ident not in started or ident in finished:raise ValueError('JOURNAL_NODE_ORDER')
            for field in ['operator','implementation']:
                if event['payload'][field]!=started[ident][field]:raise ValueError('JOURNAL_DISPATCH_CHANGED')
            finished.add(ident)
    if events[-1]['status']=='COMPLETED' and set(started)!=finished:raise ValueError('JOURNAL_NODE_INCOMPLETE')
    if expected_instances is not None and len(started)!=expected_instances:raise ValueError('JOURNAL_INSTANCE_COUNT')
    return events


def verify_layers(directory,recipe):
    root=Path(directory);layers={};report=json.loads(read(root/'report.json'))
    try:actual=json.loads(read(root/'worker/result.json'));layers['L0']={'status':'PASS'}
    except (OSError,ValueError):actual=None;layers['L0']={'status':'FAIL','reason':'RESULT_MISSING_OR_MALFORMED'}
    try:
        events=check_complete_journal(root/'worker/events.jsonl',run_id=report['run_id'],expected_instances=report['worker']['logical_instances'])
        seal=json.loads(read(root/'worker/journal-seal.json'))
        if sha(read(root/'worker/events.jsonl'))!=seal['journal_sha256']:raise ValueError('JOURNAL_SEAL')
        from rcwg_spec.binding import ExpectedManifest,validate_evidence
        expected=ExpectedManifest(canonical(json.loads(read(root/'expected.json'))))
        sidecar=json.loads(read(root/'sidecar.json'));bound=json.loads(read(root/'bound-events.json'))
        binding=validate_evidence(expected,[sidecar],{report['run_id']:bound})
        if binding['status']!='EVIDENCE_BOUND':raise ValueError('BINDING_INCOMPLETE')
        layers['L1']={'status':'PASS','comparison_context_hash':binding['comparison_context_hash']}
    except (OSError,ValueError,KeyError,TypeError) as exc:layers['L1']={'status':'FAIL','reason':str(exc)}
    if layers['L0']['status']!='PASS':layers['L2']={'status':'UNKNOWN','reason':'NO_USABLE_RESULT'}
    elif recipe['kind']=='paths':
        passed,reason=check_paths(actual,recipe['graph'],recipe['seeds'],recipe['targets'],weight_field=recipe.get('weight_field'),direction=recipe.get('direction','out'))
        layers['L2']={'status':'PASS' if passed else 'FAIL','reason':reason}
    else:layers['L2']=check_output(actual,recipe['expected'],recipe['contract'])
    layers['L3']=verify_semantics(actual,recipe['semantic']) if 'semantic' in recipe and actual is not None else {'status':'NOT_APPLICABLE','reason':'NO_SEMANTIC_OBLIGATIONS'}
    m=report['measurements']
    if not m.get('calibrated') or m.get('budget_within') is None:layers['L4']={'status':'UNKNOWN','reason':'MEASUREMENT_NOT_CALIBRATED_OR_BUDGET_UNRESOLVED'}
    else:layers['L4']={'status':'PASS' if m['budget_within'] else 'FAIL','reason':None if m['budget_within'] else 'RESOURCE_BUDGET_EXCEEDED'}
    software=all(layers[k]['status'] in {'PASS','NOT_APPLICABLE'} for k in ['L0','L1','L2','L3'])
    status='FAIL' if any(x['status']=='FAIL' for x in layers.values()) else 'UNKNOWN' if any(x['status']=='UNKNOWN' for x in layers.values()) else 'PASS'
    return {'status':status,'software_result':'PASS' if software else 'FAIL','layers':layers,'formal_ready':False}
