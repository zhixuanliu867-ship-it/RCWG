"""Full native calibration plus discriminating negative and runtime controls."""
import copy,time,threading,traceback,uuid
from common import *
from runtime import Runtime
from references import run
from evaluator import evaluate
from metrics import roots,compare,reliability
def read_episode(eid):
    p=ROOT/'runs'/eid
    events=[json.loads(x) for x in (p/'execution_events.jsonl').read_text(encoding='utf-8').splitlines()]
    arts={x['artifact_id']:x for x in [json.loads(z) for z in (p/'artifacts.jsonl').read_text(encoding='utf-8').splitlines()]}
    return load(p/'final_submission.json'),arts,events,load(p/'native_evaluation.json')
def equivalent(s):
    s=copy.deepcopy(s)
    for k,v in s['answer'].items():
        if isinstance(v,list):s['answer'][k]=list(reversed(v))
    if 'regressions' in s['answer']:
        regs=s['answer'].pop('regressions');s['findings']=[{'cases':regs[:len(regs)//2]},{'cases':regs[len(regs)//2:]}]
    return s
def contracts(prefix,only=None):
    records=[];catalog=load(ROOT/'dataset_catalog.json')['tasks']
    for row in catalog:
        tid=row['id']
        if only and tid not in only:continue
        eid=prefix+'_'+tid;t=load(ROOT/f'tasks/{tid}.json')
        try:
            ev=load(ROOT/f'runs/{eid}/evaluation.json') if (ROOT/f'runs/{eid}/evaluation.json').exists() else run(tid,eid)
            s,a,e,n=read_episode(eid);checks=[]
            def check(name,value,detail=None):checks.append({'name':name,'pass':bool(value),'detail':detail})
            check('native_correct_control',ev['success'],{k:ev.get(k) for k in ('field_checks','support_checks','status')})
            alt=evaluate(t,equivalent(s),a,e,n);check('order_grouping_equivalent',alt['success'])
            wrong=copy.deepcopy(s);field=next(iter(wrong['answer']));wrong['answer'][field]='DELIBERATELY_WRONG';wrong['claims']=[]
            check('targeted_wrong_answer_rejected',not evaluate(t,wrong,a,e,{**n,'success':False} if t['scenario']=='appworld' else n)['success'])
            missing=copy.deepcopy(s);missing['evidence']=['nonexistent'];missing['claims']=[]
            check('missing_evidence_rejected',not evaluate(t,missing,a,e,n)['success'])
            only_handoff=copy.deepcopy(s);only_handoff['evidence']=[k for k,v in a.items() if v['kind']=='handoff'];only_handoff['claims']=[]
            check('handoff_opinion_not_native_evidence',not evaluate(t,only_handoff,a,e,n)['success'])
            unknown=copy.deepcopy(s);unknown['claims'].append({'field':'novel_causal_explanation','value':'plausible but unregistered','evidence':s['evidence']})
            check('unregistered_claim_requires_adjudication',evaluate(t,unknown,a,e,n)['status']=='ADJUDICATION_NEEDED')
            if t['conditions'].get('first_read_fault'):check('fault_actually_exposed',any(x['status']=='TOOL_ERROR' for x in e))
            if t.get('update'):check('semantic_update_triggered',any(x['kind']=='environment_update' and x.get('exposure_event') for x in e))
            if t['conditions'].get('fault')=='lost_after':check('uncertain_commit_hidden_but_retained',any(x.get('content',{}).get('data',{}).get('withheld') for x in a.values() if isinstance(x.get('content',{}).get('data'),dict)))
            if t['conditions'].get('fault')=='stale_two_readers':check('deterministic_interleaving_executed',any(x['kind']=='interleaving_checkpoint' for x in e))
            records.append({'task':tid,'episode':eid,'pass':all(x['pass'] for x in checks),'checks':checks})
        except Exception as ex:records.append({'task':tid,'episode':eid,'pass':False,'error':type(ex).__name__+': '+str(ex),'traceback':traceback.format_exc()})
        print(tid,records[-1]['pass'],flush=True);write(ROOT/f'qa/{prefix}_contracts.json',{'records':records,'task_count':len(records),'passed_tasks':sum(x['pass'] for x in records),'check_count':sum(len(x.get('checks',[])) for x in records),'failed_checks':[{'task':x['task'],'check':c['name']} for x in records for c in x.get('checks',[]) if not c['pass']]})
    return records
def runtime_controls(prefix):
    records=[]
    def check(name,test,detail=None):records.append({'name':name,'pass':bool(test),'detail':detail})
    rt=Runtime('H_G__free',prefix+'_runtime');rt.seed_handoffs()
    try:
        check('initial_graph',rt.edit([{'id':'a','scope':'Discover first node','dependencies':[]},{'id':'b','scope':'Use discovery','dependencies':['a']}])['ok'])
        check('dependency_reject_visible',not rt.dispatch(['b'],lambda r,t:{'result':{}})['completed'] and bool(rt.view()['feedback']))
        check('cycle_rejected_atomically',not rt.edit([{'id':'a','scope':'bad cycle','add_dependencies':['b']}])['ok'] and not rt.tasks['a']['dependencies'])
        def worker(r,t):
            time.sleep(.02);out=r.tool('worker:'+t['id'],'nodes',{'ids':[28651]});return {'result':{'node_observed':out['data']['rows'][0]['id']},'evidence':[out['artifact_id']]}
        rt.dispatch(['a','b'],worker)
        e=rt.events;enda=next(x['monotonic_end'] for x in e if x['kind']=='worker_finished' and x['task_id']=='a');startb=next(x['monotonic_start'] for x in e if x['kind']=='worker_started' and x['task_id']=='b');check('actual_dependency_wait',startb>=enda)
        newnode=rt.artifacts[rt.results['a']]['content']['node_observed'];check('novel_task_after_observation',rt.edit([{'id':'novel_'+str(newnode),'scope':{'discovered_node':newnode},'dependencies':['a']}])['ok'])
        check('remove_dependency',rt.edit([{'id':'b','scope':'independent followup','remove_dependencies':['a']}])['ok'] and not rt.tasks['b']['dependencies'])
        check('cancel_and_redispatch',rt.edit([{'id':'b','scope':'cancel','cancel':True}])['ok'] and not rt.dispatch(['b'],worker)['completed'])
        check('oversized_graph_input_rejected',not rt.tool('worker:a','nodes',{'ids':list(range(101))})['ok'])
        check('initial_and_revision_and_execution_separate',all((rt.out/f).exists() for f in ('initial_plan.json','plan_revisions.jsonl','execution_events.jsonl')))
        old=rt.results['a'];oldhash=rt.artifacts[old]['content_hash'];rt.edit([{'id':'a','scope':'repeat valid evidence','dependencies':[]}]);rt.dispatch(['a'],worker);check('new_artifact_preserves_old',old!=rt.results['a'] and rt.artifacts[old]['content_hash']==oldhash)
        parent=rt.results['a'];copies=[]
        for i in range(3):
            ev=rt.event('fixture_copy');copies.append(rt.artifact(ev,{'assertion':'same source'},[parent],kind='worker_result'))
        check('three_copies_one_provenance',len(set(canonical(sorted(roots(a,rt.artifacts)[0])) for a in copies))==1)
    finally:rt.close()
    fixed=Runtime('H_G__free',prefix+'_fixed',mode='fixed')
    try:fixed.edit([{'id':'a','scope':'initial','dependencies':[]}]);check('fixed_plan_arm_is_enforced',not fixed.edit([{'id':'b','scope':'later','dependencies':[]}])['ok'])
    finally:fixed.close()
    sql=Runtime('E_A__free',prefix+'_sql')
    try:
        result=sql.tool('worker:a','select',{'sql':'DELETE FROM customers'});last=next(e for e in reversed(sql.events) if e['kind']=='tool_completed')
        check('sql_write_rejected_and_counted',not result['ok'] and last['resource_delta'].get('failed_queries')==1)
        check('exact_identifiers',not equal(1673.001,1673,'customer_id'));check('numeric_tolerance',equal(30.009,30.0,'consumption') and not equal(30.011,30.0,'consumption'))
    finally:sql.close()
    check('overlap_interval_union',abs(union_seconds([(0,2),(1,3),(5,6)])-4)<1e-9)
    check('pass_k',reliability(3,4,2)['pass_power_k']==.5)
    write(ROOT/f'qa/{prefix}_runtime.json',{'passed':sum(x['pass'] for x in records),'total':len(records),'checks':records});return records
def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--prefix',default='ACCEPT_V1');p.add_argument('--only',nargs='*');p.add_argument('--runtime-only',action='store_true');a=p.parse_args()
    records=[] if a.runtime_only else contracts(a.prefix,a.only);checks=runtime_controls(a.prefix)
    print(dump({'passed_tasks':sum(x['pass'] for x in records),'tasks':len(records),'runtime_passed':sum(x['pass'] for x in checks),'runtime_total':len(checks)}))
    if any(not x['pass'] for x in records+checks):raise SystemExit(1)
if __name__=='__main__':main()
