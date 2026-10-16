"""Read-only replay of all scorable historical attempts under their original contract.
New-contract diagnostics are appended; saved results are never overwritten.
"""
import sys,copy,re,json
from common import ROOT,config,load,write,dump
from pathlib import Path
N=Path(config()['legacy_root']);sys.path.insert(0,str(N/'src'))
from current_evaluator import CurrentAdapter
def main():
    records=[];excluded=[]
    expected=load(N/'appworld_workspace/data/tasks/22cc237_1/ground_truth/private_data.json')['pending_user_id_to_share'];expected={str(k).removeprefix('{_INT_}:'):v for k,v in expected.items()}
    for p in sorted((N/'runs/episodes').iterdir()):
        if p.name.startswith('OFFLINE') or not (p/'summary.json').exists():continue
        s=load(p/'summary.json');old=s.get('evaluation')
        if old is None:excluded.append({'episode':p.name,'reason':'No scorable original evaluation; attempt retained','status':s.get('status')});continue
        evs=[json.loads(x) for x in (p/'execution.jsonl').read_text(encoding='utf-8').splitlines()];submission=load(p/'submission.json');current=None
        if s['parent']=='B3':
            rows=[]
            for line in (N/'appworld_workspace/experiments/outputs'/p.name/'tasks/22cc237_1/dbs/venmo.jsonl').read_text(encoding='utf-8').splitlines():
                sql,values,many=json.loads(line)
                if re.match(r'INSERT INTO payment_requests\s*\(',sql,re.I):
                    names=[x.strip() for x in sql.split('(',1)[1].split(')',1)[0].split(',')];rows.append(dict(zip(names,values)))
            ids=[str(x['receiver_id']) for x in rows];checks={'exact_request_multiplicity':len(rows)==len(expected) and len(set(ids))==len(rows),'exact_recipients':set(ids)==set(expected),'amounts_to_cent':all(str(x['receiver_id']) in expected and abs(x['amount']-expected[str(x['receiver_id'])])<.005 for x in rows),'required_description':all(x['description']=='Work Dinner' for x in rows)}
            current=copy.deepcopy(old);current['app']['additional_contract_checks']=checks;current['app']['success']=old['app']['native_success'] and all(checks.values());current['components']['native_plus_exact_state']=current['app']['success'];current['success']=all(current['components'].values())
            note='Native result retained; independent saved INSERT-log reconstruction verifies exact state without rerunning official world.'
        else:
            a=CurrentAdapter(s['parent'],s['condition'],'readonly_replay')
            try:
                if s['update_exposed'] and a.has_update:a.release()
                a.artifacts={x.stem:load(x) for x in (p/'artifacts').glob('*.json')};current=a.evaluate(submission,evs)
            finally:a.close()
            note='Re-executed the frozen task contract with semantic alias correction; no retroactive requirement added.'
        differences=[]
        def diff(x,y,path=''):
            if isinstance(x,dict) and isinstance(y,dict):
                for k in sorted(set(x)|set(y)):diff(x.get(k),y.get(k),path+'.'+k)
            elif x!=y:differences.append({'field':path,'old':x,'new':y})
        diff(old,current)
        d={'episode':p.name,'family':s['parent'],'old_success':old['success'],'recomputed_success':current['success'],'pass_changed':old['success']!=current['success'],'differences':differences,'note':note,'new_measurements':{'three_trace_files_present':all((p/f).exists() for f in ('initial_plan.json','plan_revisions.json','execution.jsonl')),'physical_attempts_require_provider_ledger':True,'fine_evidence_claim_alignment':'NOT_OBSERVED_IN_OLD_PROTOCOL; no fabricated backfill','version_reused':'Original native snapshot and original exposed update'}}
        records.append(d);write(ROOT/'replay'/f'{p.name}.json',{'comparison':d,'recomputed_evaluation':current})
    report={'scorable_attempts':len(records),'unscorable_attempts_retained':excluded,'pass_changes':sum(x['pass_changed'] for x in records),'records':records,'source_root':str(N),'paid_calls':0,'historical_contracts_preserved':True};write(ROOT/'qa/legacy_replay.json',report)
    print(dump({'scorable_attempts':len(records),'pass_changes':report['pass_changes'],'unscorable':len(excluded)}))
    if len(records)!=48:raise SystemExit('Expected 48 scorable attempts')
if __name__=='__main__':main()
