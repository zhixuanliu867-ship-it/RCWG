"""Closed cloud profile and owner-controlled, hash-pinned authorization records."""
import re,time
from rcwg_spec.common import digest
from .transport import CloudError,PROJECT,BUCKET,RUNTIME,MODEL
from .prompts import PROFILE

PLAN_SHA='68f11740c7242475c2926025cf4bef22495a9877a49bc9503abb069ccf7ffd0c'
OLD_P0_RESULT='68242d53015aa64025ef3f7554b95321d616b96457504db1c3190d6c21121ccf'
HEX=re.compile(r'[0-9a-f]{64}')
def sha(value):
    if type(value) is not str or not HEX.fullmatch(value):raise CloudError('SHA256_INVALID')
    return value
def reference(value,prefix):
    if type(value) is not dict or set(value)!={'object','generation','sha256'}:raise CloudError('OBJECT_REFERENCE_SHAPE')
    if type(value['object']) is not str or not value['object'].startswith(prefix):raise CloudError('OBJECT_REFERENCE_PREFIX')
    from .transport import GCSStore
    GCSStore._key(value['object']);sha(value['sha256'])
    if type(value['generation']) is not str or not re.fullmatch('[1-9][0-9]{0,30}',value['generation']):raise CloudError('OBJECT_REFERENCE_GENERATION')
    return value
def manifest(value,phase,*,now=None):
    now=time.time() if now is None else now
    fields={'version','phase','project_id','region','bucket','runtime_identity','model','model_location','prompt_profile','image_digest','image_source_sha256',
            'approval','created_unix_s','expires_unix_s','inputs','expected_generation_slots','max_generate','max_count','auto_retries','budget_microusd',
            'formal_ready','pricing','c1_review','change_plan_sha256'}
    if type(value) is not dict or set(value)!=fields:raise CloudError('MANIFEST_CLOSED_SHAPE')
    fixed={'version':'CLOUD001_EXPECTED_MANIFEST_1','phase':phase,'project_id':PROJECT,'region':'us-central1','bucket':BUCKET,
           'runtime_identity':RUNTIME,'model':MODEL,'model_location':'global','prompt_profile':PROFILE,'expected_generation_slots':['p0','p1'],
           'max_generate':3 if phase=='live' else 0,'max_count':3 if phase=='live' else 0,'auto_retries':0,'budget_microusd':1000000 if phase=='live' else 0,
           'formal_ready':False,'change_plan_sha256':PLAN_SHA}
    if phase not in ('replay','live') or any(type(value[k]) is not type(v) or value[k]!=v for k,v in fixed.items()):raise CloudError('MANIFEST_FIXED_POLICY')
    if type(value['image_digest']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}',value['image_digest']):raise CloudError('IMAGE_DIGEST_REQUIRED')
    sha(value['image_source_sha256']);reference(value['approval'],'cloud001/approvals/')
    if any(type(value[k]) is not int for k in ('created_unix_s','expires_unix_s')) or not value['created_unix_s']<=now<value['expires_unix_s']<=value['created_unix_s']+7*86400:raise CloudError('MANIFEST_TIME')
    keys={'task','records','recipe'}|({'p0_plan','p1_plan'} if phase=='replay' else set())
    if type(value['inputs']) is not dict or set(value['inputs'])!=keys:raise CloudError('MANIFEST_INPUTS')
    for ref in value['inputs'].values():reference(ref,'cloud001/inputs/')
    if phase=='live':
        reference(value['pricing'],'cloud001/approvals/');reference(value['c1_review'],'cloud001/approvals/')
    elif value['pricing'] is not None or value['c1_review'] is not None:raise CloudError('REPLAY_LIVE_AUTH_UNEXPECTED')
    return value

def authorization(m,approval,pricing=None,c1=None,*,now=None):
    now=time.time() if now is None else now
    expected={'version':'CLOUD001_OWNER_APPROVAL_1','approved':True,'project_id':PROJECT,'owner':'zhixuanliu867@gmail.com','change_plan_sha256':PLAN_SHA,
              'region':'us-central1','working_budget_microusd':5000000,'model_budget_microusd':1000000,'new_batches':1,'generate_max':3,'count_max':3,'auto_retries':0}
    if type(approval) is not dict or set(approval)!=set(expected)|{'approved_unix_s','expires_unix_s','user_message_sha256'} or any(type(approval[k]) is not type(v) or approval[k]!=v for k,v in expected.items()):raise CloudError('OWNER_APPROVAL_REQUIRED')
    sha(approval['user_message_sha256'])
    if any(type(approval[k]) is not int for k in ('approved_unix_s','expires_unix_s')) or not approval['approved_unix_s']<=now<approval['expires_unix_s']<=approval['approved_unix_s']+7*86400:raise CloudError('APPROVAL_EXPIRED')
    if m['expires_unix_s']>approval['expires_unix_s']:raise CloudError('MANIFEST_EXCEEDS_APPROVAL')
    if m['phase']=='live':
        pf={'version':'CLOUD001_OFFICIAL_PRICE_RECHECK_1','model':MODEL,'location':'global','available':True,'input_usd_per_million':'0.25','output_usd_per_million':'1.50'}
        if type(pricing) is not dict or set(pricing)!=set(pf)|{'observed_unix_s','sources'} or any(pricing.get(k)!=v for k,v in pf.items()):raise CloudError('PRICE_OR_MODEL_CHANGED_REAPPROVAL_REQUIRED')
        if type(pricing['observed_unix_s']) is not int or not 0<=now-pricing['observed_unix_s']<=86400:raise CloudError('PRICE_RECHECK_STALE')
        if type(pricing['sources']) is not list or len(pricing['sources'])<2 or any(type(x) is not str or not x.startswith(('https://cloud.google.com/','https://docs.cloud.google.com/')) for x in pricing['sources']):raise CloudError('OFFICIAL_PRICE_SOURCES_REQUIRED')
        if type(c1) is not dict or set(c1)!={'version','status','image_digest','image_source_sha256','replay_manifest_sha256','replay_archive_sha256','platform_execution','p0_result_sha256','p1_static_code','model_dispatches','reviewed_unix_s','formal_ready'}:raise CloudError('C1_REVIEW_SHAPE')
        for k,v in {'version':'CLOUD001_INDEPENDENT_C1_REVIEW_1','status':'C1_CLOUD_REPLAY_ACCEPTED','image_digest':m['image_digest'],'image_source_sha256':m['image_source_sha256'],
                    'p0_result_sha256':OLD_P0_RESULT,'p1_static_code':'REFERENCE_SYNTAX','model_dispatches':0,'formal_ready':False}.items():
            if type(c1.get(k)) is not type(v) or c1[k]!=v:raise CloudError('C1_NOT_ACCEPTED')
        sha(c1['replay_manifest_sha256']);sha(c1['replay_archive_sha256'])
        if type(c1['platform_execution']) is not str or not re.fullmatch('rcwg-cloud001-replay-[a-z0-9-]+',c1['platform_execution']):raise CloudError('C1_EXECUTION_BINDING')
        if type(c1['reviewed_unix_s']) is not int or not approval['approved_unix_s']<=c1['reviewed_unix_s']<=now:raise CloudError('C1_REVIEW_TIME')
    return {'status':'OWNER_AUTHORIZATION_AND_PRECONDITIONS_VALIDATED','authorization_source':'OWNER_WRITABLE_GCS_HASH_PINNED_FROM_JOB_CONFIGURATION',
            'receipt_is_not_a_signature':True,'formal_ready':False}
