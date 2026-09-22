"""Normalize frozen slots before reducing observations; missingness is never deletion."""
from collections import Counter, defaultdict
import math
from statistics import fmean
from rcwg_full.evidence import digest

FAMILIES=tuple('F'+str(i) for i in range(1,7))
IDENTITY=('family','template_id','base_id','condition','generator','protocol','trial_label','execution_repeat')
CONTEXT=('source_hash','data_hash','model_snapshot_hash','profile_hash')


def tri_and(*values):
    if any(type(v) is not bool and v is not None for v in values):raise ValueError('INVALID_THREE_VALUE')
    if False in values:return False
    return None if None in values else True


def _positive(value):
    return type(value) in {int,float} and math.isfinite(value) and value>0


def capability(observation, reference=None, threshold=.2):
    """Unknown facility attribution blocks a formal success/plan failure conclusion."""
    if observation is None:
        return {'success':None,'efficient':None,'rho':None,'reference_covered':False,'reason':'MISSING_LOG'}
    status=observation['status'];cause=observation.get('failure_class')
    if cause in {'INFRASTRUCTURE','UNRESOLVED'} or status in {'INFRA_FAILURE','UNKNOWN','SENT_UNCONFIRMED','CANCELLED','NOT_RUN'}:
        success=None
    elif status in {'MODEL_FAILURE','PLAN_INVALID','NOT_RUN_UPSTREAM_PLAN_FAILURE'} and cause=='CONFIRMED_PLAN':
        success=False
    elif status in {'TIMEOUT','OOM'}:
        success=False if observation.get('budget_failure_confirmed') is True else None
    else:
        success=tri_and(observation.get('semantic'),observation.get('budget'))
        if observation.get('evidence_valid') is not True:success=None
    covered=bool(reference and reference.get('confirmed') is True and _positive(reference.get('elapsed_ns'))
                 and reference.get('context_hash')==observation.get('comparison_context_hash'))
    complete=status=='COMPLETED' and observation.get('timing_valid') is True and _positive(observation.get('exec_elapsed_ns'))
    rho=observation['exec_elapsed_ns']/reference['elapsed_ns'] if success is True and complete and covered else None
    efficient=False if success is False else (rho<=1+threshold if rho is not None else None)
    return {'success':success,'efficient':efficient,'rho':rho,'reference_covered':covered,
            'completed_time_ns':observation.get('exec_elapsed_ns') if complete else None,
            'censored':status in {'TIMEOUT','OOM'},'observed_elapsed_ns':observation.get('exec_elapsed_ns'),
            'reason':status,'measurement_valid':observation.get('evidence_valid') is True}


def normalize(expected, observations, references=None, *, mode='ENGINEERING_NATIVE', ledger_role='PRIMARY'):
    """Select at most one reconciled facility retry per frozen logical execution slot."""
    references=references or {};slots={};attempts=defaultdict(list);seen=set();excluded=[]
    for slot in expected:
        if slot['slot_id'] in slots:raise ValueError('DUPLICATE_EXPECTED_SLOT')
        slots[slot['slot_id']]=slot
    for item in observations:
        if item['attempt_id'] in seen:raise ValueError('DUPLICATE_ATTEMPT_RECORD')
        seen.add(item['attempt_id'])
        if item['slot_id'] not in slots:raise ValueError('UNEXPECTED_SLOT')
        if item.get('ledger_role')=='TIMING_CONFIRMATION':excluded.append(item['attempt_id']);continue
        slot=slots[item['slot_id']]
        if item.get('mode')!=mode:raise ValueError('MODE_CONTAMINATION')
        if any(item.get(key)!=slot.get(key) for key in IDENTITY):raise ValueError('PAIRING_IDENTITY_MISMATCH')
        if any(key in slot and item.get(key)!=slot[key] for key in CONTEXT):raise ValueError('FROZEN_CONTEXT_MISMATCH')
        attempts[item['slot_id']].append(item)
    rows=[];missing=[]
    for slot in slots.values():
        if slot.get('slot_kind')!='execution' or slot.get('ledger_role')!=ledger_role:continue
        candidates=attempts[slot['slot_id']]
        if len(candidates)>2:raise ValueError('RETRY_LIMIT')
        selected=None
        if candidates:
            primary=[r for r in candidates if r.get('ledger_role')==ledger_role and r.get('parent_attempt_id') is None]
            if len(primary)!=1:raise ValueError('PRIMARY_ATTEMPT_AMBIGUOUS')
            selected=primary[0]
            if len(candidates)==2:
                retry=next(r for r in candidates if r is not selected)
                if (retry.get('ledger_role')!='INFRA_RETRY' or retry.get('parent_attempt_id')!=selected['attempt_id']
                    or selected['status']!='INFRA_FAILURE' or retry.get('reconciliation')!={'worker_stopped':True,'request_uncertain':False}):
                    raise ValueError('RETRY_NOT_EQUIVALENT')
                if any(retry.get(k)!=selected.get(k) for k in (*CONTEXT,'plan_hash','comparison_context_hash')):
                    raise ValueError('RETRY_CONTEXT_CHANGED')
                selected=retry
        else:missing.append(slot['slot_id'])
        context={k:selected[k] for k in (*CONTEXT,'comparison_context_hash','plan_hash','c0_source_plan_hash') if selected and k in selected}
        rows.append({**slot,**context,**capability(selected,references.get(slot.get('task_id'))),
                     'selected_attempt':selected['attempt_id'] if selected else None,
                     'attempt_count':len(candidates),'observed_status':selected['status'] if selected else 'MISSING_LOG'})
    return {'rows':rows,'missing_log_ids':missing,'excluded_timing_attempts':excluded,
            'expected_manifest_hash':digest(expected),'observation_hash':digest(observations),
            'evidence_integrity':'FAIL' if missing else 'PASS','mode':mode,'formal_ready':False}


