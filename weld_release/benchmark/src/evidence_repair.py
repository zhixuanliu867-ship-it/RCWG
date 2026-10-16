"""Separate, source-attested review of two over-strict frozen evidence rules.

No model calls, changed trial inputs, new model observations, or overwritten scores.
Only publisher-supplied native observations / financial partial reports qualify.
Unverified opinions, wrong answers, missing scope, and unknown claims do not pass.
"""
import sys,copy,sqlite3,collections,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from common import *
from evaluator import evaluate_core as evaluate,ancestors

def jl(p):return [json.loads(x) for x in p.read_text(encoding='utf8').splitlines() if x] if p.exists() else []

def certified(task,arts,events):
    view=load(R/f"agent_views/{task['public_id']}.json");published={dump(x) for x in view.get('handoffs',[])};eids={e['event_id']:e for e in events};gold=load(R/f"private/{task['id']}.json");valid={};aliases={}
    for aid,a in arts.items():
        if a['kind']!='handoff':continue
        h=a['content'];event=eids.get(a['producer_event_id'],{})
        if dump(h) not in published or event.get('kind')!='handoff_exposed' or event.get('actor_role')!='environment':continue
        if hashlib.sha256(dump(h).encode()).hexdigest()!=a['content_hash']:continue
        alias=h.get('artifact_id')
        if alias and alias not in arts:aliases.setdefault(alias,[]).append(aid)
        if h.get('kind')=='native_test_observations' and task['scenario']=='code_review':
            # Independently executed native gate observations, not just oracle text.
            gate=Path(config()['round1_root'])/'runs'/('R1_GATE_'+task['id']);actual={}
            for g in jl(gate/'artifacts.jsonl'):
                c=g['content']
                if g['kind']=='observation' and c.get('operation')=='run_checks' and c.get('ok'):
                    for check in c['data'].get('checks',[]):
                        for case in check.get('observations',[]):actual[(g['input_versions']['source'],check['check'],case['case_id'])]=case['observed_outcome']
            rows=h.get('observations',[])
            if rows and all(actual.get((x['input_version'],x['check_id'],x['case_id']))==x['observed'] and x['input_version']==task['final_version'] for x in rows):valid[aid]={'kind':'native_test_observations','cases':{(x['check_id'],x['case_id'],x['input_version']):x['observed'] for x in rows}}
        elif h.get('kind')=='portfolio_partial' and task['dataset']=='financial' and h.get('input_version')==task['final_version']:
            ids=h.get('covered_loan_ids',[])
            if not ids or len(set(ids))!=len(ids):continue
            con=sqlite3.connect('file:'+str(R/'assets/financial.sqlite').replace('\\','/')+'?mode=ro',uri=True)
            query='SELECT d.A3,COUNT(*),SUM(l.amount),SUM(CASE WHEN l.status IN (\'B\',\'D\') THEN 1 ELSE 0 END) FROM loan l JOIN account a ON a.account_id=l.account_id JOIN district d ON d.district_id=a.district_id WHERE l.loan_id IN ('+','.join('?' for _ in ids)+') GROUP BY d.A3 ORDER BY d.A3'
            rows=[list(x) for x in con.execute(query,ids)];count=con.execute('SELECT COUNT(*) FROM loan WHERE loan_id IN ('+','.join('?' for _ in ids)+')',ids).fetchone()[0];con.close()
            if count==len(ids) and equal(h.get('regional'),rows,'regional'):valid[aid]={'kind':'financial_partial','ids':ids,'regional':h['regional']}
    return valid,{k:v[0] for k,v in aliases.items() if len(v)==1}

