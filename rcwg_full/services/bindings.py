"""No default model guesses: every generator/executor is explicitly bound."""
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlsplit
import re
from rcwg_full.evidence import digest

SLOTS = tuple([f'G{i}' for i in range(6)] + ['E0', 'E1'])
FIELDS = {'slot','role','provider','endpoint','api_version','requested_model','reported_revision',
          'region','account_binding_hash','supported_parameters','max_input_tokens','max_output_tokens',
          'thinking','structured_json','tokenizer','count_method','price_snapshot','data_policy',
          'valid_from','valid_until','decoding','idempotency','template_hash'}


def validate_binding(value, *, live=False, now=None):
    if type(value) is not dict or set(value)!=FIELDS:raise ValueError('SERVICE_BINDING_FIELDS')
    b=deepcopy(value);slot=b['slot']
    if slot not in SLOTS or b['role']!=('GENERATOR' if slot.startswith('G') else 'EXECUTOR'):raise ValueError('SERVICE_SLOT_ROLE')
    if b['provider']!='VERTEX' or b['api_version']!='v1':raise ValueError('SERVICE_PROVIDER_NOT_REGISTERED')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',b['requested_model']):raise ValueError('SERVICE_MODEL')
    url=urlsplit(b['endpoint'])
    if url.scheme!='https' or url.username or url.password or url.query or url.fragment or url.port is not None:
        raise ValueError('SERVICE_ENDPOINT')
    host='aiplatform.googleapis.com' if b['region']=='global' else b['region']+'-aiplatform.googleapis.com'
    path=r'/v1/projects/[a-z][a-z0-9-]{4,61}[a-z0-9]/locations/'+re.escape(b['region'])+r'/publishers/google/models/'+re.escape(b['requested_model'])
    if url.hostname!=host or not re.fullmatch(path,url.path):raise ValueError('SERVICE_ENDPOINT_BINDING')
    if any(not isinstance(b[k],str) or not re.fullmatch('[0-9a-f]{64}',b[k]) for k in ('account_binding_hash','template_hash')):raise ValueError('SERVICE_IDENTITY_HASH')
    if any(type(b[k]) is not int or b[k]<1 for k in ('max_input_tokens','max_output_tokens')):raise ValueError('SERVICE_TOKEN_LIMIT')
    if b['max_input_tokens']<12288 or b['max_output_tokens']<(16384 if slot.startswith('G') else 1):raise ValueError('SERVICE_CAPACITY')
    caps=b['supported_parameters']
    if type(caps) is not dict or set(caps)!={'seed','temperature','top_k','thinking','json'} or any(v not in {'SUPPORTED','UNSUPPORTED','UNKNOWN'} for v in caps.values()):raise ValueError('SERVICE_CAPABILITIES')
    if type(b['decoding']) is not dict or set(b['decoding'])-{'temperature','top_k','thinking'}:raise ValueError('SERVICE_DECODING')
    for key,value in b['decoding'].items():
        if value is not None and caps[key]!='SUPPORTED':raise ValueError('UNSUPPORTED_PARAMETER_REQUESTED')
        if key=='temperature' and value is not None and (type(value) not in {int,float} or not 0<=value<=2):raise ValueError('SERVICE_TEMPERATURE')
        if key=='top_k' and value is not None and (type(value) is not int or value<1):raise ValueError('SERVICE_TOP_K')
    if b['count_method'] not in {'PROVIDER_COUNT','LOCAL_TOKENIZER','UNKNOWN'}:raise ValueError('SERVICE_COUNT_METHOD')
    if b['idempotency'] not in {'UNSUPPORTED','UNKNOWN','REGISTERED_PROVIDER_KEY'}:raise ValueError('SERVICE_IDEMPOTENCY')
    # Provider key support is registered as data, but no header is invented here.
    if b['idempotency']=='REGISTERED_PROVIDER_KEY':raise ValueError('IDEMPOTENCY_ADAPTER_NOT_REGISTERED')
    if live:
        if not b['reported_revision'] or not b['data_policy'] or b['count_method']=='UNKNOWN' or not b['tokenizer']:
            raise PermissionError('SERVICE_NOT_FROZEN')
        if any(v=='UNKNOWN' for v in caps.values()):raise PermissionError('SERVICE_CAPABILITY_UNKNOWN')
        price=b['price_snapshot']
        if type(price) is not dict or not {'as_of','source','input_usd_per_million','output_usd_per_million'}<=set(price):raise PermissionError('PRICE_SNAPSHOT_REQUIRED')
        from decimal import Decimal
        for key in ('input_usd_per_million','output_usd_per_million'):
            number=Decimal(str(price[key]))
            if not number.is_finite() or number<0:raise ValueError('PRICE_SNAPSHOT_VALUE')
        current=now or datetime.now(timezone.utc)
        start=datetime.fromisoformat(b['valid_from'].replace('Z','+00:00'));end=datetime.fromisoformat(b['valid_until'].replace('Z','+00:00'))
        if start.tzinfo is None or end.tzinfo is None or not start<=current<end:raise PermissionError('SERVICE_BINDING_EXPIRED')
    return b


def registry(bindings, *, live=False):
    checked=[validate_binding(b,live=live) for b in bindings]
    if len(checked)!=len(SLOTS) or {b['slot'] for b in checked}!=set(SLOTS):raise ValueError('SIX_GENERATORS_TWO_EXECUTORS_REQUIRED')
    return {'revision':'FULL001_SERVICES_1','bindings':{b['slot']:b for b in checked},'snapshot_hash':digest(checked),'live_validated':live}


def account_hash(config):
    return digest({k:config.get(k) for k in ['auth_mode','project_id','login_account','service_account','location']})
