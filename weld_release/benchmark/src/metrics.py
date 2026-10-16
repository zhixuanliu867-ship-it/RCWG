"""Unweighted, denominator-explicit measurement registry and matched comparisons."""
import math
from collections import Counter
from common import *
from evaluator import ancestors,normalize_submission
def datum(value,unit='count',**kw):return {'status':'MEASURED','value':value,'unit':unit,**kw}
def na(reason):return {'status':'NOT_APPLICABLE','value':None,'reason':reason}
def needs(reason):return {'status':'NOT_OBSERVED','value':None,'reason':reason}
def roots(aid,artifacts):
    found,_=ancestors([aid],artifacts);observed=set();declared=set()
    for a in found.values():
        for r in a.get('source_record_refs',[]):
            if r.get('declared_only'):declared.add(r['source'])
            else:observed.add(canonical({'source':r['source'],'version':r.get('version'),'identity':r.get('identity')}))
    return observed,declared
def atomic(answer):
    out={}
    for k,v in answer.items():
        if isinstance(v,list):
            if not v:out[k+'::EMPTY']=[]
            for x in v:out[k+'::'+canonical(x)]=x
        else:out[k]=v
    return out
def atomic_hits(expected,answer):
    hits=set()
    for k,v in expected.items():
        got=answer.get(k)
        if not isinstance(v,list):
            if equal(got,v,k):hits.add(k)
        elif not v:
            if got==[]:hits.add(k+'::EMPTY')
        elif isinstance(got,list):
            remaining=list(got)
            for x in v:
                j=next((i for i,y in enumerate(remaining) if equal(y,x,k+'[]')),None)
                if j is not None:hits.add(k+'::'+canonical(x));remaining.pop(j)
    return hits
def contains(value,target):
    if isinstance(target,dict) and isinstance(value,dict) and all(k in value and equal(value[k],v,k) for k,v in target.items()):return True
    if isinstance(value,dict):return any(contains(v,target) for v in value.values())
    if isinstance(value,list):return any(contains(v,target) for v in value)
    return False
