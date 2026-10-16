"""R6 task-facing operators and task-level verification; no gold read by workers."""
import copy, json, sqlite3, time, hashlib, math
from collections import Counter
from common import *
from adapters import Adapter, DomainError
from dataflow import Flow, transform
import runtime

class TierAdapter(Adapter):
 def __init__(self,task,episode):
  super().__init__(task,episode)
  if task.get('asset_override'):self.dbfile=task['asset_override']
  self.state=copy.deepcopy(task.get('initial_state',{}))
  if self.scenario=='graph':
   self.tools['neighbors']['direction']='out follows src -> dst; a paper references its outgoing edge_type=1 neighbors. in returns papers that cite it.'
   self.tools['publications']={'author_ids':'array of integer author IDs (1..100)','year_min':'inclusive integer, optional','year_max':'inclusive integer, optional','mode':'summary (default) or records','returns':'{rows:[{author_id,count,total_citations,top_id,top_citations}]}; records gives {rows:[{author_id,id,year,citations,name}]}'}
   self.tools['publication_summary']={'author_ids':'array of integer author IDs','year_min':'inclusive year','year_max':'inclusive year','returns':'{rows:[{author_id,count,total_citations,top_id,top_citations}]} exact computed statistics, in input author order'}
   self.tools['references']={'paper_ids':'array of integer paper IDs','returns':'{rows:[{paper_id,reference_ids:[integer]}]} papers cited BY each input paper; complete outgoing citation list'}
  elif self.scenario=='analytics':
   self.tools['customer_summary']={'ids':'array of customer IDs, omit for all','year':'YYYY, optional','returns':'{rows:[{customer_id,count,total_amount}]}; one row per customer'}
   self.tools['loan_summary']={'regions':'array of region names, omit for all','statuses':'array of A/B/C/D, omit for all','returns':'{rows:[{region,loan_count,total_amount,adverse_count}]}'}
   if self.dataset in ('chinook','northwind'):
    self.tools.pop('customer_summary');self.tools.pop('loan_summary')
    self.tools['purchase_summary']={'ids':'array of customer IDs, omit for all','returns':'{rows:[{customer_id,order_count,item_count,total_amount}]} complete all-date purchase aggregation; item_count sums line quantities; total_amount sums line price*quantity after line discount where present. IDs retain native type.'}
  elif self.scenario=='code_review':
   self.tools['case_contracts']={'checks':'array of check names, omit for all','returns':'{cases:[{check_id,case_id,expected}]} public normative expectations, not observed results'}
  elif self.scenario=='appworld':
   self.tools={'playlist_catalog':{'returns':'{rows:[{id,title}]} owned playlists'},'playlist_summary':{'ids':'array of IDs, omit for all','include_songs':'boolean default false','returns':'{rows:[{id,duration_seconds,song_count,(songs)}]}'},'play':{'playlist_id':'integer','session':'session name from task','returns':'state for that session'},'read_state':{'returns':'current playlists/requests/preferences'},'payment_records':{'ids':'array of member IDs, omit for all','returns':'{rows:[{id,share_cents,paid_cents}]} ledger'},'request_payment':{'member_id':'integer','amount_cents':'nonnegative integer; 0 removes request','returns':'committed request; replaces by member ID, never duplicates'}}
   if 'download_playlists' in self.task.get('requirements',{}):
    self.tools={k:v for k,v in self.tools.items() if k in ('playlist_catalog','playlist_summary','read_state')}
    self.tools['download_songs']={'song_ids':'array of existing integer song IDs','returns':'committed current downloaded IDs; idempotent membership, every requested write counted'}
 def _graph(self,name,a):
  if name=='publication_summary':return self._graph('publications',{**a,'mode':'summary'})
  if name=='references':
   d,w,refs=super()._graph('neighbors',{'ids':a['paper_ids'],'edge_type':1,'direction':'out','limit':1000})
   if d['has_more']:raise DomainError('More than 1000 reference edges; use paginated neighbors')
   return {'rows':[{'paper_id':i,'reference_ids':sorted({x['dst'] for x in d['rows'] if x['src']==i})} for i in a['paper_ids']]},w,refs
  if name!='publications':return super()._graph(name,a)
  ids=a['author_ids'];assert 0<len(ids)<=100 and all(type(i)==int for i in ids)
  c=sqlite3.connect(f'file:{(ROOT/"assets"/self.dbfile).as_posix()}?mode=ro',uri=True);c.row_factory=sqlite3.Row;ticks=[0];c.set_progress_handler(lambda:ticks.__setitem__(0,ticks[0]+1000) or 0,1000)
  q='SELECT e.src author_id,n.id,n.year,n.citations,n.name FROM edges e JOIN nodes n ON e.dst=n.id WHERE e.type=3 AND e.src IN ('+','.join('?'*len(ids))+') AND n.year BETWEEN ? AND ? ORDER BY e.src,n.id'
  rows=[dict(x) for x in c.execute(q,ids+[a.get('year_min',-1),a.get('year_max',9999)])];c.close()
  if a.get('mode','summary')=='summary':
   result=[]
   for aid in dict.fromkeys(ids):
    ps=[x for x in rows if x['author_id']==aid];top=sorted(ps,key=lambda x:(-(x['citations'] or 0),x['id']))
    result.append({'author_id':aid,'count':len(ps),'total_citations':sum(x['citations'] or 0 for x in ps),'top_id':top[0]['id'] if top else None,'top_citations':top[0]['citations'] if top else None})
  else:result=rows
  return {'rows':result},{'graph_paper_records_read':len(rows),'sqlite_vm_steps_lower_bound':ticks[0],'returned_records':len(result)},[{'source':'graph','version':self.version,'identity':{'author_id':i}} for i in ids]
 def _analytics(self,name,a):
  if name=='purchase_summary':
   c=sqlite3.connect(f'file:{(ROOT/"assets"/self.dbfile).as_posix()}?mode=ro',uri=True);c.row_factory=sqlite3.Row;ticks=[0];c.set_progress_handler(lambda:ticks.__setitem__(0,ticks[0]+1000) or 0,1000)
   if self.dataset=='chinook':q='SELECT i.CustomerId customer_id,COUNT(DISTINCT i.InvoiceId) order_count,SUM(l.Quantity) item_count,ROUND(SUM(l.UnitPrice*l.Quantity),2) total_amount FROM Invoice i JOIN InvoiceLine l ON i.InvoiceId=l.InvoiceId WHERE 1=1';key='i.CustomerId'
   else:q='SELECT o.CustomerID customer_id,COUNT(DISTINCT o.OrderID) order_count,SUM(l.Quantity) item_count,ROUND(SUM(l.UnitPrice*l.Quantity*(1-l.Discount)),2) total_amount FROM Orders o JOIN "Order Details" l ON o.OrderID=l.OrderID WHERE 1=1';key='o.CustomerID'
   p=[]
   if a.get('ids') is not None:q+=' AND '+key+' IN ('+','.join('?'*len(a['ids']))+')';p+=a['ids']
   q+=' GROUP BY '+key+' ORDER BY '+key
   try:rows=[dict(x) for x in c.execute(q,p)]
   finally:c.close()
   return {'rows':rows},{'queries':1,'sqlite_vm_steps_lower_bound':ticks[0],'returned_rows':len(rows)},[{'source':self.dataset,'version':self.version,'identity':r} for r in rows]
  if name not in ('customer_summary','loan_summary'):return super()._analytics(name,a)
  c=sqlite3.connect(f'file:{(ROOT/"assets"/self.dbfile).as_posix()}?mode=ro',uri=True);c.row_factory=sqlite3.Row;ticks=[0];c.set_progress_handler(lambda:ticks.__setitem__(0,ticks[0]+1000) or 0,1000)
  if name=='customer_summary':
   q='SELECT CustomerID customer_id,COUNT(*) count,ROUND(SUM(Consumption),2) total_amount FROM yearmonth WHERE 1=1';p=[]
   if a.get('ids') is not None:q+=' AND CustomerID IN ('+','.join('?'*len(a['ids']))+')';p+=a['ids']
   if a.get('year'):q+=' AND Date LIKE ?';p+=[str(a['year'])+'%']
   q+=' GROUP BY CustomerID ORDER BY CustomerID'
  else:
   q="SELECT d.A3 region,COUNT(*) loan_count,SUM(l.amount) total_amount,SUM(CASE WHEN l.status IN ('B','D') THEN 1 ELSE 0 END) adverse_count FROM loan l JOIN account a ON l.account_id=a.account_id JOIN district d ON a.district_id=d.district_id WHERE 1=1";p=[]
   if a.get('regions') is not None:q+=' AND d.A3 IN ('+','.join('?'*len(a['regions']))+')';p+=a['regions']
   if a.get('statuses') is not None:q+=' AND l.status IN ('+','.join('?'*len(a['statuses']))+')';p+=a['statuses']
   q+=' GROUP BY d.A3 ORDER BY d.A3'
  rows=[dict(x) for x in c.execute(q,p)];c.close()
  return {'rows':rows},{'queries':1,'sqlite_vm_steps_lower_bound':ticks[0],'returned_rows':len(rows)},[{'source':self.dataset,'version':self.version,'identity':r} for r in rows]
 def _code_review(self,name,a):
  if name=='case_contracts':
   cases=load(ROOT/f'protocol/{self.dataset}_public_contracts.json');scope=set(a.get('case_ids',self.task['requirements']['scoped_case_ids']));selected=[x for x in cases if (not a.get('checks') or x['check_id'] in a['checks']) and x['check_id']+'::'+x['case_id'] in scope]
   return {'cases':selected},{'contract_cases_read':len(selected)},[{'source':self.dataset,'version':self.version,'identity':{'contract':True}}]
  result=super()._code_review(name,a)
  if name=='run_checks' and a.get('check_names'):
   d,w,refs=result;scope=set(a.get('case_ids',self.task['requirements']['scoped_case_ids']))
   for ch in d['checks']:ch['observations']=[x for x in ch['observations'] if ch['check']+'::'+x['case_id'] in scope]
   return d,w,refs
  return result
 def _appworld(self,name,a):
  with self._lock:
   if name=='download_songs':
    ps=load(ROOT/self.task['business_export'])['playlists'];known={s['id'] for p in ps for s in p['songs']};ids=a['song_ids']
    if not isinstance(ids,list) or any(type(i)!=int or i not in known for i in ids):raise DomainError('Unknown song ID')
    previous=set(self.state.get('downloaded',[]));self.state['downloaded']=sorted(previous|set(ids))
    return {'downloaded':self.state['downloaded']},{'business_writes':len(ids),'business_state_changes':len(set(ids)-previous)},[]
   if name=='read_state':return copy.deepcopy(self.state),{'state_reads':1},[]
   if name=='playlist_catalog':
    data=load(ROOT/self.task.get('business_export','assets/appworld_exports/b0a8eae_1.json'))['playlists'];return {'rows':[{'id':p['id'],'title':p['title']} for p in data]},{'business_records_read':len(data)},[]
   if name=='playlist_summary':
    data=load(ROOT/self.task.get('business_export','assets/appworld_exports/b0a8eae_1.json'))['playlists'];ps=[p for p in data if a.get('ids') is None or p['id'] in a['ids']];rows=[]
    for p in ps:
     row={'id':p['id'],'duration_seconds':sum(x['duration'] for x in p['songs']),'song_count':len(p['songs'])}
     if a.get('include_songs'):row['songs']=p['songs']
     rows.append(row)
    return {'rows':rows},{'business_records_read':sum(len(p['songs']) for p in ps),'returned_records':len(rows)},[]
   if name=='play':
    data=load(ROOT/self.task.get('business_export','assets/appworld_exports/b0a8eae_1.json'))['playlists'];p=next(x for x in data if x['id']==a['playlist_id'])
    if a['session'] not in self.task['requirements']['sessions']:raise DomainError('Unknown session')
    self.state.setdefault('playing',{})[a['session']]=p['id'];return {'session':a['session'],'playlist_id':p['id'],'playing':True},{'business_writes':1},[]
   if name=='payment_records':
    rows=[x for x in self.task['ledger'] if a.get('ids') is None or x['id'] in a['ids']];return {'rows':copy.deepcopy(rows)},{'business_records_read':len(rows)},[]
   if name=='request_payment':
    mid=a['member_id'];amount=a['amount_cents']
    if type(amount)!=int or amount<0 or mid not in [x['id'] for x in self.task['ledger']]:raise DomainError('Invalid payment')
    self.state.setdefault('requests',{})[str(mid)]=amount
    return {'member_id':mid,'amount_cents':amount,'committed':True},{'business_writes':1},[]
   raise DomainError('Unknown business operation')

