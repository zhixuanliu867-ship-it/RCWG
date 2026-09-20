"""Fixed owner authorization scope. No credential values enter this module's records."""
from __future__ import annotations
import os,re,time
from .common import fail

PROJECT='rcwg-509116'
ACCOUNT='zhixuanliu867@gmail.com'
RUNNER='rcwg-api-runner@rcwg-509116.iam.gserviceaccount.com'

def validate_live_binding(config):
    if config.get('auth_mode')=='GCLOUD_USER':
        from .policy import validate_config
        validate_config(config)
        if (config['project_id'],config['login_account'],config['principal'],config['quota_project'],config['service_account'])!=(PROJECT,ACCOUNT,ACCOUNT,PROJECT,None):
            fail('LIVE_IDENTITY_OUTSIDE_AUTHORIZATION')
        return
    if (config['project_id'],config['login_account'],config['service_account'])!=(PROJECT,ACCOUNT,RUNNER):
        fail('LIVE_IDENTITY_OUTSIDE_AUTHORIZATION')

def check_auth_environment(config):
    # Inspect presence only. Do not read referenced files or emit variable values.
    for key in ('CLOUDSDK_AUTH_ACCESS_TOKEN','CLOUDSDK_AUTH_ACCESS_TOKEN_FILE',
                'CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE','GOOGLE_APPLICATION_CREDENTIALS',
                'CLOUDSDK_AUTH_LOGIN_CONFIG_FILE','CLOUDSDK_API_ENDPOINT_OVERRIDES_IAMCREDENTIALS'):
        if os.environ.get(key):fail('AUTH_OVERRIDE_PRESENT')
    impersonation=os.environ.get('CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT')
    if impersonation and impersonation!=config['service_account']:fail('AUTH_OVERRIDE_PRINCIPAL')
    quota=os.environ.get('CLOUDSDK_BILLING_QUOTA_PROJECT')
    if quota and quota!=config['project_id']:fail('AUTH_OVERRIDE_QUOTA_PROJECT')
    if os.environ.get('CLOUDSDK_CORE_LOG_HTTP','').lower() not in ('','false','0','no'):
        fail('AUTH_HTTP_LOGGING_FORBIDDEN')

def safe_failure(returncode,stderr):
    """Extract only allowlisted codes; raw stderr may contain credential material."""
    codes=('PERMISSION_DENIED','UNAUTHENTICATED','SERVICE_DISABLED','NOT_FOUND','RESOURCE_EXHAUSTED')
    raw=stderr if type(stderr) is bytes else b''
    matched=next((c for c in codes if c.encode() in raw),'AUTH_FAILED')
    status=re.search(rb'(?<!\d)(401|403|404|429|500|502|503|504)(?!\d)',raw)
    return {'exit_code':returncode,'error_code':matched,'http_status':int(status[0]) if status else None,
            'request_id':None,'reason':'GCLOUD_FAILED_RAW_STDERR_WITHHELD'}
