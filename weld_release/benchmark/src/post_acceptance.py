"""Regression controls for the interface defects found by live model integration."""
import copy,uuid
from common import *
from acceptance import read_episode
from evaluator import evaluate
from runtime import Runtime
from references import appworld
def main():
    rows=[]
    def check(name,result,detail=None):rows.append({'name':name,'pass':bool(result),'detail':detail})
    s,a,e,n=read_episode('ACCEPT_FINAL_H_A__free');t=load(ROOT/'tasks/H_A__free.json');strings=copy.deepcopy(s)
    strings['answer']['regional']=[[x[0],*map(str,x[1:])] for x in strings['answer']['regional']];strings['claims']=[]
    check('numeric_strings_preserve_declared_integer_meaning',evaluate(t,strings,a,e,n)['success'])
    strings['answer']['regional'][0][1]='84.0001';check('fractional_count_not_normalized_to_integer',not evaluate(t,strings,a,e,n)['success'])
    rt=Runtime('H_A__free','POST_projection')
    try:
        r=rt.tool('worker:fixture','select',{'sql':'SELECT loan_id FROM loan ORDER BY loan_id','limit':1000})
        rt.submit({'answer':{'loan_ids':{'from_artifact':r['artifact_id'],'path':['rows'],'column':'loan_id'}},'evidence':[]})
        check('projection_uses_public_tool_result_root',rt.final['answer']['loan_ids']==[x[0] for x in r['data']['rows']])
    finally:rt.close()
    for tid,eid in [('E_C__free','LIVE_FINAL_05'),('E_A__free','LIVE_03'),('G_WINDOW_2015__free','LIVE_02')]:
        s,a,e,n=read_episode(eid);check('live_equivalent_representation_'+tid,evaluate(load(ROOT/f'tasks/{tid}.json'),s,a,e,n)['success'])
    s,a,e,n=read_episode('LIVE_FINAL_05');wrong=copy.deepcopy(s);wrong['claims']=[];wrong['answer']['impacted_entrypoints'][0]='itsdangerous.TimestampSigner.invented_method';check('nonexistent_public_symbol_rejected',not evaluate(load(ROOT/'tasks/E_C__free.json'),wrong,a,e,n)['success'])
    class Client:
        def __init__(self):self.i=0;self.saw_feedback=False
        def chat(self,prompt,role,episode_id):
            self.saw_feedback|=bool(prompt.get('view',{}).get('feedback'));self.i+=1
            text='{"broken":' if self.i==1 else dump({'final':{'answer':{},'evidence':[]}})
            return {'text':text,'accounting':{'request_id':'OFFLINE_STUB_'+uuid.uuid4().hex,'cost_usd':0,'status':'SETTLED','role':role,'simulation':True}}
    rt=Runtime('H_G__free','POST_protocol_feedback');client=Client()
    try:
        rt.run_agent(client,max_calls=3,manager_turns=3,worker_turns=1);summary=load(rt.out/'summary.json');check('malformed_json_feedback_and_recovery',client.saw_feedback and summary['status']=='EVALUATED' and client.i==2)
    finally:rt.close()
    class ReserveClient:
        def __init__(self):self.roles=[]
        def chat(self,prompt,role,episode_id):
            self.roles.append(role);obj={'plan':[{'id':'a','scope':'investigate','dependencies':[]}],'dispatch':['a']} if len(self.roles)==1 else {'final':{'answer':{},'evidence':[]}}
            return {'text':dump(obj),'accounting':{'request_id':'OFFLINE_STUB_'+uuid.uuid4().hex,'cost_usd':0,'status':'SETTLED','role':role,'simulation':True}}
    rt=Runtime('H_G__free','POST_final_reserve');client=ReserveClient()
    try:rt.run_agent(client,max_calls=2,manager_turns=2,worker_turns=3);check('last_manager_call_reserved',client.roles==['manager','manager'])
    finally:rt.close()
    # A real fourth request tests the native-vs-exact-state distinction.
    rt=Runtime('X05__normal','POST_duplicate_native')
    try:
        answer=appworld(rt);good=rt.adapter.native_evaluate();first=next(e for e in rt.events if e.get('tool')=='app_call' and e.get('arguments',{}).get('api')=='create_payment_request');extra=rt.tool('worker:reconcile','app_call',first['arguments']);bad=rt.adapter.native_evaluate();rt.submit({'answer':answer,'evidence':list(rt.results.values())});rt.finish()
        check('native_duplicate_rejected_by_exact_state',good['success'] and extra['ok'] and not bad['success'] and bad['added_request_count']==4,{'before':good['success'],'after_native_success':bad['native_success'],'after_exact_success':bad['success'],'added_requests':bad['added_request_count']})
    finally:rt.close()
    write(ROOT/'qa/post_integration_acceptance.json',{'checks':rows,'passed':sum(x['pass'] for x in rows),'total':len(rows)});print(dump({'passed':sum(x['pass'] for x in rows),'total':len(rows),'failures':[x['name'] for x in rows if not x['pass']]}))
    if not all(x['pass'] for x in rows):raise SystemExit(1)
if __name__=='__main__':main()
