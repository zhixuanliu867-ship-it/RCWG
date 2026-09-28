"""No-API request/token/cost forecast; unknown is never priced as zero."""
from collections import Counter,defaultdict
from decimal import Decimal
import math
from rcwg_full.evidence import digest


def forecast(slots,*,price_snapshots=None,development_usage=(),semantic_calls=None):
    development_usage=list(development_usage)
    prices=price_snapshots or {};counts=Counter();usage=defaultdict(list)
    for record in development_usage:
        if record.get('split')!='development' or record.get('origin')!='PROVIDER_USAGE':raise ValueError('FORECAST_DEVELOPMENT_USAGE_ONLY')
        if not record.get('request_id') or not record.get('source_hash'):raise ValueError('USAGE_PROVENANCE')
        fields=[record.get('input_tokens'),record.get('output_tokens')]
        if any(type(v) is not int or v<0 for v in fields):raise ValueError('USAGE_TOKEN_FIELDS')
        usage[(record['slot'],record['protocol'],record['stage'])].append(tuple(fields))
    seen=set()
    for slot in slots:
        if slot['slot_id'] in seen:raise ValueError('DUPLICATE_EXPECTED_SLOT')
        seen.add(slot['slot_id'])
        if slot['slot_kind']!='generation':continue
        stages=['physical'] if slot['protocol']=='P0' or slot.get('generation_stage')=='GUIDED_PHYSICAL' else ['logical','physical']
        for stage in stages:counts[(slot['generator'],slot['protocol'],stage,slot['ledger_role'],slot.get('experiment_id'))]+=1
    rows=[]
    for (slot,protocol,stage,role,experiment),count in sorted(counts.items()):
        max_output=16384 if protocol=='P0' else 4096 if stage=='logical' else 12288
        price=prices.get(slot);known=usage.get((slot,protocol,stage),[])
        tokens={'input_upper':count*12288,'output_upper':count*max_output,'origin':'DECLARED_PROTOCOL_UPPER_BOUND',
                'development_observed_requests':len(known),'development_mean_input':sum(v[0] for v in known)/len(known) if known else None,
                'development_mean_output':sum(v[1] for v in known)/len(known) if known else None}
        upper=None;estimated=None
        if price is not None:
            if not {'as_of','source','input_usd_per_million','output_usd_per_million'}<=set(price):raise ValueError('PRICE_SNAPSHOT_FIELDS')
            a,b=[Decimal(str(price[k])) for k in ['input_usd_per_million','output_usd_per_million']]
            if not a.is_finite() or not b.is_finite() or a<0 or b<0:raise ValueError('PRICE_SNAPSHOT_VALUES')
            upper=str((a*tokens['input_upper']+b*tokens['output_upper'])/1000000)
            if known:estimated=str(count*(a*sum(v[0] for v in known)+b*sum(v[1] for v in known))/len(known)/1000000)
        rows.append({'category':'G','slot':slot,'protocol':protocol,'stage':stage,'ledger_role':role,'experiment':experiment,
            'requests_upper_if_reached':count,'requests_lower':0,'tokens':tokens,'price_snapshot_hash':digest(price) if price else None,
            'cost_usd_upper':upper,'cost_usd_development_estimate':estimated,'price_status':'SNAPSHOT_BOUND' if price else 'UNKNOWN',
            'invoice_cost_usd':None,'thinking_billing_bound':'REQUIRES_FROZEN_PROVIDER_CAPABILITY'})
    unknown=[{'category':kind,'requests':None,'cost_usd':None,'status':'UNKNOWN','reason':reason} for kind,reason in [
        ('E','PLAN_DEPENDENT_SEMANTIC_NODE_AND_COUNT_WORK'),('COUNT','FROZEN_PROVIDER_COUNT_POLICY_REQUIRED'),
        ('REFERENCE','ACTUAL_CANDIDATE_SCREEN_AND_CONFIRMATION_USAGE_REQUIRED'),('FIXTURE','DEVELOPMENT_PROBE_POLICY_REQUIRED'),
        ('RETRY','AT_MOST_ONE_FACILITY_RETRY_NOT_AN_AUTHORIZATION'),('CLOUD_CONTROL','ACTUAL_CONTROL_STEP_PRICING_REQUIRED'),
        ('OBJECT_STORAGE','ACTUAL_OBJECT_SIZES_RETENTION_AND_PRICE_REQUIRED')]]
    if semantic_calls is not None:
        if type(semantic_calls) is not dict or not {'lower','upper','scope_hash'}<=set(semantic_calls) or any(type(semantic_calls[k]) is not int or semantic_calls[k]<0 for k in ['lower','upper']) or semantic_calls['lower']>semantic_calls['upper']:raise ValueError('SEMANTIC_CALL_INTERVAL')
        unknown[0].update(requests=semantic_calls,status='ESTIMATED_RANGE',reason='IMPORTED_PLAN_BOUND_RANGE_NOT_PROVIDER_BILLING')
    return {'revision':'FULL001_BUDGET_FORECAST_1','expected_slots_hash':digest(slots),'generation':rows,'other_categories':unknown,
            'G_requests_upper':sum(r['requests_upper_if_reached'] for r in rows),'aggregate_cost_usd':None,
            'aggregate_cost_status':'INCOMPLETE_UNTIL_ALL_REQUIRED_CATEGORIES_KNOWN','development_usage_hash':digest(list(development_usage)),
            'paid_calls_performed':0,'count_calls_performed':0,'execution_authorized':False,'formal_ready':False}
