"""Add two prior source parents with newly runnable task cards; no new-source claim."""
import shutil,csv
from common import *
from build_dataset import emit,tasks
def main():
    cat=load(ROOT/'dataset_catalog.json');P=Path(config()['pilot_root']);N=Path(config()['legacy_root'])
    if any(x['id']=='I_DELAY__all_channels' for x in cat['tasks']):return
    dest=ROOT/'assets/incident_unit2';dest.mkdir(exist_ok=True)
    for name in ('metrics.parquet','logs.parquet','traces.parquet'):shutil.copy2(P/'sources/incident_b'/name,dest/name)
    pub=load(P/'dataset/I2/public.json');gold=load(P/'private/I2_gold.json')['v0']['answers']
    for condition in ('all_channels','late_traces'):
        t={'id':'I_DELAY__'+condition,'family':'I_DELAY','scenario':'incident','dataset':'incident_unit2','parent':'I2','cluster':'RCA_ONLINEBOUTIQUE_CHECKOUT','condition':condition,'task':pub['task'],'cut_timestamp':pub['cut_timestamp'],'conditions':{'traces':'pending' if condition=='late_traces' else 'available'},'handoffs':[],'track':'free_construction'}
        if condition=='late_traces':t['update']={'trigger_tools':['metric_summary'],'asset':'traces','target_version':'r1','notice':pub['update_notice']};t['final_version']='r1'
        emit(t,{'answer':gold,'origin':'Original second RCAEval delay episode, unchanged telemetry; previously used source parent I2.'})
    spec=load(N/'appworld_workspace/data/tasks/b0a8eae_1/specs.json')
    for condition in ('normal','recoverable_read'):
        t={'id':'B_MUSIC__'+condition,'family':'B_MUSIC','scenario':'appworld','dataset':'appworld','parent':'B1','cluster':'APPWORLD_WORKOUT_b0a8eae','condition':condition,'task':spec['instruction']+' Use typed app APIs; session authentication is supplied by the local bridge. Complete the task when the actual music-player state is correct.','datetime':spec['datetime'],'native_task_id':'b0a8eae_1','conditions':{'first_read_fault':condition=='recoverable_read'},'track':'free_construction'}
        emit(t,{'answer':{'completion':'state_verified'},'origin':'Original AppWorld native instruction and evaluator; multiple qualifying playlists accepted.'})
    for t in tasks:
        public={k:t[k] for k in ('public_id','task','scenario','initial_version','answer_schema')};public['handoffs']=[];public['contract']='Return answer, claims [{field,value,evidence:[artifact IDs]}], and evidence. Use the observed native state.'
        if t.get('datetime'):public['datetime']=t['datetime']
        write(ROOT/f"agent_views/{t['public_id']}.json",public)
        cat['tasks'].append({k:t.get(k) for k in ('id','family','scenario','parent','cluster','condition','track','source_status')})
    cat['task_count']=len(cat['tasks']);cat['semantic_parents']=len({t['parent'] for t in cat['tasks']});cat['source_clusters']=len({t['cluster'] for t in cat['tasks']});write(ROOT/'dataset_catalog.json',cat)
    with (ROOT/'task_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['id','family','scenario','parent','cluster','condition','track'];w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(cat['tasks'])
    print(dump({'task_count':cat['task_count'],'parents':cat['semantic_parents'],'source_clusters':cat['source_clusters']}))
if __name__=='__main__':main()