RETURN_TYPES={'nodes':'{rows:[{id,type,name,year,citations,abstract}],has_more,next_offset}','neighbors':'{rows:[{src,dst,type,id,node_type,name,year,citations}],has_more,next_offset}','search_nodes':'{rows:[node],has_more,next_offset}','metric_summary':'{rows:[{metric,pre_mean,post_mean,ratio}],has_more,next_offset}','trace_summary':'[{service,pre_median_duration,post_median_duration,ratio,records}] (raw array)','log_search':'{count,by_service,samples,has_more}','run_checks':'{checks:[{check,observations:[{case_id,observed_outcome,...}],exitcode}]}','read_file':'{path,lines:[string],start,total_lines,sha256}','read_probe_inputs':'{path,lines:[string],start,total_lines,sha256}','select':'{columns:[string],rows:[[values]],has_more,next_offset,read_tables,read_columns,sql,parameters}'}

def eq(a,b):
 if type(b)==float:return type(a) in (int,float) and math.isfinite(a) and abs(a-b)<=max(.005,abs(b)*1e-4)
 if isinstance(b,list):
  if not isinstance(a,list) or len(a)!=len(b):return False
  rest=list(a)
  for y in b:
   ix=next((i for i,x in enumerate(rest) if eq(x,y)),None)
   if ix is None:return False
   rest.pop(ix)
  return True
 if isinstance(b,dict):return isinstance(a,dict) and set(a)==set(b) and all(eq(a[k],v) for k,v in b.items())
 return type(a)==type(b) and a==b

