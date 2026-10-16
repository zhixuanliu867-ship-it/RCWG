"""Recompute existing native/control/model traces with the final judge, without paid calls."""
import copy,uuid
from common import *
from acceptance import read_episode,equivalent
from evaluator import evaluate
from metrics import summarize
from runtime import Runtime
def main():
    rows=[];schema=load(ROOT/'dataset_catalog.json')['tasks']
    for row in schema:
        tid=row['id'];eid='ACCEPT_FINAL_'+tid;task=load(ROOT/f'tasks/{tid}.json');s,a,e,n=read_episode(eid);ev=evaluate(task,s,a,e,n)
        cases={'correct':ev['success'],'equivalent':evaluate(task,equivalent(s),a,e,n)['success']}
        wrong=copy.deepcopy(s);wrong['claims']=[];wrong['answer'][next(iter(wrong['answer']))]='DELIBERATELY_WRONG'
        cases['wrong_rejected']=not evaluate(task,wrong,a,e,{**n,'success':False} if n else None)['success']
        none=copy.deepcopy(s);none['evidence']=[];none['claims']=[];cases['ungrounded_rejected']=not evaluate(task,none,a,e,n)['success']
        unknown=copy.deepcopy(s);unknown['claims'].append({'field':'new_claim','value':'unregistered','evidence':s['evidence']});cases['unregistered_adjudication']=evaluate(task,unknown,a,e,n)['status']=='ADJUDICATION_NEEDED'
        if task['scenario']=='code_review':
            alternate=copy.deepcopy(s);alternate['claims']=[];alternate['answer']['impacted_entrypoints']=['itsdangerous.TimestampSigner.validate','itsdangerous.TimedSerializer.loads','itsdangerous.URLSafeTimedSerializer.loads'] if task['dataset']=='itsdangerous' else ['requests.Session.resolve_redirects','requests.PreparedRequest.prepare_cookies'];cases['public_symbol_impact_accepted']=evaluate(task,alternate,a,e,n)['success']
        write(ROOT/f'recomputed/{eid}.json',ev);write(ROOT/f'recomputed/{eid}_metrics.json',summarize(task,ev,a,e,[],s));rows.append({'task':tid,'episode':eid,'pass':all(cases.values()),'checks':cases})
    model=[]
    for p in sorted((ROOT/'runs').glob('LIVE*')):
        if not (p/'summary.json').exists():continue
        old=load(p/'summary.json');eid=p.name;s,a,e,n=read_episode(eid) if (p/'final_submission.json').exists() else (None,{},[],None);task=load(ROOT/f"tasks/{old['task_id']}.json")
        expression_recovered=False
        if s is None and (p/'submitted_expression.json').exists():
            # The original run aborted on an otherwise unambiguous projection.
            # This is a retrospective parser repair, never a new model run.
            events=[json.loads(x) for x in (p/'execution_events.jsonl').read_text(encoding='utf-8').splitlines()];arts={x['artifact_id']:x for x in [json.loads(z) for z in (p/'artifacts.jsonl').read_text(encoding='utf-8').splitlines()]}
            rt=Runtime(old['task_id'],'PROJECTION_REPLAY_'+eid+'_'+uuid.uuid4().hex[:6]);rt.artifacts=arts
            try:rt.submit(load(p/'submitted_expression.json'));s=rt.final;a=arts;e=events;expression_recovered=True
            finally:rt.close()
        ev=evaluate(task,s,a,e,n);write(ROOT/f'recomputed/{eid}.json',ev)
        model.append({'episode':eid,'task':old['task_id'],'original_status':old['status'],'original_success':old['evaluation']['success'],'final_judge_success':ev['success'],'final_judge_status':ev['status'],'factual_correct':ev['factual_correct'],'field_checks':ev['field_checks'],'evidence_valid':ev['evidence_valid'],'projection_recovered_without_model_call':expression_recovered,'model_calls':old['model_calls']})
    write(ROOT/'qa/final_contract_recheck.json',{'task_count':len(rows),'passed_tasks':sum(x['pass'] for x in rows),'check_count':sum(len(x['checks']) for x in rows),'passed_checks':sum(sum(x['checks'].values()) for x in rows),'records':rows,'judge_hash':sha(ROOT/'src/evaluator.py')});write(ROOT/'qa/final_model_recheck.json',{'records':model,'paid_calls':0,'method':'Original immutable observations; final alias/projection/task-semantic judge. Original judgments retained.'})
    print(dump({'tasks':len(rows),'passed':sum(x['pass'] for x in rows),'model_records':len(model),'failures':[x['task'] for x in rows if not x['pass']]}))
    if not all(x['pass'] for x in rows):raise SystemExit(1)
if __name__=='__main__':main()