def common_reference_domain(expected,references,*,mode='ENGINEERING_NATIVE'):
    """Select from frozen task/measurement bindings, never successful responses."""
    methods=defaultdict(set);by_task=defaultdict(list)
    for slot in expected:
        if slot.get('slot_kind')=='execution' and slot.get('ledger_role')=='PRIMARY':
            methods[(slot['generator'],slot['protocol'])].add(slot['task_id']);by_task[slot['task_id']].append(slot)
    common=set.intersection(*methods.values()) if methods else set();covered=set()
    for task in common:
        reference=references.get(task,{})
        if reference.get('confirmed') is not True or not _positive(reference.get('elapsed_ns')) or not reference.get('context_hash'):continue
        contexts={s.get('comparison_context_hash') for s in by_task[task]}
        if mode=='FORMAL' and None in contexts:raise ValueError('FROZEN_REFERENCE_CONTEXT_REQUIRED')
        if contexts-{None,reference['context_hash']}:continue
        covered.add(task)
    return covered


def template_means(rows, metric, unknown_value):
    if metric not in {'success','efficient'} or unknown_value not in (0,1):raise ValueError('METRIC_INPUT')
    current=[]
    for row in rows:
        value=row[metric]
        if type(value) is not bool and value is not None:raise ValueError('INVALID_THREE_VALUE')
        current.append({**row,'value':unknown_value if value is None else int(value)})
    # Mean repeats, then trials, conditions and bases, in that order. Methods are
    # intentionally not keys: callers must select one frozen method/model first.
    keys=['family','template_id','base_id','condition','trial_label']
    for _ in range(4):
        groups=defaultdict(list)
        for row in current:groups[tuple(row[k] for k in keys)].append(row['value'])
        current=[{**dict(zip(keys,key)),'value':fmean(values)} for key,values in groups.items()]
        keys.pop()
    return {(r['family'],r['template_id']):r['value'] for r in current}


def macro(values, *, families=FAMILIES):
    grouped=defaultdict(list)
    for (family,_),value in values.items():grouped[family].append(value)
    if set(grouped)!=set(families):raise ValueError('FAMILY_COVERAGE_MISMATCH')
    return fmean(fmean(grouped[family]) for family in families)


def summarize(rows, metric='success', *, families=FAMILIES, evidence_integrity='PASS'):
    methods={(r.get('generator'),r.get('protocol'),r.get('arm')) for r in rows}
    if len(methods)!=1:raise ValueError('SELECT_ONE_METHOD')
    lower=macro(template_means(rows,metric,0),families=families)
    upper=macro(template_means(rows,metric,1),families=families)
    unknown=sum(r[metric] is None for r in rows)
    return {'metric':metric,'point':lower if not unknown and evidence_integrity=='PASS' else None,
            'identification_lower':lower,'identification_upper':upper,
            'interval_kind':'FIXED_DENOMINATOR_IDENTIFICATION_NOT_CONFIDENCE',
            'denominator':len(rows),'unknown':unknown,'known_false':sum(r[metric] is False for r in rows),
            'reference_coverage':sum(r['reference_covered'] for r in rows),
            'statuses':dict(Counter(r['observed_status'] for r in rows)),
            'hierarchy':['execution_repeat','trial_label','condition','base_id','template_id','family_macro'],
            'evidence_integrity':evidence_integrity}


def pair_e2(adaptive, frozen):
    keys=('task_id','generator','protocol','trial_label','execution_repeat')
    def keyed(rows):
        result={tuple(r[k] for k in keys):r for r in rows}
        if len(result)!=len(rows):raise ValueError('DUPLICATE_E2_PAIR')
        return result
    left,right=keyed(adaptive),keyed(frozen)
    if left.keys()!=right.keys():raise ValueError('E2_PAIR_MISMATCH')
    for key in left:
        a,b=left[key],right[key]
        if (a['condition']!=b['condition'] or b['condition']=='C0'
            or b.get('plan_hash')!=b.get('c0_source_plan_hash')
            or not b.get('c0_source_plan_hash')
            or any(a.get(k)!=b.get(k) for k in ('data_hash','profile_hash','model_snapshot_hash'))):
            raise ValueError('E2_FROZEN_BINDING_MISMATCH')
    return [(left[key],right[key]) for key in sorted(left)]


def frontier(rows, fields):
    """A vector partial order only over complete measured successful observations."""
    if not fields or len(set(fields))!=len(fields):raise ValueError('FRONTIER_FIELDS')
    eligible=[r for r in rows if r.get('success') is True and all(
        r.get('measurement',{}).get(k)=='MEASURED' and type(r.get(k)) in {int,float}
        and math.isfinite(r[k]) and r[k]>=0 for k in fields)]
    return [r for r in eligible if not any(all(q[k]<=r[k] for k in fields) and any(q[k]<r[k] for k in fields) for q in eligible)]
