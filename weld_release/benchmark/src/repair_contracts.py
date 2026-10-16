"""R2 contracts: explicit obligations, authenticated reuse, content adjudication."""
import copy,hashlib
from common import *

EXPLANATION_ALIASES={'explanation','interpretation','root_cause_explanation','root_vs_largest_symptom','symptom_vs_root_explanation','root_vs_symptom_explanation','largest_symptom_distinction','log_query_interpretation'}

def evaluate_repaired(task,submission,artifacts,events,native=None):
 from evaluator import evaluate_core,observed
 from evidence_repair import review
 if not isinstance(submission,dict):return evaluate_core(task,submission,artifacts,events,native)
 s=copy.deepcopy(submission);gold=load(ROOT/f"private/{task['id']}.json");texts=[];exrefs=[];labels=[]
 if task['scenario']=='incident':
  answer=s.get('answer',s.get('answers',{}))
  if isinstance(answer,dict):
   for key in list(answer):
    if key in EXPLANATION_ALIASES:
     val=answer.pop(key)
     if isinstance(val,str) and val.strip():texts.append(val)
  if isinstance(s.get('causal_explanation'),str):texts.append(s.pop('causal_explanation'))
 kept=[]
 for c in s.get('claims',[]) if isinstance(s.get('claims',[]),list) else []:
  if not isinstance(c,dict):kept.append(c);continue
  field=c.get('field')
  if task['scenario']=='incident' and field in EXPLANATION_ALIASES:
   if isinstance(c.get('value'),str) and c['value'].strip():texts.append(c['value'])
   exrefs.extend(c.get('evidence',[]) if isinstance(c.get('evidence'),list) else []);continue
  if field not in gold['answer'] and 'value' not in c:
   # A label with only references asserts no additional fact. Preserve its refs.
   labels.append(copy.deepcopy(c));s.setdefault('evidence',[]).extend(c.get('evidence',[]) if isinstance(c.get('evidence'),list) else []);continue
  kept.append(c)
 s['claims']=kept
 result=review(task,s,artifacts,events,native)
 ev=copy.deepcopy(result.get('base_evaluation') or evaluate_core(task,s,artifacts,events,native))
 ev['support_checks']=result.get('support_checks',ev.get('support_checks',{}));ev['claim_checks']=result.get('claim_checks',ev.get('claim_checks',[]))
 contradiction=any(c.get('factual') is False or c.get('support') is False for c in ev['claim_checks'])
 ev['evidence_valid']=bool(ev['support_checks']) and all(ev['support_checks'].values()) and not contradiction and not ev.get('missing_evidence')
 ev['success']=bool(result['reviewed_success']);ev['contract_obligations']={}
 ev['repair_audit']={k:result.get(k) for k in ('aliases_resolved','certified_handoff_ids','minimum_current_execution_satisfied')}
 ev['repair_audit']['reference_only_labels']=labels
 if task['scenario']=='code_review':
  ev['contract_obligations']['minimum_current_execution']=bool(result.get('minimum_current_execution_satisfied'))
  detail=ev.get('evidence_detail',{}).get('impact_resolution',{})
  ev['symbol_existence_valid']=not detail.get('unresolved_symbols')
  if detail.get('relevance_requires_review'):
   ev['status']='ADJUDICATION_NEEDED';ev['repair_audit']['pending_symbol_relevance']=detail['relevance_requires_review']
 if task['scenario']=='incident':
  texts=list(dict.fromkeys(texts));exrefs=exrefs or list(s.get('evidence',[]))
  aliases=result.get('aliases_resolved',{});exrefs=[aliases.get(x,x) for x in exrefs]
  obs,missing,_=observed(exrefs,artifacts,events)
  subject={'task':task['id'],'texts':texts,'evidence_ids':sorted(set(exrefs)),'evidence_hashes':{k:artifacts[k]['content_hash'] for k in sorted(set(exrefs)) if k in artifacts}}
  key=hashlib.sha256(dump(subject).encode()).hexdigest()
  content={'review_key':key,**subject,'present':bool(texts),'grounding_available':bool(obs) and not missing,'status':'MISSING' if not texts else 'PENDING_CONTENT_REVIEW'}
  path=ROOT/'qa/content_decisions.json';decisions=load(path).get('decisions',{}) if path.exists() else {};decision=decisions.get(key)
  if decision:
   content.update(status='PASS' if decision['pass'] else 'FAIL',decision=decision)
  ok=bool(texts) and bool(obs) and not missing and bool(decision and decision['pass'])
  ev['explanation_review']=content;ev['contract_obligations']['explanation']=ok
  if not ok:ev['success']=False
  if texts and not decision:ev['status']='CONTENT_REVIEW_REQUIRED'
  # Preserve nine factual fields and their denominator; explanation is its own obligation.
 ev['task_contract_valid']=bool(ev.get('factual_correct')) and not contradiction and all(ev['contract_obligations'].values()) and ev['status'] not in ('ADJUDICATION_NEEDED','CONTENT_REVIEW_REQUIRED')
 ev['evaluation_policy']='R2_CONTRACT_REPAIR_1'
 return ev