def covers(ob,req):
 """Public operation semantics, independent of a candidate's graph topology."""
 op=ob['operation'];a=ob['arguments'];d=ob['data'];kind=req['kind']
 if kind=='publications':return op in ('publications','publication_summary') and req['author'] in a.get('author_ids',[]) and (a.get('year_min',-1)==req['lo'] and a.get('year_max',9999)==req['hi'] or a.get('mode')=='records' and a.get('year_min',-1)<=req['lo'] and a.get('year_max',9999)>=req['hi'])
 if kind=='neighbors':return (op=='references' and req['edge_type']==1 and req['id'] in a.get('paper_ids',[])) or (op=='neighbors' and req['id'] in a.get('ids',[]) and a.get('edge_type')==req['edge_type'] and a.get('direction','out')=='out' and not d.get('has_more') and a.get('offset',0)==0)
 if kind=='customer':return op=='customer_summary' and (a.get('ids') is None or req['id'] in a['ids']) and str(a.get('year',''))==str(req.get('year',''))
 if kind=='loan':return op=='loan_summary' and (a.get('regions') is None or req['region'] in a['regions']) and sorted(a.get('statuses',[]))==sorted(req.get('statuses',[]))
 if kind=='purchase':return op=='purchase_summary' and (a.get('ids') is None or req['id'] in a['ids'])
 if kind=='check':return op=='run_checks' and any(ch['check']==req['check'] and any(x['case_id']==req['case'] for x in ch['observations']) for ch in d.get('checks',[]))
 if kind=='source':return op=='read_file' and a.get('path')==req['path'] and a.get('start',1)<=req.get('line',1)<=a.get('start',1)+a.get('lines',200)-1
 if kind=='contract':return op=='case_contracts' and any(x['check_id']==req['check'] and x['case_id']==req['case'] for x in d['cases'])
 if kind=='metric':return op=='metric_summary' and req['metric'] in [x['metric'] for x in d.get('rows',[])]
 if kind=='trace':return op=='trace_summary' and req['service'] in [x['service'] for x in d]
 if kind=='log':return op=='log_search' and a.get('regex','error|fail|timeout')==req['regex'] and a.get('service')==req.get('service')
 return False

