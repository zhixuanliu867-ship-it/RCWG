"""Ten-model research tables, preserving acquisition and parent dependence."""
from pathlib import Path
import json,itertools,sys
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parent;A=R/'analysis'
PRIMARY={'graph':'graph_paper_records_read','code_review':'native_cases','analytics':'sqlite_vm_steps_lower_bound','incident':'metric_values_read','appworld':'business_records_read'}
MODELS=['deepseek','kimi','qwen','gemma','glm','minimax','gemini','gemini37','grok','luna']
LABELS=['DeepSeek V4 Pro 0813','Kimi K2.6','Qwen3.8 Flash','Gemma 4 31B','GLM-5.3 Flash','MiniMax M3','Gemini 3.8 Flash','Gemini 3.7 Flash','Grok 4.3','GPT-6 Luna']
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(n,d):
 d=d if isinstance(d,pd.DataFrame) else pd.DataFrame(d);d.to_csv(A/(n+'.csv'),index=False,encoding='utf-8-sig');return d
def boot(t,value):
 v=t.groupby('parent')[value].mean().dropna().to_numpy()
 if not len(v):return dict(parents=0,estimate=None,low=None,high=None)
 x=np.random.default_rng(20261016).choice(v,(4000,len(v)),replace=True).mean(axis=1)
 return dict(parents=len(v),estimate=float(v.mean()),low=float(np.quantile(x,.025)),high=float(np.quantile(x,.975)))
