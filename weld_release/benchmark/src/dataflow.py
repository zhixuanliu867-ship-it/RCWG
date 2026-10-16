"""Model-authored native dataflow: fixed deterministic workers, runtime graph edits.
No operator reads private labels. Private labels are imported only by grade().
"""
import copy,json,time,hashlib,math,statistics,ast
from common import *
from runtime import Runtime,ProtocolError

def get(x,path):
 if isinstance(path,str):path=[path]
 for k in path:x=x[int(k)] if isinstance(x,list) else x[k]
 return x

def transform(a):
 op=a['op'];v=a.get('input');path=a.get('path',[])
 if op=='get':return get(v,path)
 if op=='parse':
  try:return json.loads(v)
  except ValueError:return ast.literal_eval(v)
 if op=='rows':return [dict(zip(v['columns'],r)) for r in v['rows']]
 if op=='filter':
  def match(x):
   for p in a['predicates']:
    z=get(x,p['path']);q=p['value'];cmp=p['cmp']
    if not {'eq':lambda:z==q,'ne':lambda:z!=q,'ge':lambda:z>=q,'le':lambda:z<=q,'in':lambda:z in q,'contains':lambda:q in z}[cmp]():return False
   return True
  return [x for x in v if match(x)]
 if op=='project':
  fields=a['fields']
  if isinstance(fields,dict):return [{k:get(x,p) for k,p in fields.items()} for x in v]
  return [get(x,fields) for x in v]
 if op=='unique':return list({canonical(x):x for x in v}.values())
 if op=='sort':
  result=list(v)
  for spec in reversed(a.get('keys',[[]])):
   path=spec['path'] if isinstance(spec,dict) else spec;descending=spec.get('descending',False) if isinstance(spec,dict) else bool(a.get('descending',False))
   result.sort(key=lambda x:get(x,path),reverse=descending)
  return result
 if op=='slice':return v[a.get('start',0):a.get('stop')]
 if op=='flatten':return [z for x in v for z in x]
 if op=='concat':return [z for x in a['inputs'] for z in x]
 if op=='sum':return sum(get(x,path) for x in v)
 if op=='count':return len(v)
 if op=='object':return a['fields']
 if op=='group':
  out={}
  for x in v:
   k=get(x,a['key']);r=out.setdefault(canonical(k),{'key':k,'count':0,'sum':0});r['count']+=1;r['sum']+=get(x,a['value']) if 'value' in a else 0
  return list(out.values())
 raise ProtocolError('Unknown transform '+str(op))