class TierFlow(Flow):
 def __init__(self,*a,**k):
  runtime.Adapter=TierAdapter
  super().__init__(*a,**k)
  if self.task['scenario']=='appworld' and self.prefix:
   self.adapter.state=copy.deepcopy(load(self.prefix/'business_state.json'))
 def prompt(self):
  p=super().prompt();p['task']={k:v for k,v in self.task.items() if k in ('id','task','scenario','dataset','answer_schema','requirements','initial_version','final_version','conditions','public_context','difficulty')}
  p['return_types']=RETURN_TYPES
  p['instruction']+=' IMPORTANT: transform filter/project/sort/slice/unique return RAW ARRAYS, not a rows object. Reference arrays using path:[0,...], not path:["rows"]. An empty path references the full result. Final answer must have only the requested answer fields. Reused observations can remain valid after an unrelated update. You choose which observations to refresh.'
  p['instruction']+=' You can submit short answers directly as JSON literals after observing the evidence; no transform node is required for copying values. reason_observation_ids is optional; if used, copy producer_event_id from a result rather than inventing IDs. To finish, return {"final":{"answer":...}}, not a node named final.'
  p['reference_example']={'value':{'$ref':'previous_node_id','path':['rows',0,'field_name']},'rule':'A reference is a JSON object, never a string containing $ref. Replace node ID and path by the actual previous result.'}
  if self.task['scenario']=='code_review':p['instruction']+=' run_checks and case_contracts show only the scoped case IDs by default; every actually executed test is still counted. If source inspection is required by the task, complete it even for an approve verdict.'
  p['previous_answer']=load(self.prefix/'final_submission.json') if self.prefix else None
  p['native_tools']=copy.deepcopy(self.adapter.tools)|{'transform':p['native_tools']['transform']}
  return p
 def finish_flow(self,status):
  if self.task['scenario']=='appworld':write(self.out/'business_state.json',self.adapter.state)
  return super().finish_flow(status)
 def grade(self):
  gold=load(ROOT/f'private/{self.task["id"]}.json');answer=(self.final or {}).get('answer',{});obs=[];verification=[]
  # A malformed answer is an incorrect submission, not a verifier exception.
  if not isinstance(answer,dict):answer={}
  for a in self.artifacts.values():
   if a['kind']!='observation' or not a['content'].get('ok'):continue
   c=a['content'];valid=True
   if self.prefix and a['input_versions']['source']!=self.task['final_version']:
    if self.task['scenario']=='appworld':valid=False
    else:
     start=time.perf_counter();v=self.adapter.call(c['operation'],c['arguments'],actor='validator');valid=v['ok'] and canonical(c['data'])==canonical(v['data']);verification.append({'artifact_id':a['artifact_id'],'applicable':valid,'seconds':time.perf_counter()-start,'resource':v['work']})
   if valid:obs.append(c)
  checks={k:eq(answer.get(k),v) for k,v in gold.get('answer',{}).items()};support={}
  if self.task['scenario']=='appworld':
   st=self.adapter.state;req=self.task['requirements'];native={}
   if 'download_playlists' in req:
    ps={p['id']:p for p in load(ROOT/self.task['business_export'])['playlists']};required={s['id'] for pid in req['download_playlists'] for s in ps[pid]['songs']};downloaded=set(st.get('downloaded',[]));known={s['id'] for p in ps.values() for s in p['songs']}
    native['required_songs_downloaded']=required<=downloaded;native['prior_downloads_preserved']=set(self.task['initial_state'].get('downloaded',[]))<=downloaded;native['valid_song_ids']=downloaded<=known;native['other_state_preserved']=all(st.get(k)==v for k,v in self.task['initial_state'].items() if k!='downloaded')
   elif 'sessions' in req:
    ps={x['id']:x for x in load(ROOT/'assets/appworld_exports/b0a8eae_1.json')['playlists']}
    for session,seconds in req['sessions'].items():
     pid=st.get('playing',{}).get(session);native[session]=pid in ps and sum(x['duration'] for x in ps[pid]['songs'])>=seconds
   else:
    expected={str(x['id']):max(0,x['share_cents']-x['paid_cents']) for x in self.task['ledger'] if x['id'] in req['members']}
    native['requests_correct']=all(st.get('requests',{}).get(k,0)==v for k,v in expected.items())
    native['no_unrequested_changes']=set(st.get('requests',{}))<=set(expected)
   native['preferences_preserved']=st.get('preferences')==self.task['initial_state']['preferences'];checks=native;support={'observed_state':bool(obs) or bool(self.prefix)}
   q1=all(checks.values()) and answer.get('completion')=='done';q2=all(support.values())
  else:
   for k,rs in gold['coverage'].items():support[k]=all(any(covers(o,r) for o in obs) for r in rs)
   q1=bool(checks) and all(checks.values()) and set(answer)==set(gold['answer']);q2=bool(support) and all(support.values())
  write(self.out/'verifier_work.json',verification)
  return {'Q1_task_correct':q1,'Q2_evidence_state_valid':q2,'joint_valid':q1 and q2,'details':{'field_checks':checks,'support_checks':support,'answer':answer},'native':checks if self.task['scenario']=='appworld' else None}
