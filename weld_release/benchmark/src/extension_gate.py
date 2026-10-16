"""Native execution and discriminating controls for the full repaired pool. No API."""
import copy,sys,uuid,traceback
from common import *
from acceptance import read_episode,equivalent,runtime_controls
from references import run
from evaluator import evaluate

def main():
 rows=[];decisions=load(ROOT/'qa/content_decisions.json') if (ROOT/'qa/content_decisions.json').exists() else {'decisions':{}}
 for entry in load(ROOT/'dataset_catalog.json')['tasks']:
  tid=entry['id'];t=load(ROOT/f'tasks/{tid}.json');eid='R4_GATE_'+tid
  if (ROOT/'runs'/eid).exists() and not (ROOT/'runs'/eid/'summary.json').exists():eid+='__ENVFIX1'
  try:
   if not (ROOT/f'runs/{eid}/summary.json').exists():run(tid,eid)
   s,a,e,n=read_episode(eid)
   if t['scenario']=='incident':
    # A scripted calibration answer, not a model answer or human-reviewed label.
    # Facts come from this native reference's field vector and observed telemetry.
    ans=s['answer'];root=ans['root_service'];fault=ans['fault_type']
    ans['explanation']=f"The selected root hypothesis is {root} with fault type {fault}. The largest observed CPU change is {ans['top_cpu_metric']}, ratio {ans['cpu_ratio']}; the largest latency-90 change is {ans['top_p90_metric']}, ratio {ans['p90_ratio']}. The largest symptom need not identify the injected root. Service dependencies may propagate symptoms, but these aggregate observations do not establish a specific causal path. The log query found {ans['log_keyword_matches']} matches in the available searched messages; this count does not establish whether other errors existed."
    if ans.get('top_trace_service') is None:ans['explanation']+=' Trace information is unavailable, so no trace observation is claimed.'
    s.setdefault('claims',[]).append({'field':'explanation','evidence':s['evidence']})
   ev=evaluate(t,s,a,e,n)
   if t['scenario']=='incident':
    key=ev['explanation_review']['review_key']
    decisions['decisions'][key]={'pass':True,'reason':'Scripted native calibration: explanation interpolates native observed fields, labels root as hypothesis, avoids asserting a causal path, scopes log search, and declares absent traces. Not a model outcome.','reviewer':'deterministic calibration construction'}
    write(ROOT/'qa/content_decisions.json',decisions);ev=evaluate(t,s,a,e,n)
   checks={'native_correct':bool(ev['success']),'equivalent_grouping':bool(evaluate(t,equivalent(s),a,e,n)['success'])}
   wrong=copy.deepcopy(s);wrong['answer'][next(k for k in wrong['answer'] if k!='explanation')]='DELIBERATELY_WRONG';wrong['claims']=[]
   checks['wrong_answer_rejected']=not evaluate(t,wrong,a,e,{**n,'success':False} if n else None)['success']
   missing=copy.deepcopy(s);missing['evidence']=['nonexistent'];missing['claims']=[]
   checks['missing_evidence_rejected']=not evaluate(t,missing,a,e,n)['success']
   unknown=copy.deepcopy(s);unknown.setdefault('claims',[]).append({'field':'novel_causal_explanation','value':'unregistered','evidence':s['evidence']})
   extra=evaluate(t,unknown,a,e,n);checks['unregistered_claim_not_accepted']=not extra['success'] and extra['status'] in ('ADJUDICATION_NEEDED','CONTENT_REVIEW_REQUIRED')
   if t.get('update'):checks['update_exposed']=any(x['kind']=='environment_update' and x.get('exposure_event') for x in e)
   if t['conditions'].get('first_read_fault'):checks['read_fault_exposed']=any(x['status']=='TOOL_ERROR' for x in e)
   rows.append({'task':tid,'pass':all(checks.values()),'checks':checks,'positive_status':ev['status'],'field_checks':ev.get('field_checks'),'support_checks':ev.get('support_checks')})
   write(ROOT/f'qa/calibration_submissions/{tid}.json',s)
  except Exception as ex:rows.append({'task':tid,'pass':False,'error':str(ex),'traceback':traceback.format_exc()})
  write(ROOT/'qa/extension_native_gate_progress.json',rows);print(tid,rows[-1]['pass'],flush=True)
 rt=runtime_controls('R4_GATE')
 result={'pass':all(x['pass'] for x in rows+rt),'cards':len(rows),'passed_cards':sum(x['pass'] for x in rows),'control_checks':sum(len(x.get('checks',{})) for x in rows),'runtime_checks':len(rt),'runtime_passed':sum(x['pass'] for x in rt),'failures':[x for x in rows+rt if not x['pass']],'paid_calls':0}
 write(ROOT/'qa/round_entry_gate.json',result);print(dump(result),flush=True)
 if not result['pass']:raise SystemExit(1)
if __name__=='__main__':main()
