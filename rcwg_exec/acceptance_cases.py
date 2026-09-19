"""Synthetic engineering-only corpus, with explicit expected outcomes."""
from copy import deepcopy
from pathlib import Path
from rcwg_spec.common import canonical,digest
from rcwg_exec.demo import prepare_fixture

LOGICAL={'required_outputs':['id and score ordered by score descending, then id ascending'],
         'hard_constraints':['eligible records only'], 'necessary_operations':['filter and exact top k'],
         'data_dependencies':['registered records'], 'information_requirements':['id, score, eligible'],
         'permissible_alternatives':['heap or full sort'], 'uncertainty':[]}


def development_cases(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    task,plans,recipe,data=prepare_fixture(directory/'fixture',n=97,k=9,seed=31)
    rows=[];expect={}
    def add(name,plan,*,outcome='COMPLETED',verification='PASS',protocol=None,fault='none',timeout=None,cancel=None,responses=None):
        t=deepcopy(task);r=deepcopy(recipe)
        if timeout is not None:t['resources']['wall_timeout_s']=timeout;r['task_input_hash']=digest(t)
        entry={'attempt_id':name,'task':t,'recipe':r,'locations':{t['datasets'][0]['id']:data},'allowed_root':directory,
               'fault':fault,'cancel_after_s':cancel,'plan':deepcopy(plan)}
        if protocol:
            entry['protocol']=protocol;entry['responses']=responses or ([canonical(plan)] if protocol=='P0' else [canonical(LOGICAL),canonical(plan)])
            del entry['plan']
        rows.append(entry);expect[name]={'outcome':outcome,'verification':verification}
    scalar=deepcopy(plans['streaming_heap']);scalar['nodes'][1]['implementation']='scalar'
    copy=deepcopy(plans['full_sort']);copy['nodes'][3]['implementation']='copy';copy['nodes'][3]['storage']='memory'
    add('p0-heap-scalar-view',scalar,protocol='P0')
    add('p1-fullsort-vector-copy',copy,protocol='P1')
    add('missing-filter',plans['omitted_filter'],protocol='P0',verification='FAIL')
    for choice in ('k','keys','projection'):
        p=deepcopy(plans['streaming_heap'])
        if choice=='k':p['nodes'][2]['params']['k']=1
        elif choice=='keys':p['nodes'][2]['params']['keys'][0]['direction']='asc'
        else:p['nodes'][3]['params']['columns']=['id','score','eligible']
        add('wrong-'+choice,p,protocol='P0',verification='FAIL')
    invalid=deepcopy(scalar);invalid['nodes'][2]['params']['k']=-1
    add('static-invalid',invalid,protocol='P0',outcome='PLAN_INVALID',verification='UNKNOWN')
    gap=deepcopy(scalar);gap['nodes'][2]['after']=['keep']
    add('facility-gap',gap,protocol='P1',outcome='RUNTIME_IMPLEMENTATION_GAP',verification='UNKNOWN')
    add('invalid-response',scalar,protocol='P0',responses=[b'{'],outcome='MOCK_RESPONSE_INVALID',verification='UNKNOWN')
    add('invalid-logical',scalar,protocol='P1',responses=[b'{}',canonical(scalar)],outcome='MOCK_RESPONSE_INVALID',verification='UNKNOWN')
    add('deadline',scalar,fault='stall',timeout=.5,outcome='TIMEOUT',verification='UNKNOWN')
    add('cancel',scalar,fault='stall',cancel=.5,outcome='UNKNOWN',verification='UNKNOWN')
    for fault in ('crash','nonzero','partial_artifact','partial_journal','corrupt_journal','drop_report','artifact_binding','artifact_metadata'):
        add(fault,scalar,fault=fault,outcome='INFRA_FAILURE',verification='UNKNOWN')
    add('descendant-cleanup',scalar,fault='spawn_descendant',timeout=1,outcome='TIMEOUT',verification='UNKNOWN')
    dynamic=deepcopy(scalar);dynamic['nodes'][1]['params']['predicate']={'op':'gt',
        'left':{'op':'div','left':{'field':'score'},'right':{'literal':0.0}},'right':{'literal':0.0}}
    add('dynamic-divzero',dynamic,outcome='MODEL_FAILURE',verification='UNKNOWN')
    # Independent verifier recomputes gold for these actual source files.
    for label,n,k,seed,custom in [
        ('empty',0,3,1,None),('kzero',23,0,2,None),('fewer',4,20,3,None),
        ('seed7',73,11,7,None),('seed19',81,13,19,None),
        ('ties-duplicates-negative',0,9,0,[{'id':i,'score':float(-i%3-5),'eligible':True}
                                         for i in [5,4,3,3,2,1,1,0]])]:
        t,pp,r,dd=prepare_fixture(directory/('edge-'+label),n=n,k=k,seed=seed,rows=custom)
        for implementation in ('streaming_heap','full_sort'):
            ident='edge-'+label+'-'+implementation
            rows.append({'attempt_id':ident,'task':t,'recipe':r,'locations':{t['datasets'][0]['id']:dd},
                         'allowed_root':directory,'plan':pp[implementation]})
            expect[ident]={'outcome':'COMPLETED','verification':'PASS'}
    return rows,expect
