"""Predeclared complete formal blocks, after real reference confirmation."""
import json
from copy import deepcopy
from rcwg_full.evidence import read,write,sha,digest,canonical
from rcwg_full.reference.confirmation import confirm
from rcwg_spec.binding import RunnerContext
from .control import reference_gate,formal_gate


def load(path):return json.loads(read(path))


def phase_affordable(state,amount):
    with state.db() as db:
        rows=db.execute('SELECT s.body,r.amount FROM reservations r JOIN scopes s ON r.scope=s.id').fetchall()
    used=sum(cost for raw,cost in rows if load_stage(raw) in {'B_DEVELOPMENT','B_REFERENCE','B_FORMAL'})
    return state.affordable(amount) and used+amount<=int(state.policy['budget']['remaining_live_and_reference_allocation']*1_000_000)


def load_stage(raw):return json.loads(raw)['stage']


def continue_references_and_formal(pipeline):
    p=pipeline;root=p.root;pre=load(root/'FORMAL_PREREQUISITES.json');blocks=p.plan.get('formal_blocks',[])
    blockers=list(pre['blockers'])
    if p.config['measurement_profile']!='FORMAL_RESOURCE':blockers.append('RESOURCE_CALIBRATION_NOT_CLOSED')
    result={'status':'NOT_ADMITTED','blockers':sorted(set(blockers)),'references':[],'formal_blocks':[],
        'formal_generation':0,'formal_execution':0,'original_planned_generation':23040,'original_planned_execution':61440,
        'historical_planned_total':150880,'human_reapproval_required':False}
    if blockers:return result
    evidence=load(root/'PREPARATION_EVIDENCE.json')
    for key in ['frozen_data','analysis_freeze']:evidence[key]=pre['evidence'][key]
    for block in blocks:
        previous=root/'private/formal-gates'/block['id']/'block-results.json'
        if previous.exists():
            saved=load(previous)
            if saved.get('identity')!=p.current_identity():raise PermissionError('FORMAL_RESUME_IDENTITY_CHANGED')
            result['formal_blocks'].append(saved);result['references'].append({'block_id':block['id'],**saved['reference']})
            result['formal_generation']+=len(saved['generations']);result['formal_execution']+=len(saved['executions']);continue
        if block['family'] not in {'F1','F2','F3','F4'}:
            raise PermissionError('THIS_FORMAL_ADAPTER_REQUIRES_VERSIONED_SEMANTIC_REFERENCE_BOUNDS')
        scope=p.scope('B_REFERENCE',{'HOST':block['reference_max_executions']},0,scope_key=block['id'])
        admission=reference_gate(evidence,p.current_identity(),scope=scope,state=p.state)
        definitions=load(root/block['candidate_file']);context=RunnerContext(canonical(load(root/block['reference_context_file'])))
        def execute(plan,request):
            key=request['candidate_id']+'-'+request['role']+'-'+str(request['repeat'])
            job=deepcopy(block['reference_jobs'][key]);job.update(execution_mode='FORMAL',admission=admission)
            record=p.execution(job,plan,scope,reference=True)
            if record.get('comparison_context_hash')!=context.comparison_context_hash:
                return {**request,'status':'INFRA_FAILURE','reconciliation_required':True,'reason':'REFERENCE_CONTEXT_CHANGED'}
            return {**request,'status':record['status'],'semantic':record.get('verification',{}).get('status')=='PASS',
                'budget':record.get('budget_within'),'timing_valid':bool(record.get('evidence_bound') and record.get('measurement_validity',{}).get('valid')),
                'exec_elapsed_ns':record.get('exec_elapsed_ns'),'report_sha256':record.get('report_sha256')}
        directory=root/'private/references'/block['id'];directory.parent.mkdir(parents=True,exist_ok=True)
        reference=confirm(definitions,context,execute,directory,resume=(directory/'manifest.json').exists())
        result['references'].append({'block_id':block['id'],**reference})
        if not reference['confirmed']:
            result['blockers'].append('REFERENCE_MISSING:'+block['id']);continue
        observed=[]
        for slot in ['G0','G1','G2','G3','G4','G5']:
            binding=next(b for b in p.models['bindings'] if b['slot']==slot)
            file=p.index.root/('observed-model-'+digest(binding)+'.json')
            if slot in p.available and file.exists():observed.append(load(file)['reported_revision'])
        if len(observed)!=6 or len(set(observed))!=6:
            result['blockers'].append('SIX_DISTINCT_OBSERVED_GENERATORS_REQUIRED');continue
        if not phase_affordable(p.state,block['reserved_upper_microusd']):
            result['blockers'].append('NO_AFFORDABLE_COMPLETE_FORMAL_BLOCK:'+block['id']);break
        identity=p.current_identity();gate_dir=root/'private/formal-gates'/block['id'];gate_dir.mkdir(parents=True,exist_ok=True)
        for key,payload in {'model_coverage':{'observed_generator_identities':observed},
            'reference_coverage':{'next_block_common_coverage':True,'reference_id':reference['reference_id'],
                                  'context_hash':context.comparison_context_hash,'elapsed_ns':reference['elapsed_ns']}}.items():
            file=gate_dir/(key+'.json');value={'status':'PASS','identity':identity,**payload}
            if file.exists():
                if load(file)!=value:raise PermissionError('FORMAL_GATE_CHANGED')
            else:write(file,value)
            evidence[key]={'path':str(file),'sha256':sha(read(file))}
        live=p.scope('B_FORMAL',block['limits'],block['reserved_upper_microusd'],scope_key=block['id'])
        admitted=formal_gate(evidence,identity,scope=live,state=p.state)
        completed=gate_dir/'block-results.json'
        if completed.exists():block_result=load(completed)
        else:
            generations=[];executions=[]
            for job in block['generations']:
                generation=p.generation(job,live);generations.append({'job_id':job['id'],'status':generation['status']})
                for item in job['executions']:
                    item=deepcopy(item);item.update(execution_mode='FORMAL',admission=admitted)
                    outcome=p.execution(item,generation['plan'] if generation['status']=='COMPLETED' else None,live)
                    executions.append({'job_id':item['id'],'status':outcome['status'],'verification':outcome.get('verification'),
                        'budget_within':outcome.get('budget_within'),'exec_elapsed_ns':outcome.get('exec_elapsed_ns')})
                    if outcome['status'] in {'INFRA_FAILURE','SENT_UNCONFIRMED','UNKNOWN','SERVICE_DRIFT'}:
                        raise PermissionError('FORMAL_BLOCK_REQUIRES_RECONCILIATION')
            block_result={'block_id':block['id'],'identity':identity,'status':'PARTIAL_CAMPAIGN_COMPLETE_BLOCK','admission':admitted,
                          'generations':generations,'executions':executions,'reference':reference}
            write(completed,block_result)
        result['formal_blocks'].append(block_result)
        result['formal_generation']+=len(block_result['generations']);result['formal_execution']+=len(block_result['executions'])
    result['status']='PARTIAL_FORMAL' if result['formal_blocks'] else 'REFERENCES_ONLY' if result['references'] else 'NOT_ADMITTED'
    result['blockers']=sorted(set(result['blockers']));return result
