"""Freeze the cross-model measurement protocol before any benchmark inference."""
import datetime,random,collections
from common import *

MODELS={'gemini':'google/gemini-3.8-flash','gpt':'openai/gpt-5.6-sol','glm':'z-ai/glm-5.3-flash'}
TASKS=['H_G__complete','H_G__gap','H_A__complete','H_A__gap',
       'E_C__grouped','E_C__interleaved','E_A__grouped','E_A__wrong_object_memo',
       'E_A__free','X02__value_change','X02__object_change','X02__unrelated_change',
       'P_C__correct_control','P_C__single_error','P_C__copied_error',
       'P_I__correct_control','P_I__single_error','P_I__copied_error',
       'X04__all_channels','X04__late_traces','X04__absent_traces',
       'X05__normal','X05__lost_after','X06__second_write_fails']
BRIDGE=['H_G__gap','E_C__interleaved','X02__object_change','P_C__copied_error','P_I__copied_error','X05__lost_after']

def main():
    if (ROOT/'protocol/round1.json').exists():raise RuntimeError('Protocol already frozen')
    for t in TASKS:load(ROOT/f'tasks/{t}.json')
    old=Path(config()['baseline_root']);receipts=[]
    for p in (old/'runs').glob('LIVE_FINAL_*/physical_requests.jsonl'):
        receipts.extend(json.loads(x) for x in p.read_text(encoding='utf8').splitlines())
    per_input=sum((x.get('usage') or {}).get('prompt_tokens',0) or 0 for x in receipts)/10
    per_output=sum((x.get('usage') or {}).get('completion_tokens',0) or 0 for x in receipts)/10
    catalog=load(ROOT/'protocol/model_catalog_round1.json');tags={'gemini':'google-ai-studio','gpt':'openai','glm':'z-ai/fp8'};pricing={}
    for key,mid in MODELS.items():
        endpoint=next(x for x in catalog['endpoints'][mid]['endpoints'] if x['tag']==tags[key])
        pricing[key]={'model':mid,'tag':tags[key],'provider_name':endpoint['provider_name'],'snapshot_name':endpoint['name'],'input_per_m':float(endpoint['pricing']['prompt'])*1e6,'output_per_m':float(endpoint['pricing']['completion'])*1e6,'pricing':endpoint['pricing'],'ignore_tags':[x['tag'] for x in catalog['endpoints'][mid]['endpoints'] if x['tag']!=tags[key]]}
    projected=sum(48*(per_input*x['input_per_m']+per_output*x['output_per_m'])/1e6 for x in pricing.values())
    jobs=[];order=list(TASKS);random.Random(20261013).shuffle(order)
    for repeat in (1,2):
        for t in order if repeat==1 else list(reversed(order)):
            keys=list(MODELS);random.Random(t+str(repeat)).shuffle(keys)
            for k in keys:jobs.append({'episode':f'R1_{k}_r{repeat}_{t}','task':t,'repeat':repeat,'arm':'same_model_system','manager':k,'worker':k})
    for t in BRIDGE:
        for k in ('gpt','glm'):jobs.append({'episode':f'R1_BRIDGE_{k}_{t}','task':t,'repeat':1,'arm':'fixed_gemini_worker','manager':k,'worker':'gemini'})
    p={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'models':MODELS,'pricing':pricing,'tasks':TASKS,'primary_episodes':144,'bridge_episodes':12,'jobs':jobs,'limits':{'calls_per_episode':40,'manager_turns':10,'worker_turns':8,'manager_output_tokens':8192,'worker_output_tokens':8192,'reasoning_effort':'low','response_format':'json_object','temperature':'omitted for all; provider-native defaults','max_parallel_episodes':3,'workers_per_episode':2,'network_timeout_seconds':180,'round_admission_ceiling_usd':100.0,'automatic_retry_unknown':False},'budget_estimate':{'historical_mean_input_tokens_per_episode':per_input,'historical_mean_output_tokens_per_episode':per_output,'main_at_observed_token_volume_usd':projected,'with_bridge_planning_estimate_usd':projected*1.15,'stress_3x_tokens_usd':projected*3.45,'scope':'This user-authorized new round has its own USD100 ceiling, including preflights and failed/unknown requests. Historical USD16.631526544 remains separately recorded, not recharged.'},'hypotheses':[{'id':'H1','mechanism':'Incomplete investigation or incorrect integration despite locally correct evidence','readouts':['M02','M04','M07','M08','M09','M10','M11','M12','M36'],'contrasts':[['H_G__complete','H_G__gap'],['H_A__complete','H_A__gap'],['E_C__grouped','E_C__interleaved'],['E_A__grouped','E_A__wrong_object_memo']]},{'id':'H2','mechanism':'Failure to update conclusions or reconcile state after new observations','readouts':['M17','M18','M19','M20','M22','M37','M39','M40'],'contrasts':[['E_A__free','X02__value_change'],['E_A__free','X02__object_change'],['E_A__free','X02__unrelated_change'],['X04__all_channels','X04__late_traces'],['X04__all_channels','X04__absent_traces'],['X05__normal','X05__lost_after'],['X05__normal','X06__second_write_fails']]},{'id':'H3','mechanism':'Wrong inherited opinion adoption and same-source repetition','readouts':['M28','M29','M30','M31','M32'],'contrasts':[['P_C__correct_control','P_C__single_error'],['P_C__single_error','P_C__copied_error'],['P_I__correct_control','P_I__single_error'],['P_I__single_error','P_I__copied_error']]}],'analysis_rules':['Retain every scheduled and started attempt, including transport and protocol failures.','Main arm compares same-model manager-worker systems. Bridge fixes workers to Gemini on six prespecified tasks; Gemini primary repeat 1 is its shared comparator.','Do not ascribe a main-arm difference to manager ability alone.','Two repeats estimate local repeat sensitivity, not a robust universal pass^k.','Paired conditions share parents and sources; report parent/source denominators, no item-level significance inflation.','Disconfirmation is informative: if copied errors are corrected, say that; do not select only failing tasks.','Deadline/network timeout and call budget remain separate from semantic task failure.','Freeze benchmark input, runtime, and judge before benchmark calls. Any later scoring correction is separately versioned.'],'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for d in ['src','vendor','tasks','private','agent_views','protocol'] for p in (ROOT/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}}
    write(ROOT/'protocol/round1.json',p);print(dump({'tasks':len(TASKS),'main':144,'bridge':12,'budget':p['budget_estimate']}))

if __name__=='__main__':main()
