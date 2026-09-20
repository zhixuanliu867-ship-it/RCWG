"""One fixed two-attempt engineering pilot. No project or spending is implicit."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import re
import time
from .common import ROOT,ApiError,fail,read,digest,sha,integer,SHA,ID,private_path

from .common import canonical as canonical_config

MODEL='gemini-3.1-flash-lite'
BASE='55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278'
PROJECT=re.compile(r'[a-z][a-z0-9-]{4,28}[a-z0-9]\Z')
SERVICE=re.compile(r'[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com\Z')
CONFIG_KEYS={'version','project_id','location','model','pricing','max_input_tokens','output_limits','temperature',
             'thinking_level','request_timeout_s','max_response_bytes','allow_environment_proxy',
             'service_account','login_account','reservation_microusd','ceiling_microusd','max_requests','pilot_profile'}
APPROVAL_KEYS={'approved','manifest_sha256','expires_unix','project_id','service_account',
               'ceiling_microusd','data_location_approved','pricing_rechecked_unix',
               'pr4_delivery_proof_verified','offline_api_acceptance_sha256','owner_note'}

def default_config(project_id: str):
    return {'version':'API001_CONFIG_1','project_id':project_id,'location':'global','model':MODEL,
      'pricing':{'source':'https://cloud.google.com/vertex-ai/generative-ai/pricing','checked_date':'2026-09-19',
                 'currency':'USD','input_usd_per_million':'0.25','output_usd_per_million':'1.50',
                 'scope':'STANDARD_GLOBAL_TEXT_NONCACHED_ESTIMATE_NOT_INVOICE'},
      'max_input_tokens':12288,'output_limits':{'P0.physical':16384,'P1.logical':4096,'P1.physical':12288},
      'temperature':1.0,'thinking_level':'MINIMAL','request_timeout_s':120,'max_response_bytes':1048576,
      'allow_environment_proxy':False,'service_account':None,'login_account':'zhixuanliu867@gmail.com',
      'reservation_microusd':{'countTokens':10000,'generateContent':250000},
      'ceiling_microusd':1000000,'max_requests':{'countTokens':3,'generateContent':3},
      'pilot_profile':'F1_ROOT_CHAIN_PUBLIC_RUNTIME_PROFILE_1'}

def windows_config(host_binding):
    config=default_config('rcwg-509116')
    config.update(version='API001_CONFIG_2_WINDOWS_USER',auth_mode='GCLOUD_USER',principal_type='USER',
                  principal='zhixuanliu867@gmail.com',quota_project='rcwg-509116',transport_host='WINDOWS',
                  transport_backend='NATIVE_PYTHON_HTTPS_PIPE_1',windows_host=deepcopy(host_binding))
    return config

def validate_config(config):
    if type(config) is dict and config.get('version')=='API001_CONFIG_2_WINDOWS_USER':
        extra={'auth_mode','principal_type','principal','quota_project','transport_host','transport_backend','windows_host'}
        if set(config)!=CONFIG_KEYS|extra:fail('CONFIG_FIELDS')
        from .windows_bridge import validate_host
        validate_host(config['windows_host'])
        expected=windows_config(config['windows_host'])
        if canonical_config(config)!=canonical_config(expected):fail('WINDOWS_CONFIG_POLICY_CHANGED')
        return deepcopy(config)
    if type(config) is not dict or set(config)!=CONFIG_KEYS:fail('CONFIG_FIELDS')
    project=config['project_id']
    if type(project) is not str or not PROJECT.fullmatch(project):fail('PROJECT_INVALID')
    expected=default_config(project)
    # Two permitted owner settings: audited environment proxy and existing runner SA.
    for key in CONFIG_KEYS-{'service_account','allow_environment_proxy'}:
        if config[key]!=expected[key] or type(config[key]) is not type(expected[key]):fail('CONFIG_POLICY_CHANGED')
    if type(config['allow_environment_proxy']) is not bool:fail('PROXY_POLICY')
    sa=config['service_account']
    if sa is not None and (type(sa) is not str or not SERVICE.fullmatch(sa) or not sa.endswith('@'+project+'.iam.gserviceaccount.com')):
        fail('SERVICE_ACCOUNT_INVALID')
    return deepcopy(config)

def endpoint(config,kind):
    validate_config(config)
    if kind not in ('countTokens','generateContent'):fail('ENDPOINT_METHOD')
    return ('https://aiplatform.googleapis.com/v1/projects/'+config['project_id']+
            '/locations/global/publishers/google/models/'+MODEL+':'+kind)

def validate_approval(approval,manifest,*,now=None):
    now=int(time.time()) if now is None else now
    user=manifest.get('config',{}).get('auth_mode')=='GCLOUD_USER'
    keys=APPROVAL_KEYS|({'version','auth_mode','principal','windows_host_sha256','windows_acceptance_sha256'} if user else set())
    if type(approval) is not dict or set(approval)!=keys:fail('APPROVAL_FIELDS')
    if user:
        if approval['version']!='API001_APPROVAL_2_WINDOWS_USER' or approval['auth_mode']!='GCLOUD_USER' or approval['principal']!='zhixuanliu867@gmail.com':fail('APPROVAL_PRINCIPAL')
        if approval['windows_host_sha256']!=digest(manifest['config']['windows_host']):fail('APPROVAL_WINDOWS_HOST')
        if type(approval['windows_acceptance_sha256']) is not str or not SHA.fullmatch(approval['windows_acceptance_sha256']):fail('WINDOWS_ACCEPTANCE_REQUIRED')
    config=validate_config(manifest['config'])
    for name in ('approved','data_location_approved','pr4_delivery_proof_verified'):
        if approval[name] is not True:fail('OWNER_APPROVAL_REQUIRED')
    if approval['manifest_sha256']!=digest(manifest):fail('APPROVAL_MANIFEST')
    if approval['project_id']!=config['project_id'] or approval['service_account']!=config['service_account'] or (config['service_account'] is None and not user):
        fail('APPROVAL_PRINCIPAL')
    if type(approval['ceiling_microusd']) is not int or approval['ceiling_microusd']!=config['ceiling_microusd']:fail('APPROVAL_BUDGET')
    if not integer(approval['expires_unix'],now+1,now+86400):fail('APPROVAL_EXPIRED_OR_TOO_LONG')
    if not integer(approval['pricing_rechecked_unix'],now-86400,now):fail('PRICING_RECHECK_REQUIRED')
    if type(approval['offline_api_acceptance_sha256']) is not str or not SHA.fullmatch(approval['offline_api_acceptance_sha256']):
        fail('OFFLINE_ACCEPTANCE_REQUIRED')
    if type(approval['owner_note']) is not str or not approval['owner_note'].strip():fail('OWNER_NOTE_REQUIRED')
    return deepcopy(approval)

def approval_template(manifest):
    result={'approved':False,'manifest_sha256':digest(manifest),'expires_unix':int(time.time())+86400,
        'project_id':manifest['config']['project_id'],'service_account':manifest['config']['service_account'],
        'ceiling_microusd':1000000,'data_location_approved':False,'pricing_rechecked_unix':0,
        'pr4_delivery_proof_verified':False,'offline_api_acceptance_sha256':'','owner_note':''}
    if manifest['config'].get('auth_mode')=='GCLOUD_USER':
        result.update(version='API001_APPROVAL_2_WINDOWS_USER',auth_mode='GCLOUD_USER',principal=manifest['config']['principal'],
                      windows_host_sha256=digest(manifest['config']['windows_host']),windows_acceptance_sha256='')
    return result

def check_exec_sources(root=ROOT):
    pins=read(root/'specs/api001/exec_source_pins.json')
    mismatches=[]
    for name,h in pins['runtime_source_sha256'].items():
        p=root/name
        if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=h:mismatches.append(name)
    if mismatches:fail('EXEC_SOURCE_BASELINE_MISMATCH')
    return pins['head_sha']

def source_snapshot(root=ROOT):
    paths=[]
    for prefix in ('rcwg_api','rcwg_spec','rcwg_exec','rcwg_boot','prompts','specs','configs','tests','scripts','acceptance','.github/workflows','docs/api001'):
        paths.extend(p for p in (root/prefix).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    paths.extend(p for p in (root/'tests').glob('test_api001*.py'))
    paths.extend(p for p in (root/'scripts').glob('*api001*.py'))
    paths.extend(p for p in (root/'acceptance/api001').glob('*.py'))
    paths.extend(root/p for p in ('PROJECT_STATE.md','AGENTS.md','pyproject.toml','uv.lock','.python-version','.gitignore') if (root/p).is_file())
    if any(p.is_symlink() for p in paths):fail('SOURCE_SYMLINK')
    return {str(p.relative_to(root)):sha(p.read_bytes()) for p in sorted(set(paths))}


def check_retained_test_sources(root=ROOT):
    pins=read(root/'specs/api001/retained_test_source_sha256.json')
    for name,h in pins['files_sha256'].items():
        p=root/name
        if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=h:fail('RETAINED_TEST_BYTES_CHANGED')
    return len(pins['files_sha256'])


def check_staged_snapshot(snapshot,root=ROOT):
    import subprocess
    result=subprocess.run(['git','diff','--exit-code','--name-only'],cwd=root,capture_output=True)
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    if result.returncode or not set(snapshot).issubset(set(tracked)):fail('SOURCE_INDEX_MISMATCH')
