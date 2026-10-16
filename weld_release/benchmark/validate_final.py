"""Final acceptance of the complete cohort and merged research data."""
from pathlib import Path
import json,hashlib,collections,math,xml.etree.ElementTree as ET
import pandas as pd
R=Path(__file__).resolve().parent
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 progress=load(R/'qa/matrix_progress.json');assert progress['completed']==3000 and not progress['running'] and not progress['stop']
 development=load(R/'qa/development_acceptance.json');assert development['passed'] and len(development['models'])==5
 p=load(R/'protocol/round1.json');fr=load(R/'protocol/run_freeze.json');assert sha(R/'protocol/round1.json')==fr['protocol_sha256'];assert sha(R/'run_matrix.py')==fr['collector_sha256'];assert sha(R/'audit_grades.py')==fr['independent_audit_sha256']
 for k,h in {**fr['source_hashes'],**fr['asset_hashes']}.items():assert sha(R/k)==h,k
 for x in load(R/'inputs/manifest.json'):assert sha(R/x['file'])==x['sha256'],x['file']
 manifest=load(R/'qa/matrix_manifest.json');resolved=load(R/'qa/matrix_resolved.json');jobs={j['episode']:j for j in p['jobs'] if j['split']=='main'};assert len(manifest)==len(resolved)==len(jobs)==3000
 ids=set();statuses=collections.Counter();headers=['assignment.json','checkpoint.json','initial_plan.json','plan_revisions.jsonl','execution_events.jsonl','physical_requests.jsonl','model_responses.jsonl']
 for logical,seq in manifest.items():
  assert resolved[logical]==seq[-1]
  for eid in seq:
   folder=R/'runs'/eid;s=load(folder/'summary.json');j=load(folder/'assignment.json');assert s['episode']==eid
   for name in headers:assert (folder/name).exists(),(eid,name)
   for line in (folder/'physical_requests.jsonl').read_text(encoding='utf8').splitlines():
    x=json.loads(line);rid=x['request_id'];assert rid not in ids;ids.add(rid);assert x['requested_model']==p['models'][j['model']]
    if x.get('status')=='SETTLED':
     assert x['returned_model']==p['models'][j['model']],(rid,x['returned_model']);assert x['provider']==p['pricing'][j['model']]['provider_name'];assert math.isfinite(x['cost_usd']) and x['cost_usd']>=0
    statuses[x['status']]+=1
  job=jobs[logical]
  if job['prefix_episode']:assert load(R/'runs'/seq[-1]/'assignment.json')['prefix_episode']==resolved[job['prefix_episode']]
 d=pd.read_csv(R/'analysis/combined_main_stages.csv');assert len(d)==6000 and d.model.nunique()==10 and d.parent.nunique()==100 and d.source_cluster.nunique()==20
 assert not d.duplicated(['model','parent','replicate','condition']).any();assert d.unmatched_worker_events.sum()==0;assert d.groupby('model').size().eq(600).all();assert d.groupby('scene').parent.nunique().eq(20).all();assert d.groupby('scene').source_cluster.nunique().eq(4).all();assert d.groupby('difficulty').parent.nunique().to_dict()=={'easy':25,'medium':75}
 cells=pd.read_csv(R/'analysis/all_result_cells.csv');assert cells.n.sum()==6000 and cells.valid.sum()==d.G.sum()
 assert load(R/'qa/evidence_audit.json')['integrity_errors']==0
 re=load(R/'qa/replay_acceptance.json');assert re['complete'] and re['all_valid'];assert re['models']==d[d.condition.eq('base')&d.G].model.nunique();assert re['completed']==6*int(d[d.condition.eq('base')].G.sum())
 budget=load(R/'analysis/budget_final.json');assert budget['combined_committed_usd']<=100 and budget['committed_usd']<=budget['admission_ceiling_usd']
 vector=[]
 for name in ['figure_0_experiment_design','figure_1_correct_work_differences','figure_2_work_to_time','figure_3_selective_adaptation']:
  for ext in ['svg','pdf','png']:assert (R/'figures'/f'{name}.{ext}').stat().st_size>500
  xml=ET.parse(R/'figures'/f'{name}.svg');texts=xml.findall('.//{http://www.w3.org/2000/svg}text');rasters=xml.findall('.//{http://www.w3.org/2000/svg}image');assert texts and not rasters
  vector.append(dict(figure=name,editable_text_objects=len(texts),raster_images=len(rasters)))
 front=(R/'papers/acl_frontmatter.tex').read_text(encoding='utf8');assert '\\usepackage[final]{acl}' in front and '[review]' not in front;assert 'Zhixuan Liu' in front and 'Qi Yan' in front and front.count('Northeastern University')==2
 nb=load(R/'analysis/research_notebook.ipynb');code=[c for c in nb['cells'] if c['cell_type']=='code'];assert code and all(c['execution_count'] is not None for c in code);assert not any(o.get('output_type')=='error' for c in code for o in c['outputs'])
 out=dict(pass_all=True,formal_stages=3000,combined_stages=6000,parents=100,source_clusters=20,models=10,physical_stages=sum(map(len,manifest.values())),physical_requests=len(ids),request_statuses=dict(statuses),prefix_consistency=True,integrity_errors=0,combined_committed_usd=budget['combined_committed_usd'],source_hashes=len(fr['source_hashes']),asset_hashes=len(fr['asset_hashes']),replay=re,vector_figures=vector)
 (R/'qa/final_acceptance.json').write_text(json.dumps(out,indent=2),encoding='utf8');print(out)
if __name__=='__main__':main()
