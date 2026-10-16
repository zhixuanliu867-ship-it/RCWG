"""Isolated frozen-decision replay. No model requests. Randomized order."""
from pathlib import Path
import sys,json,time,random,argparse
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'src'))
from common import load,write,union_seconds,canonical
from tiered import TierFlow
from event_metrics import worker_spans
def main():
 assert load(R/'qa/matrix_progress.json')['completed']==3000
 # API collection must have ended; do not overlap worker timing with paid runs.
 assert not load(R/'qa/matrix_progress.json')['running']
 manifest=load(R/'qa/matrix_manifest.json');p=load(R/'protocol/round1.json');jobs=[];audited=load(R/'analysis/audited_evaluations.json')
 for j in p['jobs']:
  if j['split']!='main' or not j['task'].endswith('__base'):continue
  eid=manifest[j['episode']][-1];s=load(R/'runs'/eid/'summary.json')
  if not audited[eid]['quality']['joint_valid']:continue
  for w in [1,4]:
   for rep in range(3):jobs.append({'source_episode':eid,'task':j['task'],'workers':w,'replicate':rep,'eid':f'REPLAY2_w{w}_r{rep}_{eid}'})
 random.Random(20261015).shuffle(jobs);out=R/'analysis/replay_results.json';rows=load(out) if out.exists() else [];finished={x['eid'] for x in rows};start=time.time()
 for job in jobs:
  if job['eid'] in finished:continue
  f=TierFlow(job['task'],job['eid'],job['workers'])
  try:
   # Reproduce parsing/rejection and event slots, not only accepted actions.
   # Stored decisions only: there is no model invocation or model cost.
   for line in (R/'runs'/job['source_episode']/'model_responses.jsonl').read_text(encoding='utf8').splitlines():
    response=json.loads(line)['response']
    f.event('manager_decision_started',actor='manager')
    f.event('model_completed',actor='manager',status='REPLAYED_DECISION',source_episode=job['source_episode'])
    try:
     text=response.strip()
     if text.startswith(chr(96)*3):text='\n'.join(text.splitlines()[1:-1])
     if f.execute(json.loads(text)):break
    except Exception as e:f.reject('decision',type(e).__name__+': '+str(e)[:350])
   s=f.finish_flow('FROZEN_REPLAY');events=f.events;spans,attempts,unmatched=worker_spans(events);assert not unmatched,unmatched
   sys.path.insert(0,str(R));from audit_grades import audit_episode
   verified=audit_episode(job['eid'])
   def observations(pack):return sorted(canonical(a['content']) for a in pack['artifacts'].values() if a['kind']=='observation')
   old=load(R/'runs'/job['source_episode']/'checkpoint.json');new=load(f.out/'checkpoint.json')
   faithful=observations(old)==observations(new)
   oldwork=load(R/'runs'/job['source_episode']/'summary.json')['work'];native_equal={k:v for k,v in oldwork.items() if k!='model_attempts'}=={k:v for k,v in s['work'].items() if k!='model_attempts'}
   rows.append(job|{'valid':verified['quality']['joint_valid'] and faithful and native_equal,'quality_valid':verified['quality']['joint_valid'],'native_observations_equal':faithful,'native_work_equal':native_equal,'worker_union_seconds':union_seconds(spans),'runtime_seconds':s['end_to_end_seconds'],'work':s['work']});write(out,rows)
  finally:f.close()
  if len(rows)%30==0:print(json.dumps({'completed':len(rows),'planned':len(jobs),'valid':sum(x['valid'] for x in rows),'seconds':time.time()-start}),flush=True)
 write(R/'qa/replay_acceptance.json',{'complete':len(rows)==len(jobs),'planned':len(jobs),'completed':len(rows),'all_valid':all(x['valid'] for x in rows),'random_seed':20261015})
 print('REPLAYS_DONE',len(rows),flush=True)
if __name__=='__main__':main()
