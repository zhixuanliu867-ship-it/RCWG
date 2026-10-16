"""Rebuild inspectable tables from immutable stage artifacts. No paid calls."""
from pathlib import Path
import json,itertools,collections,sys,math
import pandas as pd
import numpy as np
from event_metrics import worker_spans,union
R=Path(__file__).resolve().parent;O=R/'analysis';O.mkdir(exist_ok=True)
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def csv(name,rows):
 d=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows);d.to_csv(O/(name+'.csv'),index=False,encoding='utf-8-sig');return d
def main(allow_partial=False):
 p=load(R/'protocol/round1.json');jobs=[j for j in p['jobs'] if j['split']=='main'];manifest=load(R/'qa/matrix_manifest.json');rows=[];attempts=[];audited=load(O/'audited_evaluations.json') if (O/'audited_evaluations.json').exists() else {}
 for j in jobs:
  ids=manifest.get(j['episode'],[]);ss=[]
  for eid in ids:
   f=R/'runs'/eid/'summary.json'
   if not f.exists():continue
   s=load(f)
   if eid in audited:s['quality']=audited[eid]['quality']
   ss.append(s);attempts.append({'logical_episode':j['episode'],'episode':eid,'model':j['model'],'task':j['task'],'status':s['status'],'valid':s['quality']['joint_valid'],'calls':s['model_calls'],'settled_cost_usd':s['cost_usd'],'seconds':s['end_to_end_seconds']})
  if not ss:continue
  s=ss[-1];t=load(R/'tasks'/f'{j["task"]}.json');work=collections.Counter();tokens=collections.Counter();errors=collections.Counter();unknown=0;worker_union=0;worker_sum=0;worker_attempts=0;unmatched=0;admission_wait=0.;request_wall=0.;missing_wait=0
  for z in ss:
   work.update(z['work']);path=R/'runs'/z['episode']
   for line in (path/'physical_requests.jsonl').read_text(encoding='utf8').splitlines():
    q=json.loads(line);u=q.get('usage') or {};tokens.update({k:int(u.get(k) or 0) for k in ['prompt_tokens','completion_tokens']});unknown+=q.get('cost_usd') is None;admission_wait+=q.get('admission_wait_seconds',0);request_wall+=q.get('wall_seconds',0);missing_wait+='admission_wait_seconds' not in q
   evs=[json.loads(line) for line in (path/'execution_events.jsonl').read_text(encoding='utf8').splitlines()];sp,wa,um=worker_spans(evs);worker_union+=union(sp);worker_sum+=sum(y-x for x,y in sp);worker_attempts+=wa;unmatched+=len(um)
   for e in evs:
    if e.get('inherited_from'):continue
    if e['kind'] in ('action_rejected','worker_failed'):errors[e['kind']]+=1
  row={'logical_episode':j['episode'],'episode':s['episode'],'model':j['model'],'replicate':j['replicate'],'task':j['task'],'parent':t['parent'],'scene':t['scenario'],'source_cluster':t['source_cluster'],'difficulty':t['difficulty'],'condition':t['condition'],'status':s['status'],'Q1':s['quality']['Q1_task_correct'],'Q2':s['quality']['Q2_evidence_state_valid'],'G':s['quality']['joint_valid'],'first_G':ss[0]['quality']['joint_valid'],'first_status':ss[0]['status'],'attempts':len(ss),'unknown_calls':unknown,'settled_cost_usd':sum(x['cost_usd'] for x in ss),'end_to_end_seconds':sum(x['end_to_end_seconds'] for x in ss),'final_attempt_seconds':s['end_to_end_seconds'],'manager_seconds':sum(x['manager_request_union_seconds'] for x in ss),'tool_union_seconds':sum(x['tool_union_seconds'] for x in ss),'tool_sum_seconds':sum(x['tool_summed_seconds'] for x in ss),'model_calls':sum(x['model_calls'] for x in ss),'initial_nodes':len(load(R/'runs'/s['episode']/'initial_plan.json')['tasks']),'new_revisions':s['revisions'],**tokens,**errors,**{'W_'+k:v for k,v in work.items()}}
  row.update(worker_union_seconds=worker_union,worker_summed_seconds=worker_sum,worker_attempts=worker_attempts,unmatched_worker_events=unmatched)
  row['W_worker_attempts']=worker_attempts;row['W_failed_worker_attempts']=errors.get('worker_failed',0)
  row.update(admission_wait_seconds=admission_wait,request_wall_seconds=request_wall,missing_admission_measurements=missing_wait,no_admission_seconds=max(0,row['end_to_end_seconds']-admission_wait))
  row['raw_G']=audited.get(s['episode'],{}).get('original_quality',s['quality'])['joint_valid'];row['scoring_changed']=row['raw_G']!=row['G'];row['scoring_version']='EVIDENCE_EQUIVALENCE_1' if s['episode'] in audited else 'ORIGINAL_PROVISIONAL'
  physical=[json.loads(x) for x in (R/'runs'/s['episode']/'physical_requests.jsonl').read_text(encoding='utf8').splitlines() if x.strip()]
  local=load(R/'runs/api'/physical[0]['request_id']/'local.json') if physical else {}
  created=local.get('created_at','');row['transport_segment']=sum(created>=x['time'] for x in p.get('operational_amendments',[]) if x['id'] in (1,2,3)) if created else -1
  rows.append(row)
 d=csv('stages',rows);csv('physical_stages',attempts)
 if not allow_partial:assert len(d)==len(jobs), f'Incomplete main matrix: {len(d)}/{len(jobs)}'
 cols=[x for x in d.columns if x.startswith('W_')]+['action_rejected','worker_failed']
 for col in cols:d[col]=d[col].fillna(0) if col in d else 0
 d['sqlite_progress_callbacks']=d['W_sqlite_vm_steps_lower_bound']/1000
 (O/'work_counter_notes.json').write_text(json.dumps({'sqlite_vm_steps_lower_bound':{'legacy_field_preserved':True,'stored_value':'1000 * observed progress callbacks','analysis_alias':'sqlite_progress_callbacks','interpretation':'Fixed-setting SQLite progress-work counter; callback interval is approximate and can include query preparation. Not an exact instruction count or a mathematically guaranteed lower bound.','primary_source':'https://www.sqlite.org/c3ref/progress_handler.html'}},indent=2),encoding='utf8')
 csv('stages',d)
 quality=d.groupby(['model','scene','difficulty','condition'],dropna=False).agg(n=('G','size'),valid=('G','sum'),first_valid=('first_G','sum'),Q1=('Q1','sum'),Q2=('Q2','sum'),usd=('settled_cost_usd','sum'),mean_seconds=('end_to_end_seconds','mean')).reset_index();quality['rate']=quality.valid/quality.n;csv('quality_by_scene_tier',quality)
 overall=d.groupby(['model','difficulty']).agg(n=('G','size'),valid=('G','sum'),first_valid=('first_G','sum'),usd=('settled_cost_usd','sum'),calls=('model_calls','sum')).reset_index();overall['rate']=overall.valid/overall.n;csv('quality_by_tier',overall)
 bases=d[d.condition=='base'];basekey={(x.model,x.parent,x.replicate):x for x in bases.itertuples()};adapt=[]
 for (model,scene,difficulty),g in d.groupby(['model','scene','difficulty']):
  b=g[g.condition=='base'];eligible={(x.parent,x.replicate) for x in b.itertuples() if x.G}
  for cond in ['related','unrelated']:
   u=g[g.condition==cond];mask=pd.Series([(x.parent,x.replicate) in eligible for x in u.itertuples()],index=u.index,dtype=bool);e=u.loc[mask];success=e[e.G];adapt.append({'model':model,'scene':scene,'difficulty':difficulty,'condition':cond,'all_n':len(u),'all_valid':int(u.G.sum()),'correct_base_n':len(eligible),'eligible_update_n':len(e),'retained_valid':int(e.G.sum()),'conditional_rate':float(e.G.mean()) if len(e) else None,'correct_zero_native_calls':int((success.W_tool_attempts==0).sum()),'median_correct_new_calls':float(success.W_tool_attempts.median()) if len(success) else None,'median_correct_seconds':float(success.end_to_end_seconds.median()) if len(success) else None})
 csv('adaptation',adapt)
 # Full recorded native activity vector: retain calls, failed work, and work units.
 # Model requests are reported separately, not silently mixed with native units.
 units={scene:sorted(col[2:] for col in d if col.startswith('W_') and col!='W_model_attempts' and (d.loc[d.scene==scene,col]>0).any()) for scene in d.scene.unique()}
 (O/'work_vector_definition.json').write_text(json.dumps({'version':'FULL_NATIVE_ACTIVITY_V2','units_by_scene':units,'excluded':'model_attempts are retained separately as model_calls; no weighted sum','reason':'A smaller processed-item count can coexist with more transform calls or failed workers. All recorded native activity dimensions are included.'},indent=2),encoding='utf8')
 pairs=[];pool=[];replays=load(O/'replay_results.json') if (O/'replay_results.json').exists() else []
 replaymap={}
 for rec in replays:
  if rec['valid']:replaymap.setdefault((rec['source_episode'],rec['workers']),[]).append(rec['worker_union_seconds'])
 for (parent,rep),g in bases.groupby(['parent','replicate']):
  good=g[g.G];pool.append({'parent':parent,'replicate':rep,'scene':g.iloc[0].scene,'difficulty':g.iloc[0].difficulty,'correct_models':len(good),'eligible_pairs':len(good)*(len(good)-1)//2})
  for a,b in itertools.combinations(good.sort_values('model').to_dict('records'),2):
   us=units[a['scene']];av=[a.get('W_'+u,0) for u in us];bv=[b.get('W_'+u,0) for u in us]
   adom=all(x<=y for x,y in zip(av,bv)) and any(x<y for x,y in zip(av,bv));bdom=all(y<=x for x,y in zip(av,bv)) and any(y<x for x,y in zip(av,bv))
   base={'parent':parent,'replicate':rep,'scene':a['scene'],'difficulty':a['difficulty'],'model_a':a['model'],'model_b':b['model'],'episode_a':a['episode'],'episode_b':b['episode'],'work_dominance':'a' if adom else 'b' if bdom else 'equal' if av==bv else 'tradeoff','calls_a':a['W_tool_attempts'],'calls_b':b['W_tool_attempts'],'live_a':a['end_to_end_seconds'],'live_b':b['end_to_end_seconds'],'clean_transport':a['attempts']==b['attempts']==1}
   base.update(no_admission_a=a['no_admission_seconds'],no_admission_b=b['no_admission_seconds'],same_transport_segment=a['transport_segment']==b['transport_segment'],transport_segment_a=a['transport_segment'],transport_segment_b=b['transport_segment'])
   for w in [1,4]:
    for label,x in [('a',a),('b',b)]:
     vals=replaymap.get((x['episode'],w),[]);base[f'replay_{w}_{label}']=float(np.median(vals)) if vals else None
   for unit in us:
    x,y=a.get('W_'+unit,0),b.get('W_'+unit,0);pairs.append(base|{'unit':unit,'work_a':x,'work_b':y,'work_ratio_a_b':x/y if y else None})
 csv('correct_pair_work',pairs);csv('comparison_pool',pool)
 success=bases[bases.G].copy();csv('correct_base_stages',success)
 print('MAIN_ANALYSIS',len(d),int(d.G.sum()))
if __name__=='__main__':main('--partial' in sys.argv)