def review(task,submission,arts,events,native):
    frozen=evaluate(task,copy.deepcopy(submission),arts,events,native)
    if not isinstance(submission,dict):return {'reviewed_success':frozen['success'],'changed':False,'reason':'No structured submission'}
    certificates,aliases=certified(task,arts,events);s=copy.deepcopy(submission)
    def refs(xs):return [aliases.get(x,x) for x in xs] if isinstance(xs,list) else []
    s['evidence']=refs(s.get('evidence',[]))
    for c in s.get('claims',[]) if isinstance(s.get('claims'),list) else []:
        if isinstance(c,dict):c['evidence']=refs(c.get('evidence',[]))
    ev=evaluate(task,s,arts,events,native);answer=ev.get('answer',{});allrefs=s['evidence']+[r for c in s.get('claims',[]) if isinstance(c,dict) for r in c.get('evidence',[])];context,_=ancestors(allrefs,arts)
    context_read=any(a['kind']=='observation' and a['content'].get('operation')=='read_file' and a['content'].get('ok') and a['content']['data'].get('path')=='REVIEW_CONTEXT.md' for a in context.values())
    def supports(field,ids):
        found,missing=ancestors(ids,arts)
        if missing:return False
        certs=[certificates[x] for x in found if x in certificates]
        if task['scenario']=='code_review' and field in ('regressions','verdict') and context_read:
            cases={k:v for c in certs if c['kind']=='native_test_observations' for k,v in c['cases'].items()};regs=answer.get('regressions',[])
            return bool(cases) and ev['field_checks'].get('regressions',False) and all(cases.get((x.get('check_id'),x.get('case_id'),x.get('input_version')))==x.get('observed') for x in regs)
        if task['dataset']=='financial' and field in ('loan_ids','regional','total_amount'):
            cs=[c for c in certs if c['kind']=='financial_partial'];ids=[i for c in cs for i in c['ids']]
            if not cs or len(set(ids))!=len(ids):return False
            regional=collections.defaultdict(lambda:[0,0,0])
            for c in cs:
                for region,n,amount,adverse in c['regional']:
                    regional[region][0]+=n;regional[region][1]+=amount;regional[region][2]+=adverse
            derived={'loan_ids':sorted(ids),'regional':[[k,*v] for k,v in sorted(regional.items())],'total_amount':sum(v[1] for v in regional.values())}
            return equal(answer.get(field),derived[field],field)
        return False
    support={k:old or supports(k,allrefs) for k,old in ev.get('support_checks',{}).items()};claimchecks=copy.deepcopy(ev.get('claim_checks',[]));structured=[x for x in s.get('claims',[]) if isinstance(x,dict)]
    for c,raw in zip(claimchecks,structured):
        if c.get('status')=='JUDGED' and c.get('factual') is True and not c.get('support'):c['support']=supports(c['field'],raw.get('evidence',[]))
    pending=ev['status']=='ADJUDICATION_NEEDED';contradiction=any(x.get('factual') is False or x.get('support') is False for x in claimchecks)
    # The inherited public REVIEW_SUBMISSION.md separately requires one current
    # registered execution. Trusted handoffs may support other cases, not waive it.
    minimum_execution=True
    if task['scenario']=='code_review':
        path=R/'assets'/task['dataset']/({'r0':'v0','r1':'v1','r2':'fixed'}[task['final_version']])/'REVIEW_SUBMISSION.md'
        requires=path.exists() and 'at least one registered check against the final revision' in path.read_text(encoding='utf8')
        if requires:minimum_execution=any(a['kind']=='observation' and a['input_versions'].get('source')==task['final_version'] and a['content'].get('operation')=='run_checks' and a['content'].get('ok') and any(check.get('observations') for check in a['content'].get('data',{}).get('checks',[])) for a in arts.values())
    result=bool(ev.get('factual_correct') and support and all(support.values()) and not ev.get('missing_evidence') and not contradiction and not pending and minimum_execution)
    return {'base_evaluation':ev,'normalized_submission':s,'frozen_success':frozen['success'],'reviewed_success':result,'changed':result!=frozen['success'],'aliases_resolved':{k:v for k,v in aliases.items() if k in dump(submission)},'certified_handoff_ids':list(certificates),'support_checks':support,'minimum_current_execution_satisfied':minimum_execution,'claim_checks':claimchecks,'factual_checks_unchanged':True,'review_scope':'Publisher handoff authentication, explicit published-ID aliases, native execution attestation and financial aggregate recomposition only. Preserve the public minimum-current-execution requirement. Wrong factual answers, unverified memos, and unresolved extra claims remain unaccepted.'}

def main():
    p=load(R/'protocol/round1.json');rows=[];(R/'reviewed').mkdir(exist_ok=True)
    for job in p['jobs']:
        d=R/'runs'/job['episode']
        if not (d/'summary.json').exists():continue
        task=load(R/f"tasks/{job['task']}.json");arts={a['artifact_id']:a for a in jl(d/'artifacts.jsonl')};s=load(d/'final_submission.json') if (d/'final_submission.json').exists() else None;native=load(d/'native_evaluation.json') if (d/'native_evaluation.json').exists() else None
        result=review(task,s,arts,jl(d/'execution_events.jsonl'),native);write(R/f"reviewed/{job['episode']}.json",result);rows.append({**job,**result})
    write(R/'analysis/handoff_review.json',{'policy_version':'SOURCE_ATTESTED_HANDOFF_REVIEW_2','reviewer':'deterministic source-attestation rules; no LLM grader','paid_calls':0,'amendment':'Preserve the inherited public submission document requirement of at least one registered current-version execution; v1 interim snapshot retained.','rows':rows});print(dump({'reviewed':len(rows),'changed':[x['episode'] for x in rows if x['changed']]}))

if __name__=='__main__':main()