def main():
 global A
 source_a=A;available='--available' in sys.argv
 old=pd.read_csv(R/'inputs/combined_main_stages.csv');new=pd.read_csv(source_a/'stages.csv');assert len(old)==3000
 if available:
  assert new.groupby('model').size().eq(600).all();A=source_a/'available';A.mkdir(exist_ok=True)
 else:assert len(new)==3000
 models=[m for m in MODELS if m in set(old.model)|set(new.model)]
 parent_cohort=old.groupby('parent').cohort.first().to_dict();new['cohort']=new.parent.map(parent_cohort);new['campaign']='R9';new['online_group']=np.where(new.model.eq('glm'),'R9_glm_delayed','R9_initial4');old['online_group']=old.campaign
 # R6/R7 used one fixed admission configuration, verified against their original protocols and collectors.
 old['transport_segment_origin']=np.where(old.transport_segment.isna(),'derived_fixed_configuration','recorded')
 missing=old.transport_segment.isna();assert set(old.loc[missing,'campaign'])<= {'R6','R7'}
 old.loc[missing,'transport_segment']=0
 new['transport_segment_origin']='recorded'
 old['model_cohort']='existing5';new['model_cohort']='added5';d=pd.concat([old,new],ignore_index=True)
 wc=[c for c in d if c.startswith('W_')];d[wc]=d[wc].fillna(0);d['sqlite_progress_callbacks']=d.W_sqlite_vm_steps_lower_bound/1000
 assert len(d)==600*len(models) and set(d.model)==set(models) and not d.duplicated(['model','parent','replicate','condition']).any()
 save('combined_main_stages',d);write_model_metadata=[]
 for m in models:
  i=MODELS.index(m);write_model_metadata.append(dict(model=m,label=LABELS[i],group='Open-weight family API' if i<6 else 'Closed API',cohort='existing5' if m in set(old.model) else 'added5'))
 save('model_metadata',write_model_metadata)
 cells=d.groupby(['model','scene','difficulty','condition']).agg(n=('G','size'),valid=('G','sum'),Q1=('Q1','sum'),Q2=('Q2','sum'),usd=('settled_cost_usd','sum')).reset_index();cells['rate']=cells.valid/cells.n;save('all_result_cells',cells)
 save('cohort_quality',d.groupby(['campaign','cohort','model','scene','condition']).agg(n=('G','size'),valid=('G','sum'),rate=('G','mean')).reset_index())
 b=d[d.condition.eq('base')];base=b.set_index(['model','parent','replicate']);u=d[d.condition.ne('base')].copy();u['base_G']=[bool(base.loc[(x.model,x.parent,x.replicate),'G']) for x in u.itertuples()];save('all_updates',u);eligible=u[u.base_G]
 model=[]
 for m in models:
  t=d[d.model.eq(m)];tb=t[t.condition.eq('base')];row=dict(model=m,n=len(t),valid=int(t.G.sum()),base_n=len(tb),base_valid=int(tb.G.sum()),answer_valid=int(t.Q1.sum()),submitted=int(t.status.eq('EVALUATED').sum()),usd=float(t.settled_cost_usd.sum()))
  for tier in ['easy','medium']:
   q=tb[tb.difficulty.eq(tier)];row[tier+'_n']=len(q);row[tier+'_valid']=int(q.G.sum())
  for c in ['related','unrelated']:
   q=eligible[eligible.model.eq(m)&eligible.condition.eq(c)];row[c+'_n']=len(q);row[c+'_valid']=int(q.G.sum())
  model.append(row)
 save('model_summary',model)
 for name,keys in [('conditional_adaptation',['model','difficulty','condition']),('conditional_adaptation_scene',['model','scene','condition']),('conditional_adaptation_cohort',['cohort','model','condition'])]:save(name,eligible.groupby(keys).agg(n=('G','size'),valid=('G','sum'),rate=('G','mean'),median_new_calls=('W_tool_attempts','median')).reset_index())
 d['transport_unresolved']=d.status.isin(['TRANSPORT_UNKNOWN','BUDGET_EXHAUSTED'])
 av=d.groupby(['model','condition']).agg(n=('G','size'),confirmed_valid=('G','sum'),transport_unresolved=('transport_unresolved','sum')).reset_index();av['lower']=av.confirmed_valid/av.n;av['upper']=(av.confirmed_valid+av.transport_unresolved)/av.n;save('availability_bounds',av)
 oldp=pd.read_csv(R/'inputs/combined_prefix_audit.csv');newp=new.merge(pd.DataFrame(load(source_a/'prefix_compatibility.json')),on='logical_episode');pa=save('combined_prefix_audit',pd.concat([oldp,newp],ignore_index=True))
 save('prefix_refresh_matrix',pa.groupby(['model','prefix_answer_still_correct','prefix_evidence_already_sufficient']).agg(n=('G','size'),updated_valid=('G','sum'),rate=('G','mean')).reset_index())
 save('update_need_summary',pa.groupby(['cohort','model','prefix_already_valid']).agg(n=('G','size'),valid=('G','sum'),rate=('G','mean')).reset_index())
 replays=load(source_a/'replay_all_results.json');replaymap={}
 for x in replays:
  if x['valid']:replaymap.setdefault((x['source_episode'],x['workers']),[]).append(x['worker_union_seconds'])
 units={s:[c for c in wc if c!='W_model_attempts' and d.loc[d.scene.eq(s),c].gt(0).any()] for s in d.scene.unique()}
 pairs=[];components=[];pools=[];times=[]
 for (parent,rep),g in b.groupby(['parent','replicate']):
  good=g[g.G].sort_values('model');scene=g.iloc[0].scene;us=units[scene]
  pools.append(dict(parent=parent,replicate=rep,scene=scene,cohort=parent_cohort[parent],correct_models=len(good),pairs=len(good)*(len(good)-1)//2))
  for a,z in itertools.combinations(good.to_dict('records'),2):
   av=[a[c] for c in us];zv=[z[c] for c in us];ad=all(x<=y for x,y in zip(av,zv)) and av!=zv;zd=all(y<=x for x,y in zip(av,zv)) and av!=zv
   row={k:a[k] for k in ['parent','replicate','scene','source_cluster','difficulty','cohort']};relation='a_dominates' if ad else 'b_dominates' if zd else 'equal' if av==zv else 'tradeoff'
   same=a['online_group']==z['online_group'] and a.get('transport_segment',0)==z.get('transport_segment',0)
   clean=a['attempts']==z['attempts']==1
   row.update(model_a=a['model'],model_b=z['model'],episode_a=a['episode'],episode_b=z['episode'],relation=relation,tool_calls_a=a['W_tool_attempts'],tool_calls_b=z['W_tool_attempts'],same_online_group=same,online_group_a=a['online_group'],online_group_b=z['online_group'],clean_transport=clean)
   pairs.append(row)
   for unit in us:components.append(row|dict(unit=unit[2:],work_a=a[unit],work_b=z[unit],primary=unit[2:]==PRIMARY[scene]))
   unit='W_'+PRIMARY[scene];wa,wz=a.get(unit,0),z.get(unit,0)
   if wa==wz or not clean or relation not in ['a_dominates','b_dominates']:continue
   low,high=(a,z) if wa<wz else (z,a)
   if (low is a and not ad) or (low is z and not zd):continue
   sw=1-low[unit]/high[unit]
   for timing,field,slots in [('online','end_to_end_seconds',None),('online_without_admission','no_admission_seconds',None),('native_replay_1',None,1),('native_replay_4',None,4)]:
    if field and not same:continue
    if field:tl,th=low[field],high[field]
    else:
     lv=replaymap.get((low['episode'],slots),[]);hv=replaymap.get((high['episode'],slots),[])
     if len(lv)!=3 or len(hv)!=3:continue
     tl,th=float(np.median(lv)),float(np.median(hv))
    if not np.isfinite(tl) or not np.isfinite(th) or th<=0:continue
    st=1-tl/th;times.append(row|dict(timing=timing,unit=unit[2:],low_model=low['model'],high_model=high['model'],low_episode=low['episode'],high_episode=high['episode'],work_saving=sw,time_saving=st,attenuation_gap=sw-st,work_low=low[unit],work_high=high[unit],time_low=tl,time_high=th,outcome='reversed_or_zero' if st<=0 else 'attenuated_positive' if st<sw else 'at_least_proportional'))
 pp=save('native_work_pairs',pairs);lc=save('native_work_pair_components',components);pl=save('comparison_pool',pools)
 save('work_relation_summary',pp.groupby(['scene','relation']).agg(pairs=('parent','size'),parents=('parent','nunique')).reset_index())
 tied=save('same_tool_call_count_primary_work',lc[lc.primary&lc.tool_calls_a.eq(lc.tool_calls_b)])
 save('call_count_blind_spot',tied.assign(different=tied.work_a.ne(tied.work_b)).groupby('scene').agg(equal_call_pairs=('parent','size'),different_primary_work=('different','sum'),parents=('parent','nunique')).reset_index())
 at=save('attenuation_primary',times);save('attenuation_summary',at.groupby(['difficulty','timing','outcome']).agg(n=('parent','size'),parents=('parent','nunique')).reset_index())
 save('attenuation_parent_uncertainty',[dict(difficulty=tier,timing=timing,**boot(t,'attenuation_gap')) for (tier,timing),t in at.groupby(['difficulty','timing'])])
 matched=[];matchedstats=[];native=at[at.timing.eq('native_replay_4')&at.difficulty.eq('medium')];keys=['parent','replicate','low_episode','high_episode']
 for timing in ['online','online_without_admission']:
  q=at[at.timing.eq(timing)&at.difficulty.eq('medium')].merge(native,on=keys,suffixes=('_online','_native'));q['native_minus_online']=q.time_saving_native-q.time_saving_online;q['online_domain']=timing;matched.append(q);matchedstats.append(dict(timing=timing,pairs=len(q),**boot(q,'native_minus_online')))
 save('paired_timing_domains',pd.concat(matched,ignore_index=True));save('paired_timing_domain_uncertainty',matchedstats)
 commonkeys=set(map(tuple,pl.loc[pl.correct_models.eq(len(models)),['parent','replicate']].to_numpy()));cu=u[[(x.parent,x.replicate) in commonkeys for x in u.itertuples()]]
 common=[]
 for m in models:
  for c in ['related','unrelated']:
   q=cu[cu.model.eq(m)&cu.condition.eq(c)];common.append(dict(model=m,condition=c,n=len(q),valid=int(q.G.sum()),rate=q.G.mean() if len(q) else None,parents=q.parent.nunique()))
 save('common_support_adaptation',common)
 pairwise=[]
 for ma,mb in itertools.combinations(models,2):
  aa=u[u.model.eq(ma)&u.base_G];zz=u[u.model.eq(mb)&u.base_G];j=aa.merge(zz,on=['parent','replicate','condition'],suffixes=('_a','_b'))
  for c,q in j.groupby('condition'):
   q=q.copy();q['delta']=q.G_a.astype(int)-q.G_b.astype(int);pairwise.append(dict(model_a=ma,model_b=mb,condition=c,n=len(q),valid_a=int(q.G_a.sum()),valid_b=int(q.G_b.sum()),**boot(q,'delta')))
 save('pairwise_common_support_adaptation',pairwise)
 source_ci=[];rng=np.random.default_rng(20261016)
 for m,t in eligible[eligible.condition.eq('related')].groupby('model'):
  pt=t.groupby(['scene','source_cluster','parent']).G.mean().reset_index();bs=[]
  strata=[[h.G.to_numpy() for _,h in g.groupby('source_cluster')] for _,g in pt.groupby('scene')]
  for _ in range(2000):
   values=[]
   for clusters in strata:
    for index in rng.integers(0,len(clusters),len(clusters)):
     vals=clusters[index];values.extend(rng.choice(vals,len(vals),replace=True))
   bs.append(np.mean(values))
  source_ci.append(dict(model=m,parents=pt.parent.nunique(),source_clusters=pt.source_cluster.nunique(),equal_parent_estimate=pt.G.mean(),low=np.quantile(bs,.025),high=np.quantile(bs,.975),unit='source cluster within scene, then parent; shared-corpus dependence remains'))
 save('related_source_uncertainty',source_ci)
 sensitivity=[]
 for m,t in eligible.groupby('model'):
  for cond,g in t.groupby('condition'):
   for excluded in sorted(g.source_cluster.unique()):
    h=g[g.source_cluster.ne(excluded)];sensitivity.append(dict(model=m,condition=cond,excluded_source=excluded,rate=h.groupby('parent').G.mean().mean(),parents=h.parent.nunique()))
 save('leave_one_source_out',sensitivity)
 result=dict(main_n=len(d),main_valid=int(d.G.sum()),base_n=len(b),base_valid=int(b.G.sum()),new_n=len(new),new_valid=int(new.G.sum()),parents=d.parent.nunique(),source_clusters=d.source_cluster.nunique(),models=d.model.nunique(),pairs=len(pp),parents_with_pairs=pl[pl.pairs.gt(0)].parent.nunique(),equal_pairs=int(pp.relation.eq('equal').sum()),dominance_pairs=int(pp.relation.isin(['a_dominates','b_dominates']).sum()),tradeoff_pairs=int(pp.relation.eq('tradeoff').sum()),common_ten_cells=len(commonkeys) if len(models)==10 else None,common_all_model_cells=len(commonkeys),planned_stages=6000,all_models_complete=len(models)==10,pending_models=[m for m in MODELS if m not in models])
 (A/'final_summary.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(result)
if __name__=='__main__':main()
