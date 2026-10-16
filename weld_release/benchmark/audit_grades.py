"""Independent post-collection evidence audit; original scores are immutable.
Admits primitive graph reads and equivalent SQL; no generated answer is edited.
"""
from pathlib import Path
import sys,json,copy,re,hashlib,time,collections
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'src'))
from common import load,write,dump,canonical
from tiered import TierAdapter,covers,eq

def compatible_view(content,current):
 """Keep identity-bound unchanged components of a cached native observation.
 Never claim completeness for a partially retained paginated graph result.
 """
 if canonical(content['data'])==canonical(current):return content
 op=content['operation'];old=content['data'];c=copy.deepcopy(content)
 if op=='run_checks':
  now={(ch['check'],x['case_id']):x for ch in current.get('checks',[]) for x in ch['observations']};out=[]
  for ch in old.get('checks',[]):
   keep=[x for x in ch['observations'] if (ch['check'],x['case_id']) in now and canonical(x)==canonical(now[ch['check'],x['case_id']])]
   if keep:out.append({**ch,'observations':keep})
  c['data']={'checks':out};return c if out else None
 if op=='metric_summary':
  now={x['metric']:x for x in current['rows']};kept=[x for x in old['rows'] if x['metric'] in now and canonical(x)==canonical(now[x['metric']])];c['data']={**old,'rows':kept};return c if kept else None
 if op=='trace_summary':
  now={x['service']:x for x in current};c['data']=[x for x in old if x['service'] in now and canonical(x)==canonical(now[x['service']])];return c if c['data'] else None
 if op in ('customer_summary','loan_summary','publication_summary','publications'):
  key,argument=('customer_id','ids') if op=='customer_summary' else ('region','regions') if op=='loan_summary' else ('author_id','author_ids');groups={};now={}
  for row in old['rows']:groups.setdefault(row[key],[]).append(row)
  for row in current['rows']:now.setdefault(row[key],[]).append(row)
  good=[k for k,rows in groups.items() if k in now and canonical(rows)==canonical(now[k])];c['data']={'rows':[x for x in old['rows'] if x[key] in good]};c['arguments'][argument]=good;return c if good else None
 return None

def complete_pages(ob,op,identity):
 pages=[]
 for o in ob:
  if o['operation']!=op or not identity(o['arguments']):continue
  d=o['data']
  if not isinstance(d,dict) or 'rows' not in d:continue
  pages.append((o['arguments'].get('offset',0),len(d['rows']),d.get('has_more',False)))
 pos=0
 for offset,n,more in sorted(set(pages)):
  if offset!=pos:continue
  if not more:return True
  pos+=n
 return False

def sql_rows(o):
 if o['operation'] not in ('select','row_lookup'):return []
 d=o['data']
 if not isinstance(d,dict) or not d.get('read_tables') or d.get('has_more'):return []
 def key(s):
  k=re.sub(r'[^a-z0-9]','',s.lower());return {'customerid':'customer_id','count':'count','countrows':'count','count1':'count','countdistinctdate':'count','sumconsumption':'total_amount','totalamount':'total_amount','loanid':'loan_id','loancount':'loan_count','adversecount':'adverse_count'}.get(k,k)
 cols=[key(x) for x in d['columns']];out=[dict(zip(cols,x)) for x in d['rows']]
 sql=d.get('sql','');match=re.search(r'(?i)\bCustomerID\s*=\s*[\'"]?(\d+)',sql)
 if match and not re.search(r'(?i)\bor\b|\bunion\b',sql):
  for row in out:row.setdefault('customer_id',int(match[1]))
 return out

