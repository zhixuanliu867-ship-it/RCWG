"""Resolve compound-condition materialization and write executable schemas before freeze."""
import copy,json
from common import *
def main():
    t=load(ROOT/'tasks/X12__update_handoff.json');g=load(ROOT/'private/X12__update_handoff.json');p=t['handoffs'][0]
    p['rows']=p['rows'][::2];p['scope_complete']=False;p['continuation']={'tool':'select','required_scope':'All observed 2012 months for the currently selected eligible customer'}
    t['handoffs']=[p];write(ROOT/'tasks/X12__update_handoff.json',t)
    # Both source conditions carry the same fresh observed test records. The
    # factor changes their ordering; copied false normative claims remain fixed.
    native=load(ROOT/'assets/requests/observations_v1.json')
    for v in ('source_only','source_binding'):
        p=ROOT/f'tasks/X12__{v}.json';t=load(p);rows=copy.deepcopy(native)
        rows.sort(key=(lambda x:(x['check_id'],x['case_id'])) if v=='source_only' else (lambda x:(x['case_id'],x['check_id'])))
        for x in rows:x['input_version']='r1'
        t['handoffs']=[x for x in t['handoffs'] if x.get('artifact_id')!='test_identity_packet']+[{'artifact_id':'test_identity_packet','kind':'native_test_observations','input_refs':['requests/current_snapshot'],'observations':rows,'notice':'Historical handoff observation; fresh native checks remain available.'}];write(p,t)
    p=ROOT/'tasks/X07__stale_two_readers.json';t=load(p);t['task']+=' This controlled concurrency schedule exposes the same initial pending-request snapshot to two worker readers before admitting writes. Assign those reads to two workers, then coordinate subsequent mutations and refresh state as needed.';write(p,t)
    def blind(x):
        if isinstance(x,str):
            import re
            return re.sub(r'\b(v0|v1|fixed)\b',lambda m:{'v0':'r0','v1':'r1','fixed':'r2'}[m.group()],x)
        if isinstance(x,list):return [blind(y) for y in x]
        if isinstance(x,dict):return {k:blind(y) for k,y in x.items()}
        return x
    for p in (ROOT/'tasks').glob('*.json'):
        t=load(p);v=load(ROOT/f"agent_views/{t['public_id']}.json");v['task']=t['task'];v['handoffs']=t['handoffs'];write(ROOT/f"agent_views/{t['public_id']}.json",v)
        v=blind(v);v['contract']+=' Claims may omit value when it is already present in answer. Large answer fields may use {from_artifact: ID, path: [data], column: column_name} to project an observed SQL column, or a path to an observed worker result. Keep evidence IDs explicit.';write(ROOT/f"agent_views/{t['public_id']}.json",v)
    fields={'event_id':{'type':'string'},'episode_id':{'type':'string'},'monotonic_start':{'type':'number','minimum':0},'monotonic_end':{'type':'number','minimum':0},'actor_role':{'type':'string'},'kind':{'type':'string'},'task_id':{'type':['string','null']},'input_artifacts':{'type':'array','items':{'type':'string'}},'input_versions':{'type':'object'},'output_artifacts':{'type':'array'},'status':{'type':'string'},'logical_action_id':{'type':['string','null']},'physical_attempt_id':{'type':['string','null']},'resource_delta':{'type':'object'}}
    write(ROOT/'protocol/events.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':list(fields),'properties':fields,'additionalProperties':True})
    write(ROOT/'protocol/artifacts.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['artifact_id','producer_event_id','input_refs','source_record_refs','input_versions','content_hash','content','claims','obligation_scope','observed_or_inferred'],'properties':{'artifact_id':{'type':'string'},'input_refs':{'type':'array'},'content_hash':{'type':'string','pattern':'^[0-9a-f]{64}$'}}})
    x=load(ROOT/'protocol/operators.json');x['version']='2.0';x['implementation_status']='Implemented in src/runtime.py and src/adapters.py; compatibility aliases listed in source';write(ROOT/'protocol/operators.json',x)
    x=load(ROOT/'protocol/metrics.json');x['version']='2.0'
    for m in x['metrics']:m['implementation']='src/metrics.py::summarize' if m['id'] not in ('M45','M46','M47') else 'src/metrics.py::compare' if m['id'] in ('M45','M46') else 'src/metrics.py::reliability'
    x['measurement_statuses']=['MEASURED','NOT_APPLICABLE','NOT_OBSERVED'];write(ROOT/'protocol/metrics.json',x)
    print('Compound conditions and JSON schemas materialized')
if __name__=='__main__':main()
