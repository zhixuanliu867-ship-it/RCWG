from pathlib import Path
import sys,json,copy
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'src'));sys.path.insert(0,str(R))
from common import load,write
from tiered import TierAdapter,TierFlow,covers,eq
from audit_grades import alternative
checks=[]
def check(n,v):checks.append({'name':n,'pass':bool(v)});assert v,n
def observation(a,op,args):
 r=a.call(op,args);assert r['ok'],r
 return {'operation':op,'arguments':args,'data':r['data']}
for tid in ['A10__base','A17__base']:
 t=load(R/'tasks'/f'{tid}.json');g=load(R/'private'/f'{tid}.json');a=TierAdapter(t,'contract');req=g['coverage']['rows'][0];cid=req['id'];native=observation(a,'purchase_summary',{'ids':[cid]})
 if t['dataset']=='chinook':sql=f'SELECT i.CustomerId customer_id,COUNT(DISTINCT i.InvoiceId) order_count,SUM(l.Quantity) item_count,ROUND(SUM(l.UnitPrice*l.Quantity),2) total_amount FROM Invoice i JOIN InvoiceLine l ON i.InvoiceId=l.InvoiceId WHERE i.CustomerId={int(cid)} GROUP BY i.CustomerId'
 else:sql='SELECT o.CustomerID customer_id,COUNT(DISTINCT o.OrderID) order_count,SUM(l.Quantity) item_count,ROUND(SUM(l.UnitPrice*l.Quantity*(1-l.Discount)),2) total_amount FROM Orders o JOIN "Order Details" l ON o.OrderID=l.OrderID WHERE o.CustomerID=\''+cid.replace("'","''")+"' GROUP BY o.CustomerID"
 obs=observation(a,'select',{'sql':sql});check(tid+' equivalent SQL accepted',alternative(req,[obs],g));check(tid+' wrong identity rejected',not alternative(g['coverage']['rows'][1],[obs],g));check(tid+' native summary binds identity',covers(native,req));a.close()
for tid in ['C10__base','C16__base']:
 t=load(R/'tasks'/f'{tid}.json');g=load(R/'private'/f'{tid}.json');a=TierAdapter(t,'contract');k=g['coverage']['verdict'][0];checkname=k['check'];obs=observation(a,'run_checks',{'check_names':[checkname]});check(tid+' test identity accepted',covers(obs,k));bad={**k,'case':'nonexistent'};check(tid+' wrong test rejected',not covers(obs,bad));a.close()
cat=[x for x in load(R/'protocol/task_catalog.json') if x['split']=='main'];check('100 parents',len({x['parent'] for x in cat})==100);check('20 source clusters',len({x['source_cluster'] for x in cat})==20);check('300 condition cards',len(cat)==300)
parents=[x for x in cat if x['r5_condition']=='base'];check('25 easy 75 medium',sum(x['difficulty']=='easy' for x in parents)==25 and sum(x['difficulty']=='medium' for x in parents)==75)
for scene in {x['scenario'] for x in parents}:check(scene+' 20 parents 4 clusters',sum(x['scenario']==scene for x in parents)==20 and len({x['source_cluster'] for x in parents if x['scenario']==scene})==4)
write(R/'qa/expansion_contract_acceptance.json',{'pass':all(x['pass'] for x in checks),'checks':checks});print('EXPANSION_CONTRACTS_PASS',len(checks))