def alternative(req,obs,gold):
 kind=req['kind']
 if kind=='purchase':
  target=next((r for r in gold['answer'].get('rows',[]) if r.get('customer_id')==req['id']),None)
  if target is None:return False
  needed={'invoice','invoiceline'} if req['dataset']=='chinook' else {'orders','order details'}
  found=set()
  for o in obs:
   if o['operation']!='select' or o['data'].get('has_more'):continue
   if not needed<=set(x.lower() for x in o['data'].get('read_tables',[])):continue
   names={'customerid':'customer_id','ordercount':'order_count','itemcount':'item_count','totalamount':'total_amount'}
   cols=[names.get(re.sub('[^a-z0-9]','',c.lower()),c) for c in o['data']['columns']]
   for values in o['data']['rows']:
    row=dict(zip(cols,values))
    if row.get('customer_id')==req['id']:found.update(k for k,v in target.items() if k in row and eq(row[k],v))
  return set(target)<=found
 if kind=='source':return any(o['operation']=='read_file' and o['arguments'].get('path')==req['path'] and bool(o['data'].get('lines')) for o in obs)
 if kind=='publications':
  return complete_pages(obs,'neighbors',lambda a:req['author'] in a.get('ids',[]) and a.get('edge_type') in (None,3) and a.get('direction','out')=='out')
 if kind=='neighbors':return complete_pages(obs,'neighbors',lambda a:req['id'] in a.get('ids',[]) and a.get('edge_type') in (None,req['edge_type']) and a.get('direction','out')=='out')
 if kind in ('customer','loan'):
  rows=gold['answer'].get('rows',[]);identity='customer_id' if kind=='customer' else 'region';wanted=req['id'] if kind=='customer' else req['region'];target=next((x for x in rows if x.get(identity)==wanted),None)
  if target is None:return False
  found={}
  for o in obs:
   if o['operation'] not in ('select','row_lookup'):continue
   d=o['data'];tables=set(d.get('read_tables',[]));sql=d.get('sql','')
   if kind=='customer' and ('yearmonth' not in tables or req.get('year') and str(req['year']) not in sql):continue
   if kind=='loan' and not {'loan','account','district'}<=tables:continue
   for row in sql_rows(o):
    if row.get(identity)!=wanted:continue
    for k,v in target.items():
     if k in row and eq(row[k],v):found[k]=True
  if set(target)<=set(found):return True
  # Raw records plus local transforms are also valid, independently of SQL
  # aggregate aliases. Deduplicate by native record identity, not by value.
  raw={}
  for o in obs:
   if o['operation'] not in ('select','row_lookup'):continue
   tables=set(o['data'].get('read_tables',[]))
   for row in sql_rows(o):
    if kind=='customer' and 'yearmonth' in tables and row.get('customer_id')==wanted and 'date' in row and 'consumption' in row and str(row['date']).startswith(str(req.get('year',''))):raw[str(row['date'])]=row
    if kind=='loan' and {'loan','account','district'}<=tables and row.get('region')==wanted and all(k in row for k in ['loan_id','amount','status']):raw[row['loan_id']]=row
  if kind=='customer' and raw:return len(raw)==target['count'] and eq(sum(x['consumption'] for x in raw.values()),float(target['total_amount']))
  if kind=='loan' and raw:return len(raw)==target['loan_count'] and sum(x['amount'] for x in raw.values())==target['total_amount'] and sum(x['status'] in ('B','D') for x in raw.values())==target['adverse_count']
  return False
 return False

def audit_episode(eid):
 folder=R/'runs'/eid;s=load(folder/'summary.json');t=load(R/'tasks'/f'{s["task_id"]}.json');gold=load(R/'private'/f'{s["task_id"]}.json');pack=load(folder/'checkpoint.json');adapter=TierAdapter(t,'verifier_'+eid);events={e['event_id']:e for e in pack['events']};obs=[];receipts=[];integrity=[]
 for aid,a in pack['artifacts'].items():
  if a['kind']!='observation' or not a['content'].get('ok'):continue
  c=a['content'];event=events.get(a['producer_event_id'],{});sound=a['content_hash']==hashlib.sha256(dump(c).encode()).hexdigest() and event.get('kind')=='tool_completed' and event.get('status')=='OK' and event.get('tool')==c['operation'] and event.get('arguments')==c['arguments']
  if not sound:integrity.append(aid);continue
  valid=True
  if a['input_versions']['source']!=t['final_version']:
   if t['scenario']=='appworld':valid=False
   else:
    st=time.perf_counter();v=adapter.call(c['operation'],c['arguments'],actor='validator');view=compatible_view(c,v['data']) if v['ok'] else None;valid=view is not None;receipts.append({'artifact_id':aid,'applicable':valid,'whole_observation_equal':v['ok'] and canonical(v['data'])==canonical(c['data']),'component_view_used':valid and canonical(view)!=canonical(c),'seconds':time.perf_counter()-st,'work':v['work']})
    if valid:c=view
  if valid:obs.append(c)
 q=copy.deepcopy(s['quality']);old=copy.deepcopy(q)
 if t['scenario']!='appworld':
  support={k:all(any(covers(o,req) for o in obs) or alternative(req,obs,gold) for req in reqs) for k,reqs in gold['coverage'].items()}
  q['Q2_evidence_state_valid']=bool(support) and all(support.values()) and not integrity;q['joint_valid']=q['Q1_task_correct'] and q['Q2_evidence_state_valid'];q['details']['support_checks']=support
 elif integrity:q['Q2_evidence_state_valid']=q['joint_valid']=False
 adapter.close()
 return {'episode':eid,'quality':q,'original_quality':old,'changed':q['joint_valid']!=old['joint_valid'],'integrity_errors':integrity,'verification':receipts,'version':'EVIDENCE_EQUIVALENCE_1'}

def main():
 manifest=load(R/'qa/matrix_manifest.json');results={};changed=[]
 for seq in manifest.values():
  for eid in seq:
   if not (R/'runs'/eid/'summary.json').exists():continue
   row=audit_episode(eid);results[eid]=row
   if row['changed']:changed.append({'episode':eid,'old_G':row['original_quality']['joint_valid'],'new_G':row['quality']['joint_valid']})
   if len(results)%100==0:print('audited',len(results),flush=True)
 write(R/'analysis/audited_evaluations.json',results);write(R/'qa/evidence_audit.json',{'version':'EVIDENCE_EQUIVALENCE_1','episodes':len(results),'changed':changed,'integrity_errors':sum(len(x['integrity_errors']) for x in results.values()),'rationale':'No source line number was specified. Any nonempty read of the required current module meets that declared observation requirement. Primitive graph pagination and equivalent aggregate SQL are admitted. No task answer or generation was changed.'});print('AUDIT_DONE',len(results),'CHANGED',len(changed))
if __name__=='__main__':main()
