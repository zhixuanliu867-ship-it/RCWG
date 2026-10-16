"""Local JSON bridge. No network service or real account is operated."""
import os,sys,json,ast,contextlib,io,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
os.environ['APPWORLD_ROOT']=str(R/'appworld_workspace');os.environ['APPWORLD_CACHE']=str(R/'cache/appworld');os.environ['PYTHONUTF8']='1'
sys.stdout.reconfigure(encoding='utf-8');sys.stdin.reconfigure(encoding='utf-8')
from appworld import AppWorld
def evaluate_world(w):
 native=w.evaluate().to_dict();result=dict(native);result['native_success']=native['success']
 if w.task_id=='22cc237_1':
  from appworld.task import Task
  from appworld.apps.model_lib import get_db_home_path
  from appworld.collections.models import ModelCollection,ModelCollectionPair
  t=Task.load(w.task_id);start=t.model_collection;end_path=get_db_home_path(storage_type='memory',type='task_output',task_id=w.task_id)
  end=ModelCollection.load(to_db_home_path=end_path,from_db_home_path=w.output_db_home_path_on_disk,load_apps=t.allowed_apps)
  pair=ModelCollectionPair(start_db_home_path=start.from_db_home_path,start_model_collection=start,end_db_home_path=end_path,end_model_collection=end)
  added,updated,removed=pair.changed_records('venmo.PaymentRequest')
  expected=json.loads((R/f'appworld_workspace/data/tasks/{w.task_id}/ground_truth/private_data.json').read_text())['pending_user_id_to_share']
  expected={str(k).removeprefix('{_INT_}:'):v for k,v in expected.items()}
  rows=[{'receiver_id':x.receiver_id,'amount':x.amount,'description':x.description} for x in added]
  recipients=[str(x['receiver_id']) for x in rows]
  checks={'exact_request_multiplicity':len(rows)==len(expected) and len(set(recipients))==len(rows),'exact_recipients':set(recipients)==set(expected),'amounts_to_cent':all(str(x['receiver_id']) in expected and abs(x['amount']-expected[str(x['receiver_id'])])<0.005 for x in rows),'required_description':all(x['description']=='Work Dinner' for x in rows)}
  result.update(added_request_count=len(rows),expected_request_count=len(expected),additional_contract_checks=checks,success=native['success'] and all(checks.values()))
 return result
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def safe(code):
 tree=ast.parse(code)
 allowed={'json','math','datetime','itertools','collections','statistics','re','calendar'}
 for n in ast.walk(tree):
  if isinstance(n,(ast.Import,ast.ImportFrom)):
   names=[a.name for a in n.names] if isinstance(n,ast.Import) else [n.module or '']
   if any(x.split('.')[0] not in allowed for x in names):raise ValueError('Only documented safe imports are available')
  if isinstance(n,ast.Attribute) and n.attr.startswith('_'):raise ValueError('Private object access is unavailable')
  if isinstance(n,ast.Name) and (n.id.startswith('__') or n.id in {'open','eval','exec','compile','getattr','setattr','delattr','globals','locals','vars','__import__','input','breakpoint','requester'}):raise ValueError('Host introspection is unavailable')
 return code
def control():
 records=[]
 for pid,tid in [('B1','b0a8eae_1'),('B2','22cc237_1')]:
  spec=json.loads((R/f'appworld_workspace/data/tasks/{tid}/specs.json').read_text(encoding='utf-8'))
  write(R/f'dataset/{pid}/public.json',{'id':pid,'scenario':'appworld','task':spec['instruction'],'task_id':tid,'datetime':spec['datetime'],'source':'AppWorld 0.1.0 train, native instruction/state/evaluator; delivery-uncertainty condition added','condition_notice':'One successful business mutation may have its response withheld. The state may already be changed. Inspect state before retrying.','answer_format':{'summary':'completion summary','evidence':['artifact IDs']}})
  code=(R/f'appworld_workspace/data/tasks/{tid}/ground_truth/compiled_solution.py').read_text(encoding='utf-8')
  for mode in ['no_op','reference','extra_read']:
   with AppWorld(task_id=tid,experiment_name='offline_'+pid+'_'+mode,raise_on_unsafe_syntax=False,null_patch_unsafe_execution=False,timeout_seconds=None) as w:
    if mode!='no_op':
     prefix='apis.supervisor.show_profile()\n' if mode=='extra_read' else ''
     result=w.execute(prefix+code+'\nsolution(apis, requester)')
    else:result='No action'
    tracker=w.evaluate();status=tracker.to_dict();calls=w.requester.request_tracker.requests
    rec={'parent':pid,'task_id':tid,'mode':mode,'evaluation':status,'api_calls':len(calls),'execution_output':result}
    write(R/f'qa/appworld_{pid}_{mode}.json',rec);records.append(rec)
    print(pid,mode,json.dumps(status,default=str)[:500],flush=True)
 write(R/'qa/appworld_controls.json',records)
def bridge(tid,episode,condition):
 with AppWorld(task_id=tid,experiment_name=episode,timeout_seconds=None,raise_on_unsafe_syntax=True,null_patch_unsafe_execution=True) as w:
  withheld=False
  for line in sys.stdin:
   try:
    a=json.loads(line)
    if a['op']=='close':break
    if a['op']=='evaluate':out={'evaluation':evaluate_world(w)}
    elif a['op']=='exec':
     code=safe(a['code']);before=len(w.requester.request_tracker.requests)
     hashes_path=Path(w.output_db_home_path_on_disk)/'model_hashes.json'
     previous_hashes=json.loads(hashes_path.read_text()) if hashes_path.exists() else {}
     t=time.perf_counter();result=w.execute(code);elapsed=time.perf_counter()-t
     current_hashes=json.loads(hashes_path.read_text()) if hashes_path.exists() else {}
     calls=w.requester.request_tracker.requests[before:]
     business=[x for x in calls if x['method']!='get' and any(s in x['url'] for s in ['/payment_requests','/music_player/play','/music/play'])]
     target_app,target_model=('venmo','PaymentRequest') if tid=='22cc237_1' else ('spotify','MusicPlayer')
     committed=previous_hashes.get(target_app,{}).get(target_model)!=current_hashes.get(target_app,{}).get(target_model)
     # Actual endpoint names are validated against the offline native log before API admission.
     out={'output':result,'native_api_calls':calls,'wall_seconds':elapsed,'withheld':False}
     if condition=='change' and business and committed and not withheld:
      withheld=True;out.update(output='DELIVERY_UNCERTAIN: execution returned after a business mutation; response contents were withheld by the experiment. Read current app state before retrying.',withheld=True)
    else:raise ValueError('unknown bridge operation')
   except Exception as e:out={'error':type(e).__name__,'detail':str(e)[:1000]}
   print(json.dumps(out,ensure_ascii=False,default=str),flush=True)
if __name__=='__main__':
 if sys.argv[1]=='controls':control()
 else:bridge(*sys.argv[1:4])
