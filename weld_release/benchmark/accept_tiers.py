from pathlib import Path
import sys,copy,json,time,concurrent.futures
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'src'))
from common import load,write
from tiered import TierFlow
stamp=str(int(time.time()))
def test_parent(parent):
 results=[];prefix=None
 for cond in ['base','related','unrelated']:
  tid=parent+'__'+cond;plan=load(R/f'private/reference_plans/{tid}.json');eid='QA_'+stamp+'_'+tid
  flow=TierFlow(tid,eid,4,prefix=prefix if cond!='base' else None)
  for action in plan:flow.execute(action)
  s=flow.finish_flow('SCRIPTED_CONTROL');results.append({'task':tid,'control':'correct','pass':s['quality']['joint_valid'],'work':s['work']})
  if cond=='base':prefix=R/'runs'/eid
  # A false output or invalid state must fail the gate.
  if flow.task['scenario']=='appworld':flow.final={'answer':{'completion':'not_done'}}
  else:flow.final={'answer':{}}
  q=flow.grade();results.append({'task':tid,'control':'incorrect','pass':not q['joint_valid']})
  flow.close()
 # Work-changing but result-preserving control on the initial task.
 tid=parent+'__base';plan=load(R/f'private/reference_plans/{tid}.json');f=TierFlow(tid,'QA_DUP_'+stamp+'_'+parent,4)
 f.execute(plan[0]);second=copy.deepcopy(plan[0]);
 for n in second['nodes']:n['id']='again_'+n['id']
 f.execute(second);f.execute(plan[-1]);s=f.finish_flow('SCRIPTED_DUPLICATION_CONTROL')
 basework=results[0]['work']['tool_attempts'];results.append({'task':tid,'control':'same_answer_extra_work','pass':s['quality']['joint_valid'] and s['work']['tool_attempts']==2*basework});f.close()
 return results
if __name__=='__main__':
 parents=list(dict.fromkeys(x['parent'] for x in load(R/'protocol/task_catalog.json')));results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
  for rows in ex.map(test_parent,parents):
   results+=rows;print(rows[0]['task'],all(x['pass'] for x in rows),flush=True)
 write(R/'qa/tier_acceptance.json',{'pass':all(x['pass'] for x in results),'checks':results,'count':len(results)})
 assert all(x['pass'] for x in results),[x for x in results if not x['pass']]
