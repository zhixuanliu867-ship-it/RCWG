"""Typed calls into native local AppWorld; generic auth only, no task answer access."""
import sys,json,re,hashlib
from pathlib import Path
import app_native
from app_native import AppWorld,evaluate_world,R

def main(episode,variant):
 with AppWorld(task_id='22cc237_1',experiment_name=episode,timeout_seconds=None,raise_on_unsafe_syntax=True,null_patch_unsafe_execution=True) as w:
  initialized=False;masked=False
  for line in sys.stdin:
   req=json.loads(line)
   if req['op']=='close':break
   if req['op']=='evaluate':print(json.dumps({'evaluation':evaluate_world(w)},default=str),flush=True);continue
   before=len(w.requester.request_tracker.requests);path=Path(w.output_db_home_path_on_disk)/'model_hashes.json';old=json.loads(path.read_text()) if path.exists() else {};code='';result=''
   try:
    op=req['op'];app=req.get('app','');api=req.get('api','')
    if op in ['app_call','api_doc'] and (not re.fullmatch('[a-z][a-z0-9_]*',app) or api and not re.fullmatch('[a-z][a-z0-9_]*',api)):raise ValueError('Invalid app or API name')
    if op=='profile':code='print(apis.supervisor.show_profile())'
    elif op=='list_apps':code='print(apis.api_docs.show_app_descriptions())'
    elif op=='api_doc':code=f'print(apis.api_docs.show_api_doc(app_name={app!r},api_name={api!r}))' if api else f'print(apis.api_docs.show_api_descriptions(app_name={app!r}))'
    elif op=='app_call':
     args=req.get('arguments',{}).copy()
     if not initialized:
      w.execute("profile=apis.supervisor.show_profile(); passwords={x['account_name']:x['password'] for x in apis.supervisor.show_account_passwords()}; session_tokens={}");initialized=True
     if app in ['phone','simple_note','venmo'] and api!='login':
      login=f"\nif {app!r} not in session_tokens: session_tokens[{app!r}]=apis.{app}.login(username=profile['phone_number' if {app!r}=='phone' else 'email'],password=passwords[{app!r}])['access_token']\n"
      args.pop('access_token',None);code=login+f"call_arguments={args!r}; call_arguments['access_token']=session_tokens[{app!r}]; print(apis.{app}.{api}(**call_arguments))"
     else:code=f'print(apis.{app}.{api}(**{args!r}))'
    else:raise ValueError('Unknown typed operation')
    result=w.execute(code)
   except Exception as exc:result='Execution failed. '+type(exc).__name__+': '+str(exc)
   current=json.loads(path.read_text()) if path.exists() else {};calls=w.requester.request_tracker.requests[before:]
   committed=old.get('venmo',{}).get('PaymentRequest')!=current.get('venmo',{}).get('PaymentRequest') and any(x['url']=='/venmo/payment_requests' and x['method']=='post' for x in calls)
   withheld=variant=='lost_response' and committed and not masked
   if withheld:masked=True
   output='DELIVERY_UNCERTAIN: the request may have committed. Inspect current payment-request state before any retry.' if withheld else result
   print(json.dumps({'output':output,'api_calls':len(calls),'discovery_calls':sum('/api_docs/' in x['url'] for x in calls),'business_committed':committed,'withheld':withheld,'failed':result.startswith('Execution failed.'),'state_hash':hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()},default=str),flush=True)
if __name__=='__main__':main(*sys.argv[1:3])
