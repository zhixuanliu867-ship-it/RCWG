"""Targeted evidence and measurement controls beyond happy-path answer matching."""
import copy,json,hashlib
from common import *
from acceptance import read_episode
from evaluator import evaluate
from runtime import Runtime
from metrics import summarize,roots,compare
def main(prefix='DEEP_FINAL',base='ACCEPT_V2'):
    tests=[]
    def check(name,ok,detail=None):tests.append({'name':name,'pass':bool(ok),'detail':detail})
    tid='E_A__grouped';task=load(ROOT/f'tasks/{tid}.json');s,a,e,n=read_episode(base+'_'+tid)
    near=copy.deepcopy(s);near['claims']=[];near['answer']['monthly_rows'][0]['consumption']+=.009
    check('continuous_tolerance_preserves_correctness',evaluate(task,near,a,e,n)['success'])
    wrong=copy.deepcopy(s);wrong['answer']['monthly_rows'][0]['customer_id']=12459;wrong['claims']=[]
    check('wrong_object_rejected_despite_valid_link',not evaluate(task,wrong,a,e,n)['success'])
    stripped=copy.deepcopy(s)
    for c in stripped['claims']:c.pop('value',None)
    check('no_redundant_claim_value_required',evaluate(task,stripped,a,e,n)['success'])
    forged=copy.deepcopy(a);o=next(x for x in forged.values() if x['kind']=='observation');o['content']['operation']='unobserved_operation';o['content_hash']=hashlib.sha256(dump(o['content']).encode()).hexdigest()
    check('forged_event_binding_rejected',not evaluate(task,s,forged,e,n)['success'])
    regtask=load(ROOT/'tasks/E_C__grouped.json');cs,ca,ce,cn=read_episode(base+'_E_C__grouped');bad=copy.deepcopy(cs);bad['claims']=[];bad['answer']['regressions'][0]['input_version']='r0'
    check('same_case_wrong_snapshot_rejected',not evaluate(regtask,bad,ca,ce,cn)['success'])
    bad=copy.deepcopy(cs);bad['claims']=[];bad['answer']['regressions'][0]['expected']='cookie:session=example-cookie'
    check('observed_does_not_imply_normative_expected',not evaluate(regtask,bad,ca,ce,cn)['success'])
    clean=load(ROOT/'tasks/E_C__fixed_control.json');ss,aa,ee,nn=read_episode(base+'_E_C__fixed_control');bad=copy.deepcopy(ss);bad['claims']=[];bad['answer']['regressions']=cs['answer']['regressions'][:1]
    check('clean_snapshot_false_finding_rejected',not evaluate(clean,bad,aa,ee,nn)['success'])
    for v,changes in [('value_change',1),('object_change',2),('unrelated_change',0)]:
        t=load(ROOT/f'tasks/X02__{v}.json');ss,aa,ee,nn=read_episode(base+'_X02__'+v);ev=evaluate(t,ss,aa,ee,nn);m=summarize(t,ev,aa,ee,[],ss)
        check('semantic_change_count_'+v,m['M17']['denominator']==changes,{'changed':m['M17'],'stable':m['M18']})
    for v in ('correct_control','copied_error'):
        t=load(ROOT/f'tasks/P_I__{v}.json');ss,aa,ee,nn=read_episode(base+'_P_I__'+v);ev=evaluate(t,ss,aa,ee,nn);m=summarize(t,ev,aa,ee,[],ss)
        check('correct_consensus_not_error' if v=='correct_control' else 'seeded_wrong_exposure_measured',m['M28']['status']=='NOT_APPLICABLE' if v=='correct_control' else m['M28']['denominator']==1)
    rt=Runtime('E_A__free',prefix+'_projection')
    try:
        one=rt.tool('worker:fixture','select',{'sql':'SELECT CustomerID FROM customers ORDER BY CustomerID LIMIT 3'})
        rt.submit({'answer':{'ids':{'from_artifact':one['artifact_id'],'path':['data'],'column':'CustomerID'}},'evidence':[]})
        check('large_output_projection_materializes_observed_column',rt.final['answer']['ids']==[x[0] for x in one['data']['rows']] and one['artifact_id'] in rt.final['evidence'])
        check('private_path_cannot_be_projected','private' not in rt.artifacts)
    finally:rt.close()
    graph=compare(ROOT/f'runs/{base}_X01__separate',ROOT/f'runs/{base}_X01__shared')
    check('joint_valid_work_comparison',graph['joint_valid_n']==1 and graph['work_saving'].get('returned_records',0)>0,graph)
    # Deliberately invalid candidate remains in the quality ledger and gets no saving.
    ev=load(ROOT/f'runs/{base}_X10__verified_empty/evaluation.json');check('verified_empty_is_success',ev['success'])
    fx=load(ROOT/f'runs/{base}_X10__unfinished/metrics.json');check('failed_read_is_charged_and_recovered',fx['M41']['value'].get('failed_tools')==1 and fx['M40']['value']==1)
    import jsonschema
    eschema=load(ROOT/'protocol/events.schema.json');aschema=load(ROOT/'protocol/artifacts.schema.json');valid=True;checked=0
    for p in (ROOT/'runs').glob(base+'_*'):
        for name,schema in [('execution_events.jsonl',eschema),('artifacts.jsonl',aschema)]:
            for line in (p/name).read_text(encoding='utf-8').splitlines():
                try:jsonschema.validate(json.loads(line),schema);checked+=1
                except jsonschema.ValidationError:valid=False
    check('machine_readable_event_artifact_schemas',valid,{'records_checked':checked})
    views=[load(p) for p in (ROOT/'agent_views').glob('*.json')]
    check('condition_names_and_oracles_absent_from_agent_views',all(not any(k in v for k in ('condition','family','answer','private','seeded_claim')) for v in views))
    write(ROOT/'qa'/f'{prefix}.json',{'passed':sum(x['pass'] for x in tests),'total':len(tests),'checks':tests});print(dump({'passed':sum(x['pass'] for x in tests),'total':len(tests),'failures':[x['name'] for x in tests if not x['pass']]}))
    if not all(x['pass'] for x in tests):raise SystemExit(1)
if __name__=='__main__':
    import sys
    main(*(sys.argv[1:] or []))
