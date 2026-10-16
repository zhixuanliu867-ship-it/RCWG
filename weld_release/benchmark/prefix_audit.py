"""Measure whether a correct base's answer/evidence already satisfies an update.
Counterfactual verifier controls only. No new manager calls and no paid requests.
"""
from pathlib import Path
import sys,time
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R));sys.path.insert(0,str(R/'src'))
from common import load,write
from tiered import TierFlow
from audit_grades import audit_episode
def main():
 audits=load(R/'analysis/audited_evaluations.json');manifest=load(R/'qa/matrix_manifest.json');jobs=load(R/'protocol/round1.json')['jobs'];rows=[]
 for j in jobs:
  if j['split']!='main' or not j['task'].endswith('__related'):continue
  if j['prefix_episode'] not in manifest or j['episode'] not in manifest:continue
  baseid=manifest[j['prefix_episode']][-1]
  if not audits[baseid]['quality']['joint_valid']:continue
  eid='PREFIX_CHECK_'+j['episode'];folder=R/'runs'/eid
  if not (folder/'summary.json').exists():
   f=TierFlow(j['task'],eid,4,prefix=R/'runs'/baseid);f.final=load(R/'runs'/baseid/'final_submission.json')
   try:f.finish_flow('COUNTERFACTUAL_PREFIX_ONLY')
   finally:f.close()
  q=audit_episode(eid)['quality'];rows.append({'logical_episode':j['episode'],'base_episode':baseid,'prefix_answer_still_correct':q['Q1_task_correct'],'prefix_evidence_already_sufficient':q['Q2_evidence_state_valid'],'prefix_already_valid':q['joint_valid']})
  if len(rows)%40==0:print('prefix audits',len(rows),flush=True)
 write(R/'analysis/prefix_compatibility.json',rows);print('PREFIX_AUDIT_DONE',len(rows))
if __name__=='__main__':main()