def summarize(task,evaluation,artifacts,events,requests,submission):
    submission=submission if isinstance(submission,dict) else {}
    gold=load(ROOT/f"private/{task['id']}.json");schema=load(ROOT/'protocol/metrics.json')['metrics'];m={x['id']:na('Mechanism or domain not applicable to this episode') for x in schema}
    answer=evaluation.get('answer',(normalize_submission(submission) or {}).get('answer',{}));checks=evaluation.get('field_checks',{});support=evaluation.get('support_checks',{});expected=gold['answer']
    m['M01']=rate(int(evaluation['success']),1);atoms=atomic(expected);got=atomic(answer);hit=atomic_hits(expected,answer)
    # Scalar tolerance is assessed using the typed contract, not canonical text.
    for k in expected:
        if checks.get(k):hit.update(x for x in atoms if x==k or x.startswith(k+'::'))
    m['M02']=rate(len(hit),len(atoms));m['M03']=rate(sum(c.get('factual',False) for c in evaluation.get('claim_checks',[])),len(evaluation.get('claim_checks',[])),'no submitted explicit claims')
    collection='paper_ids' if 'paper_ids' in expected else 'loan_ids' if 'loan_ids' in expected else 'regressions' if 'regressions' in expected else None
    if collection:
        target={canonical(x) for x in expected[collection]};pred={canonical(x) for x in answer.get(collection,[]) if isinstance(answer.get(collection),list)};n=len(answer.get(collection,[]))
        m['M04']=rate(len(target&pred),len(target),'verified empty target set');m['M05']=rate(len(target&pred),len(pred),'no output items');m['M06']=rate(n-len(pred),n)
        gaps={canonical(x) for x in gold.get('handoff_missing_ids',[])};m['M07']=rate(len(gaps-pred),len(gaps),'no designated gap');m['M08']=rate(len(gaps&pred),len(gaps),'gap-free condition')
    worker_hits=set()
    for a in artifacts.values():
        if a['kind']=='worker_result':
            value=a['content'];value=value.get('answer',value) if isinstance(value,dict) else {};worker_hits|=atomic_hits(expected,value) if isinstance(value,dict) else set()
    m['M09']=rate(len(worker_hits),len(atoms));m['M10']=rate(len(worker_hits&hit),len(worker_hits),'no correct worker-covered atomic obligations')
    if task['scenario']=='analytics' and 'monthly_rows' in expected:
        expected_ids={(x['customer_id'],x['month']) for x in expected['monthly_rows']};rows=answer.get('monthly_rows',[]);m['M11']=rate(sum(isinstance(x,dict) and (x.get('customer_id'),x.get('month')) in expected_ids for x in rows),len(rows))
    elif task['scenario']=='graph':
        wanted={(k,x) for k in ('paper_ids','institutions','top_references') for x in expected.get(k,[])};provided=[(k,x) for k in ('paper_ids','institutions','top_references') for x in answer.get(k,[])];m['M11']=rate(sum(x in wanted for x in provided),len(provided))
    elif task['scenario']=='incident':
        fields=('root_service','top_cpu_metric','top_p90_metric','top_trace_service');m['M11']=rate(sum(checks.get(k,False) for k in fields),sum(k in answer for k in fields))
    if task['scenario']=='code_review':
        regs=answer.get('regressions',[]);truth={canonical(x) for x in expected['regressions']};m['M12']=rate(sum(canonical(r) in truth for r in regs),len(regs))
        clean={k for k,v in gold['normative']['case_outcomes'].items() if v['observed']==v['expected']};wrong=sum((x.get('check_id','')+'::'+x.get('case_id','')) in clean for x in regs if isinstance(x,dict));m['M35']=rate(wrong,len(clean))
        seen=set()
        for a in artifacts.values():
            if a['kind']=='observation' and a['input_versions']['source']==task['final_version'] and a['content'].get('operation')=='run_checks' and a['content'].get('ok'):
                seen.update(x['check'] for x in a['content']['data'].get('checks',[]))
        required={x['name'] for x in load(ROOT/f"protocol/{task['dataset']}_checks.json")['public_checks']};m['M36']=rate(len(seen&required),len(required))
    refs=submission.get('evidence',[]);refs=refs if isinstance(refs,list) else [];refs=[x for x in refs if isinstance(x,str)];_,missing=ancestors(refs,artifacts);m['M13']=rate(len(refs)-sum(x not in artifacts for x in refs),len(refs))
    m['M14']=rate(sum(x.get('support',False) for x in evaluation.get('claim_checks',[])),len(evaluation.get('claim_checks',[])),'no explicit evidence claims');m['M15']=rate(sum(support.values()),len(support))
    before=gold.get('before_answer',expected);changed={k for k in expected if not equal(before.get(k),expected[k],k)};stable=set(expected)-changed
    updates=[e for e in events if e['kind']=='environment_update'];m['M16']=rate(sum(support.values()),len(support));m['M16']['note']='Semantic evidence applicability includes stable fields supported by older observations.'
    if task.get('update'):
        m['M17']=rate(sum(checks.get(k,False) for k in changed),len(changed),'no semantic field change');m['M18']=rate(sum(checks.get(k,False) for k in stable),len(stable));m['M19']=rate(sum(equal(answer.get(k),before.get(k),k) and not checks.get(k) for k in changed),len(changed))
        if updates:
            after=Counter()
            for e in events:
                if e['monotonic_start']>=updates[0]['monotonic_end']:after.update(e['resource_delta'])
            m['M20']=datum(dict(after),'resource vector');decision=next((e for e in events if e['kind']=='manager_decision_started' and e['monotonic_start']>=updates[0]['monotonic_end']),None)
            m['M22']=datum(decision['monotonic_start']-updates[0]['monotonic_end'],'seconds') if decision else needs('No later manager decision recorded')
        else:m['M20']=needs('Update trigger was not exposed');m['M22']=needs('Update trigger was not exposed')
    m['M21']=rate(sum(checks.values()),len(checks));m['M21']['operationalization']='Discovered requested field completion; explicit novel-entity creation reported in plan trace.'
    started=[e for e in events if e['kind']=='worker_started'];finished=[e for e in events if e['kind']=='worker_finished'];m['M23']=datum({'dispatched':len(started),'completed':len(finished),'rejected':sum(e['kind']=='action_rejected' for e in events)},'events')
    revisions=[e for e in events if e['kind']=='plan_revision']
    if revisions:
        event_time={e['event_id']:e['monotonic_end'] for e in events};prior_hits=set()
        for art in artifacts.values():
            if art['kind']=='worker_result' and event_time.get(art['producer_event_id'],float('inf'))<revisions[0]['monotonic_start']:
                val=art['content'];val=val.get('answer',val) if isinstance(val,dict) else {};prior_hits|=atomic_hits(expected,val)
        m['M24']=datum({'revision_events':len(revisions),'before_first_revision_satisfied':len(prior_hits),'newly_satisfied_by_final':len(hit-prior_hits),'previously_correct_lost':len(prior_hits-hit),'final_satisfied_fields':sum(checks.values()),'causal_effect':'descriptive transition; identify effect only using matched revision-policy comparisons'},'obligation transitions')
    if task['scenario']=='incident':m['M25']=datum({k:checks.get(k) for k in ('root_service','fault_type')},'boolean vector')
    if task['scenario']=='analytics':m['M26']=rate(sum(checks.values()),len(checks))
    contributions=[]
    for a in artifacts.values():
        c=a.get('content',{})
        if a['kind']=='observation' and isinstance(c,dict) and isinstance(c.get('data'),dict):
            d=c['data'];cols=d.get('columns',[])
            if 'loan_id' in cols and any(x in cols for x in ('amount','status')):contributions.append([r[cols.index('loan_id')] for r in d['rows']])
    if contributions:m['M27']=rate(sum(len(c)-len(set(c)) for c in contributions),sum(len(set(c)) for c in contributions));m['M27']['note']='Within-result-page fact multiplicity lower bound. Repeating a query is domain work, not join multiplication. Aggregate-only queries without row witnesses are not diagnosed by this counter.'
    seed=gold.get('seeded_claim')
    if seed:
        correct=gold.get('target_claim_correct',{k:gold['answer'][k] for k in seed if k in gold['answer']})
        if correct and equal(seed,correct,'seeded_claim'):seed=None
    exposed=any(a['kind']=='handoff' and seed and contains(a['content'],seed) for a in artifacts.values())
    if seed and exposed:
        adopted=contains(answer,seed);m['M28']=rate(int(adopted),1);correct=all(checks.get(k,False) for k in gold.get('target_fields',[])) if gold.get('target_fields') else checks.get('regressions',False);m['M29']=rate(int(correct and not adopted),1)
        propagated=[]
        for aid,a in artifacts.items():
            if a['kind']=='worker_result' and contains(a['content'],seed):
                found,_=ancestors(a.get('input_refs',[]),artifacts);observed_roots,declared=roots(aid,artifacts);relevant=[]
                for oid,ob in found.items():
                    if ob['kind']!='observation' or not ob['content'].get('ok'):continue
                    c=ob['content'];op=c.get('operation');d=c.get('data',{})
                    if 'case_id' in seed:
                        if op=='run_checks' and any(ch['check']==seed.get('check_id') and any(case['case_id']==seed['case_id'] for case in ch.get('observations',[])) for ch in d.get('checks',[])):relevant.append(oid)
                        if op in ('read_file','read_probe_inputs') and d.get('path')=='REGISTERED_CHECKS.py' and seed['case_id'] in '\n'.join(d.get('lines',[])):relevant.append(oid)
                    elif 'root_service' in seed and op in ('metric_summary','trace_summary','trace_relations'):
                        if seed['root_service'] in dump(d):relevant.append(oid)
                inherited=any(contains(ob['content'],seed) for ob in found.values() if ob['kind'] in ('handoff','worker_result'))
                propagated.append({'artifact_id':aid,'has_same_claim_ancestor':inherited,'without_new_relevant_observation':not relevant,'new_relevant_observations':relevant,'declared_roots':sorted(declared)})
        m['M30']=rate(sum(x['has_same_claim_ancestor'] and x['without_new_relevant_observation'] for x in propagated),len(propagated));m['M30']['paths']=propagated;m['M30']['note']='Claim-specific direct-check opportunities; unrelated new reads do not break the propagation chain. A relevant observation can still be misinterpreted.'
    observed_roots=set();declared_roots=set()
    for aid in refs:
        a,b=roots(aid,artifacts);observed_roots|=a;declared_roots|=b
    m['M31']=datum({'observed_record_version_classes':len(observed_roots),'declared_source_classes':len(declared_roots),'agent_independence':'not inferred','model_independence':'not inferred','statistical_source_independence':'not inferred'},'classes')
    claims=submission.get('claims',[]);claims=claims if isinstance(claims,list) else [];assertions=[x for x in claims if isinstance(x,dict) and x.get('independent_confirmation')]
    if assertions:
        bad=unknown=0
        for x in assertions:
            provenance=[roots(a,artifacts) for a in x.get('evidence',[])];sets=[r[0] for r in provenance];declared=[r[1] for r in provenance]
            if len(declared)>1 and all(declared) and len(set(map(lambda s:canonical(sorted(s)),declared)))<len(declared):bad+=1
            elif any(not s for s in sets):unknown+=1
            elif len(set(map(lambda s:canonical(sorted(s)),sets)))<len(sets):bad+=1
        m['M32']=rate(bad,len(assertions)-unknown);m['M32']['unknown_provenance']=unknown
    unsupported=set(gold.get('unsupported_fields',[]));m['M33']=rate(sum(answer.get(k) not in (None,'unsupported') for k in unsupported),sum(k in answer for k in expected));supported=set(expected)-unsupported;m['M34']=rate(sum(checks.get(k,False) for k in supported),len(supported))
    native=evaluation.get('native')
    if native:
        m['M37']=datum({'native_success':native.get('native_success'),'exact_state_success':native.get('success'),'added_records':native.get('added_request_count'),'required_records':native.get('expected_request_count')},'state')
        m['M38']=datum(native.get('collateral_change_count',native.get('protected_request_changes',0)),'protected record changes')
        if native.get('added_requests'):
            checks_native=native.get('additional_contract_checks',{});m['M11']=datum({'recipient_binding_correct':checks_native.get('exact_recipients'),'amount_binding_correct':checks_native.get('amounts_to_cent'),'record_count':len(native['added_requests'])},'native state bindings')
    uncertain=[a for a in artifacts.values() if a['kind']=='observation' and isinstance(a['content'].get('data'),dict) and a['content']['data'].get('withheld')]
    if uncertain:
        reconciled=0
        for a in uncertain:
            at=next(e['monotonic_end'] for e in events if e['event_id']==a['producer_event_id']);later=[x for x in artifacts.values() if x['kind']=='observation' and next((e['monotonic_start'] for e in events if e['event_id']==x['producer_event_id']),-1)>at]
            reads=[x for x in later if x['content'].get('operation')=='app_call' and x['content']['arguments'].get('api')=='show_sent_payment_requests' and x['content'].get('ok')]
            business=native.get('additional_contract_checks',{}) if native else {}
            reconciled+=int(bool(reads) and bool(business) and all(business.values()))
        m['M39']=rate(reconciled,len(uncertain));m['M39']['note']='Requires observed state read and exact final state; duplicate writes fail exactness.'
    faults=[e for e in events if e['kind']=='tool_completed' and e['status']=='TOOL_ERROR'];injected=task['conditions'].get('first_read_fault') or task['conditions'].get('fault') in ('fail_before','second_write_fails','lost_after')
    if injected:
        exposed=bool(uncertain) or any(a['kind']=='observation' and (
            'TRANSIENT_WRITE_FAILURE:' in str(a['content'].get('data',{}).get('detail','')) or
            'RECOVERABLE_READ_FAILURE:' in str(a['content'].get('data',{}).get('detail',''))
        ) for a in artifacts.values() if a['kind']=='observation' and isinstance(a['content'],dict) and isinstance(a['content'].get('data'),dict))
        m['M40']=rate(int(evaluation['success']) if exposed else 0,int(exposed),'injected fault was never exposed')
        m['M40']['native_completion_after_exposure']=rate(int(bool(native and native.get('success'))) if exposed else 0,int(exposed),'injected fault was never exposed') if task['scenario']=='appworld' else None
        business=native.get('additional_contract_checks',{}) if native else {}
        m['M40']['business_state_after_exposure']=rate(int(bool(business) and all(business.values())) if exposed else 0,int(exposed),'injected fault was never exposed') if task['scenario']=='appworld' else None
        m['M40']['note']='Primary numerator remains full contract success. Native completion and business-state recovery are separately named; generic tool errors never establish fault exposure.' 
    work=Counter()
    for e in events:work.update(e['resource_delta'])
    m['M41']=datum(dict(work),'native resource vector');m['M42']=datum(dict(Counter(x.get('role','unknown')+'::'+x.get('status','UNKNOWN') for x in requests)),'physical attempts')
    settled=sum(x.get('cost_usd',0) or 0 for x in requests if x.get('status')=='SETTLED');held=sum(x.get('reserved_usd',0) or 0 for x in requests if x.get('status')!='SETTLED')
    m['M43']=datum({'settled_usd':settled,'unknown_reservations_usd':held,'usage':[x.get('usage') for x in requests],'source':'provider receipts; unknown is retained'},'USD and tokens')
    spans={k:[] for k in ('manager_model','worker_model','tools')}
    for e in events:
        k='tools' if e['kind']=='tool_completed' else 'manager_model' if e['kind']=='model_completed' and e['actor_role']=='manager' else 'worker_model' if e['kind']=='model_completed' else None
        if k:spans[k].append((e['monotonic_start'],e['monotonic_end']))
    allspans=sum(spans.values(),[]);end=max((e['monotonic_end'] for e in events),default=0);active=union_seconds(allspans)
    running={};path_by_finish={};critical=0
    for e in events:
        if e['kind']=='worker_started':running[e['task_id']]=e
        if e['kind']=='worker_finished' and e['task_id'] in running:
            start=running.pop(e['task_id']);prior=[]
            for aid in start.get('dependency_artifacts',[]):
                if aid in artifacts:prior.append(path_by_finish.get(artifacts[aid]['producer_event_id'],0))
            length=e['monotonic_end']-start['monotonic_start']+max(prior,default=0);path_by_finish[e['event_id']]=length;critical=max(critical,length)
    m['M44']=datum({**{k+'_union_seconds':union_seconds(v) for k,v in spans.items()},'active_union_seconds':active,'end_to_end_seconds':end,'unattributed_orchestration_and_wait_seconds':max(0,end-active),'summed_tool_seconds':sum(b-a for a,b in spans['tools']),'parallel_overlap_seconds':sum(b-a for a,b in spans['tools'])-union_seconds(spans['tools']),'worker_dependency_critical_path_seconds':critical,'critical_path_scope':'Observed worker invocations and explicit data dependencies; manager and resource queues reported separately','local_thread_cpu_seconds':sum(e.get('cpu_seconds',0) for e in events),'remote_llm_compute_seconds':None,'timing_track':task.get('timing_track','native')},'seconds')
    m['M45']=na('Computed by compare on matched episode pairs');m['M46']=na('Computed by compare on matched episode pairs');m['M47']=na('Computed by reliability over repeats');m['M48']=datum({'final_status':evaluation['status'],'parser_valid':evaluation['parser_valid'],'tool_failures':len(faults),'deadline_met':evaluation.get('deadline_met')},'status')
    return {x['id']:{'name':x['name'],**m[x['id']]} for x in schema}