class Flow(Runtime):
 def __init__(self,task_id,eid,workers=4,prefix=None):
  super().__init__(task_id,eid,workers=workers)
  if self.task.get('asset_override'):self.adapter.dbfile=self.task['asset_override']
  elif self.task['scenario']=='analytics' and self.task['r5_condition'] in ('related','unrelated') and self.task['dataset']=='debit':self.adapter.dbfile='debit_object_change.sqlite' if self.task['r5_condition']=='related' else 'debit_unrelated_change.sqlite'
  self.node_outputs={};self.prefix=prefix;self.replay_actions=[];self.decision_count=0
  if prefix:self.import_prefix(Path(prefix))
 def import_prefix(self,path):
  pack=load(path/'checkpoint.json');end=pack['elapsed']
  for e in pack['events']:
   e=copy.deepcopy(e);e['inherited_from']=str(path);e['monotonic_start']-=end+1;e['monotonic_end']-=end+1;e['prior_resource_delta']=e['resource_delta'];e['resource_delta']={};self.events.append(e);self.append('execution_events.jsonl',e)
  self.artifacts=copy.deepcopy(pack['artifacts'])
  for a in self.artifacts.values():self.append('artifacts.jsonl',a)
  self.tasks=copy.deepcopy(pack['tasks']);self.results=copy.deepcopy(pack['results']);self.node_outputs=copy.deepcopy(pack['node_outputs']);self.initialized=True
  for e in self.events:
   if e['kind']=='worker_failed' and self.tasks.get(e.get('task_id'),{}).get('status')=='FAILED':
    self.feedback.append({'event_id':e['event_id'],'action':'worker_execution','task_id':e['task_id'],'reason':e['reason'],'inherited_from':str(path)})
  self.event('environment_update',actor='environment',notice=self.task['task'],condition=self.task['r5_condition'],prefix_sha256=sha(path/'checkpoint.json'))
 def resolve(self,x):
  if isinstance(x,dict) and '$ref' in x:
   ref=x['$ref'];aid=self.node_outputs.get(ref,ref)
   if aid not in self.artifacts:raise ProtocolError('Unknown result reference '+str(ref))
   content=self.artifacts[aid]['content'];v=content.get('data',content)
   return copy.deepcopy(get(v,x.get('path',[])))
  if isinstance(x,dict):return {k:self.resolve(v) for k,v in x.items()}
  if isinstance(x,list):return [self.resolve(v) for v in x]
  return x
 def references(self,x):
  if isinstance(x,dict):
   out=[x['$ref']] if '$ref' in x else []
   for v in x.values():out+=self.references(v)
   return out
  return sum([self.references(v) for v in x],[]) if isinstance(x,list) else []
 def execute(self,obj):
  self.replay_actions.append(copy.deepcopy(obj));write(self.out/'decisions.json',self.replay_actions)
  if 'nodes' in obj:
   edits=[]
   for n in obj['nodes']:
    if not isinstance(n,dict) or not all(k in n for k in ('id','tool','arguments')):raise ProtocolError('Every node needs id, tool, arguments')
    deps=list(dict.fromkeys(n.get('dependencies',[])+[r for r in self.references(n['arguments']) if r in self.tasks or any(z['id']==r for z in obj['nodes'])]));deps=[x for x in deps if x!=n['id']]
    edits.append({'id':n['id'],'scope':{'tool':n['tool'],'arguments':n['arguments']},'dependencies':deps})
   result=self.edit(edits,reason_ids=obj.get('reason_observation_ids',[]))
   if result['ok']:self.dispatch(obj.get('dispatch',[x['id'] for x in edits]),self.worker)
  elif obj.get('dispatch'):self.dispatch(obj['dispatch'],self.worker)
  if 'final' in obj:
   f=self.resolve(obj['final']);f={'answer':f['answer']} if 'answer' in f else {'answer':f}
   # Typed dataflow provenance accompanies every submitted value. This is not a
   # model-written citation-format task; semantic applicability is still checked.
   f['evidence']=list(self.node_outputs.values());f['claims']=[];self.submit(f);return True
  return False
 def worker(self,rt,t):
  a=self.resolve(t['scope']['arguments']);tool=t['scope']['tool'];deps=[self.results[d] for d in t['dependencies'] if d in self.results]
  if tool=='transform':
   start=time.perf_counter()-self.started;data=transform(a);e=self.event('transform_completed',actor='worker:'+t['id'],start=start,arguments=a,input_artifacts=deps,resource_delta={'transform_items':len(a.get('input',[])) if isinstance(a.get('input'),list) else 1,'transform_calls':1})
   aid=self.artifact(e,{'data':data},inputs=deps,kind='derived')
  else:
   r=self.tool('worker:'+t['id'],tool,a);aid=r['artifact_id'];data=r['data']
  self.node_outputs[t['id']]=aid
  return {'result':{'data':data},'evidence':list(dict.fromkeys([aid]+deps))}
 def observation(self,aid):
  a=self.artifacts[aid];v=a['content'].get('data',a['content']);s=dump(v)
  return {'artifact_id':aid,'producer_event_id':a['producer_event_id'],'value':v if len(s)<=11000 else {'preview':s[:11000],'truncated_view':True,'full_value_available_by_reference':True},'source_version':a['input_versions']['source']}
 def unresolved_failures(self):
  # Root causes survive a wide graph's cascade of blocked-dependent messages.
  latest={}
  for event in self.events:
   tid=event.get('task_id')
   if event['kind']=='worker_failed' and self.tasks.get(tid,{}).get('status')=='FAILED':
    latest[tid]={'event_id':event['event_id'],'reason':event['reason'],'inherited_from':event.get('inherited_from')}
  return latest
 def prompt(self):
  tools=copy.deepcopy(self.adapter.tools);tools['transform']={'op':'get|parse|rows|filter|project|unique|sort|slice|flatten|concat|sum|count|object|group','input':'value or {$ref:node_id,path:[keys/indices]}','path':'get/sum extraction path','fields':'project: path list for scalar projection, or mapping output keys to paths; object: resolved values','predicates':'filter: [{path:[...],cmp:eq|ne|ge|le|in|contains,value:...}]','keys':'sort: list of paths or [{path:[...],descending:true},...], stable lexicographic priority','inputs':'concat: arrays','key':'group key path','value':'group sum path'}
  return {'instruction':'Design and execute an efficient native workflow for the public task. Fixed deterministic workers execute your nodes, including parallel independent nodes. You may add investigations or change dependencies after observations. Return {nodes:[{id,tool,arguments,dependencies:[]}],reason_observation_ids:[]} OR {final:{answer:{...}}}. A node result is referenced with {"$ref":"node_id","path":["rows",0]}; all references resolve against its data payload. Nodes run automatically in dependency order. Use a new node ID for a new investigation. Final answer values may use references. Do not invent unobserved facts. All required fields are mandatory. Optimize useful work and completion time while maintaining correctness. Node batching and division are your choice. No arbitrary host code. Do not confuse tool operation names with node IDs. Consult unresolved_worker_failures for upstream failure causes; blocked dependents can be consequences of those failures.',
   'task':{k:v for k,v in self.task.items() if k not in ('source_task','source_status','cluster','handoffs')},'native_tools':tools,'worker_slots':self.workers,'results':{k:self.observation(v) for k,v in self.node_outputs.items()},'tasks':list(self.tasks.values()),'feedback':self.feedback[-8:],'unresolved_worker_failures':self.unresolved_failures(),'decision_index':self.decision_count,'hint':'SQL is read-only; use aggregation in SQL if appropriate. For nested outputs, transform get/project/filter/rows can compose results without copying long lists. Evidence lineage is carried automatically; final answer values still must match observed facts.'}
 def collect(self,client,max_decisions):
  status='NO_SUBMISSION'
  for i in range(max_decisions):
   self.decision_count=i;self.event('manager_decision_started',actor='manager');p=self.prompt();p['remaining_decisions']=max_decisions-i
   if i==max_decisions-1:p['instruction']+=' This is the final decision: submit supported results now.'
   start=time.perf_counter()-self.started
   try:
    r=client.chat(p,'manager',self.id,max_tokens=8192);self.record_model('manager',r['text'],start,r['accounting']);s=r['text'].strip()
    if s.startswith('```'):s='\n'.join(s.splitlines()[1:-1])
    obj=json.loads(s)
    if self.execute(obj):status='EVALUATED';break
   except Exception as e:
    for attempt in getattr(e,'physical_attempts',[]):self.record_model('manager',{'error':str(e)},start,attempt)
    self.reject('decision',type(e).__name__+': '+str(e)[:350])
    if type(e).__name__ in ('TransportStop','BudgetStop'):status='TRANSPORT_UNKNOWN' if type(e).__name__=='TransportStop' else 'BUDGET_EXHAUSTED';break
  return self.finish_flow(status)
 def grade(self):
  from evaluator import evaluate_core
  from evidence_repair import review
  native=self.adapter.native_evaluate() if self.task['scenario']=='appworld' else None
  arts=copy.deepcopy(self.artifacts);events=copy.deepcopy(self.events);verification=[]
  # Previous read results are validated for semantic applicability independently
  # of the candidate's execution ledger. Verifier work is recorded separately.
  if self.prefix:
   byid={e['event_id']:e for e in events}
   for aid,a in arts.items():
    if a['kind']!='observation' or 'inherited_from' not in byid.get(a['producer_event_id'],{}):continue
    c=a['content'];start=time.perf_counter();v=self.adapter.call(c['operation'],c['arguments'],actor='validator')
    valid=bool(c['ok'] and v['ok'] and canonical(c['data'])==canonical(v['data']))
    verification.append({'artifact_id':aid,'applicable':valid,'seconds':time.perf_counter()-start,'resource':v['work']})
    if valid:
     a['input_versions']['source']=self.task['final_version'];byid[a['producer_event_id']]['input_versions']=copy.deepcopy(a['input_versions'])
    else:
     # Keep invalid source observations out of admissible evidence without
     # changing the submitted value or original trace.
     a['content']['ok']=False;a['content_hash']=hashlib.sha256(dump(a['content']).encode()).hexdigest()
  ev=evaluate_core(self.task,self.final,arts,events,native)
  q1=bool(ev['factual_correct'] and not ev.get('extra_answer_fields') and not ev.get('unregistered_findings'))
  q2=bool(ev.get('evidence_valid'))
  write(self.out/'verifier_work.json',verification)
  return {'Q1_task_correct':q1,'Q2_evidence_state_valid':q2,'joint_valid':q1 and q2,'details':ev,'native':native}
 def finish_flow(self,status):
  checkpoint={'task_id':self.task['id'],'events':self.events,'artifacts':self.artifacts,'tasks':self.tasks,'results':self.results,'node_outputs':self.node_outputs,'elapsed':time.perf_counter()-self.started,'final':self.final}
  write(self.out/'checkpoint.json',checkpoint);write(self.out/'final_submission.json',self.final)
  elapsed=time.perf_counter()-self.started;quality=self.grade()
  phase=[e for e in self.events if not e.get('inherited_from')];work={}
  for e in phase:
   for k,v in e['resource_delta'].items():work[k]=work.get(k,0)+v
  model_spans=[(e['monotonic_start'],e['monotonic_end']) for e in phase if e['kind']=='model_completed'];tools=[(e['monotonic_start'],e['monotonic_end']) for e in phase if e['kind'] in ('tool_completed','transform_completed')]
  total_active=union_seconds(model_spans+tools);summary={'episode':self.id,'task_id':self.task['id'],'scenario':self.task['scenario'],'parent':self.task['parent'],'condition':self.task['r5_condition'],'status':status,'quality':quality,'work':work,'end_to_end_seconds':elapsed,'manager_request_union_seconds':union_seconds(model_spans),'tool_union_seconds':union_seconds(tools),'tool_summed_seconds':sum(b-a for a,b in tools),'manager_tool_overlap_seconds':union_seconds(model_spans)+union_seconds(tools)-total_active,'other_seconds':max(0,elapsed-total_active),'model_calls':len(self.requests),'cost_usd':sum(q.get('cost_usd') or 0 for q in self.requests),'prefix':str(self.prefix) if self.prefix else None,'nodes_total':len(self.tasks),'revisions':len(self.revisions),'verifier_excluded_from_candidate_timing':True,'fixed_worker_type':'deterministic native operator executor'}
  write(self.out/'summary.json',summary);write(self.out/'evaluation.json',quality);self.close();return summary
