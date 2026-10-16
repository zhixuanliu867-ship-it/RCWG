"""Replay all ten cohorts in one isolated campaign; never calls a model."""
from pathlib import Path
import sys,json,csv,random,time,shutil
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'src'));sys.path.insert(0,str(R))
from common import load,write,canonical,union_seconds
from tiered import TierFlow
from audit_grades import audit_episode
from event_metrics import worker_spans
ROOTS={'R6':Path('E:/CodexResearch/WELD_R6_20261015'),'R7':Path('E:/CodexResearch/WELD_R7_GEMINI_20261015'),'R8':Path('E:/CodexResearch/WELD_R8_100P_20261015'),'R9':R}
ROOTS={k:(R/'historical_raw'/k if (R/'historical_raw'/k/'runs').exists() else v) for k,v in ROOTS.items()}
def main():
 progress=load(R/'qa/matrix_progress.json');assert not progress['running'] and not progress['stop']
 assert progress['completed']==3000 or ('--available' in sys.argv and progress['completed']==progress['planned']), 'A complete available cohort is required.'
 old=list(csv.DictReader((R/'inputs/combined_main_stages.csv').open(encoding='utf-8-sig')))
 new=list(csv.DictReader((R/'analysis/stages.csv').open(encoding='utf-8-sig')))
 for x in new:x['campaign']='R9'
 jobs=[]
 for x in old+new:
  if x['condition']!='base' or str(x['G']).lower()!='true':continue
  for w in [1,4]:
   for rep in range(3):jobs.append(dict(source_episode=x['episode'],source_root=str(ROOTS[x['campaign']]),source_campaign=x['campaign'],task=x['task'],model=x['model'],workers=w,replicate=rep,eid=f'REPLAY9D_w{w}_r{rep}_{x["episode"]}'))
 random.Random(20261016).shuffle(jobs);write(R/'protocol/replay_jobs.json',jobs)
 out=R/'analysis/replay_all_results.json';journal=R/'analysis/replay_all_results.jsonl';rows=[json.loads(line) for line in journal.read_text(encoding='utf8').splitlines() if line.strip()] if journal.exists() else [];done={x['eid'] for x in rows};started=time.time()
 def observations(pack):return sorted(canonical(a['content']) for a in pack['artifacts'].values() if a['kind']=='observation')
 for j in jobs:
  if j['eid'] in done:continue
  if shutil.disk_usage(R).free < 1024**3:raise RuntimeError('Native replay paused before next episode: less than 1 GiB free.')
  if (R/'protocol/PAUSE_NATIVE_REPLAY').exists():
   write(R/'qa/replay_pause.json',{'completed':len(rows),'planned':len(jobs),'paused_between_episodes':True,'time_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()});print('NATIVE_REPLAY_PAUSED_BETWEEN_EPISODES',len(rows),flush=True);raise SystemExit(75)
  source=Path(j['source_root'])/'runs'/j['source_episode'];f=TierFlow(j['task'],j['eid'],j['workers'])
  try:
   for line in (source/'model_responses.jsonl').read_text(encoding='utf8').splitlines():
    response=json.loads(line)['response'];f.event('manager_decision_started',actor='manager');f.event('model_completed',actor='manager',status='REPLAYED_DECISION',source_episode=j['source_episode'])
    try:
     text=response.strip()
     if text.startswith(chr(96)*3):text='\n'.join(text.splitlines()[1:-1])
     if f.execute(json.loads(text)):break
    except Exception as e:f.reject('decision',type(e).__name__+': '+str(e)[:350])
   s=f.finish_flow('FROZEN_REPLAY');spans,attempts,unmatched=worker_spans(f.events);assert not unmatched
   q=audit_episode(j['eid']);faithful=observations(load(source/'checkpoint.json'))==observations(load(f.out/'checkpoint.json'))
   native=lambda z:{k:v for k,v in z.items() if k!='model_attempts'}
   samework=native(load(source/'summary.json')['work'])==native(s['work'])
   row=j|dict(valid=bool(q['quality']['joint_valid'] and faithful and samework),quality_valid=q['quality']['joint_valid'],native_observations_equal=faithful,native_work_equal=samework,worker_union_seconds=union_seconds(spans),runtime_seconds=s['end_to_end_seconds'],work=s['work'])
   rows.append(row)
   with journal.open('a',encoding='utf8') as log:log.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
   if not row['valid']:
    write(R/'qa/replay_mismatch.json',row);raise RuntimeError('Replay mismatch retained: '+j['eid'])
  finally:f.close()
  if len(rows)%30==0:
   state={'completed':len(rows),'planned':len(jobs),'valid':sum(x['valid'] for x in rows),'seconds':time.time()-started};write(R/'qa/replay_progress.json',state);print(json.dumps(state),flush=True)
 write(out,rows);write(R/'analysis/replay_results.json',[x for x in rows if x['source_campaign']=='R9'])
 write(R/'qa/replay_acceptance.json',{'complete':len(rows)==len(jobs),'all_models_collected':progress['completed']==3000,'planned':len(jobs),'completed':len(rows),'all_valid':all(x['valid'] for x in rows),'models':len({x['model'] for x in rows}),'random_seed':20261016,'native_timing_campaign':'R9 D-volume isolated native replay; complete restart after E-volume exhaustion; all model cohorts measured together'})
 print('ALL_MODEL_REPLAY_DONE',len(rows),flush=True)
if __name__=='__main__':main()
