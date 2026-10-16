"""Offline release consistency checks. No provider requests and no model inference."""
import collections, hashlib, re
import jsonschema
from common import *

def lines(p):
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()] if p.exists() else []

def main():
    errors=[];counts=collections.Counter();cat=load(ROOT/'dataset_catalog.json')
    validators={n:jsonschema.Draft202012Validator(load(ROOT/f'protocol/{n}.schema.json')) for n in ('task','events','artifacts')}
    for row in cat['tasks']:
        task=load(ROOT/f"tasks/{row['id']}.json")
        for e in validators['task'].iter_errors(task):errors.append([row['id'],'task_schema',e.message])
        for p in [ROOT/f"private/{row['id']}.json",ROOT/f"agent_views/{task['public_id']}.json"]:
            if not p.exists():errors.append([row['id'],'missing',str(p)])
        counts['tasks']+=1
    episodes=[ROOT/f"runs/ACCEPT_FINAL_{x['id']}" for x in cat['tasks']]
    episodes += [ROOT/'runs'/x['episode'] for x in load(ROOT/'qa/final_model_recheck.json')['records']]
    for p in episodes:
        events=lines(p/'execution_events.jsonl');arts=lines(p/'artifacts.jsonl');eids={x['event_id'] for x in events};aids={x['artifact_id'] for x in arts}
        if len(eids)!=len(events) or len(aids)!=len(arts):errors.append([p.name,'duplicate_identity'])
        for e in events:
            counts['events']+=1
            for err in validators['events'].iter_errors(e):errors.append([p.name,e['event_id'],'event_schema',err.message])
            if e['monotonic_start']>e['monotonic_end']:errors.append([p.name,e['event_id'],'negative_duration'])
            for aid in e['input_artifacts']+e['output_artifacts']:
                if aid not in aids:errors.append([p.name,e['event_id'],'missing_artifact',aid])
        for a in arts:
            counts['artifacts']+=1
            for err in validators['artifacts'].iter_errors(a):errors.append([p.name,a['artifact_id'],'artifact_schema',err.message])
            if a['producer_event_id'] not in eids:errors.append([p.name,a['artifact_id'],'missing_producer'])
            if hashlib.sha256(dump(a['content']).encode()).hexdigest()!=a['content_hash']:errors.append([p.name,a['artifact_id'],'content_hash'])
            for aid in a['input_refs']:
                if aid not in aids:errors.append([p.name,a['artifact_id'],'missing_parent',aid])
        for name in ('initial_plan.json','plan_revisions.jsonl','execution_events.jsonl'):
            if not (p/name).exists():errors.append([p.name,'missing_trace',name])
        counts['episodes']+=1
    account=load(ROOT/'runs/api_accounting.json');ledger={x['id']:x for x in account['requests']};physical={}
    for row in load(ROOT/'qa/final_model_recheck.json')['records']:
        for req in lines(ROOT/'runs'/row['episode']/'physical_requests.jsonl'):
            rid=req['request_id']
            if rid in physical:errors.append([rid,'duplicate_physical_receipt'])
            physical[rid]=req
    if set(ledger)!=set(physical):errors.append(['ledger_receipt_identity_difference',sorted(set(ledger)^set(physical))])
    for rid,req in physical.items():
        if rid not in ledger:continue
        if abs((req.get('cost_usd') or 0)-(ledger[rid]['cost'] or 0)/1e9)>1e-9:errors.append([rid,'cost_mismatch'])
    receipts_cost=sum(x.get('cost_usd',0) or 0 for x in physical.values())
    if abs(receipts_cost-account['settled_cost_usd'])>1e-8:errors.append(['total_cost_mismatch'])
    counts['physical_requests']=len(physical)
    # Report only paths if any actual provider credential was accidentally copied.
    secret=re.compile(r'sk-or-v1-[A-Za-z0-9]{24,}')
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if not p.is_file() or rel.parts[0] in ('local_only','deliveries') or p.suffix.lower() not in ('.json','.jsonl','.py','.md','.txt'):continue
        if secret.search(p.read_text(encoding='utf-8',errors='ignore')):errors.append([rel.as_posix(),'credential_pattern'])
    result={'pass':not errors,'counts':dict(counts),'errors':errors,'settled_usd':account['settled_cost_usd'],'unresolved_reserved_usd':account['unresolved_reserved_usd'],'cumulative_committed_usd':account['cumulative_committed_usd'],'scope':'79 native controls and all 21 paid-model integration episodes; schemas, immutable artifact hashes, identities, three trace files, and physical billing reconciliation. Earlier development failures retained outside this final acceptance set.'}
    write(ROOT/'qa/release_consistency.json',result);print(dump(result))
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