def compare(reference,candidate):
    r=load(Path(reference)/'evaluation.json');c=load(Path(candidate)/'evaluation.json');rm=load(Path(reference)/'metrics.json');cm=load(Path(candidate)/'metrics.json');valid=r['success'] and c['success']
    rs=load(Path(reference)/'summary.json');cs=load(Path(candidate)/'summary.json');rtask=load(ROOT/f"tasks/{rs['task_id']}.json");ctask=load(ROOT/f"tasks/{cs['task_id']}.json")
    if rtask['scenario']!=ctask['scenario'] or rtask['parent']!=ctask['parent'] or not equal(load(ROOT/f"private/{rs['task_id']}.json")['answer'],load(ROOT/f"private/{cs['task_id']}.json")['answer']):raise ValueError('Unmatched task world or answer contract')
    rw=rm['M41']['value'];cw=cm['M41']['value'];rt=rm['M44']['value']['end_to_end_seconds'];ct=cm['M44']['value']['end_to_end_seconds']
    return {'reference_quality':r['success'],'candidate_quality':c['success'],'joint_valid_n':int(valid),'attempted_pairs':1,'work_saving':{k:(rw[k]-cw.get(k,0))/rw[k] if valid and rw[k]>0 else None for k in rw},'latency_saving':(rt-ct)/rt if valid and rt>0 else None,'search_edit_cost':'Separately charge the controller budget; never deduct it from native work saving implicitly.'}
def reliability(successes,n,k):
    if not 0<=successes<=n or k<1:raise ValueError('invalid repeat counts')
    return {'successes':successes,'trials':n,'k':k,'pass_power_k':math.comb(successes,k)/math.comb(n,k) if n>=k else None}
