"""WIN-01 trusted native helper. Fixed USER / project / endpoint; stdlib only.

This executable has no fake/live switch. Test doubles are injected only by unit
tests importing the module, never by its pipe protocol or command line.
"""
from __future__ import annotations
import base64
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION='API001_WINDOWS_PIPE_1'
PROJECT='rcwg-509116'
ACCOUNT='zhixuanliu867@gmail.com'
MODEL='gemini-3.1-flash-lite'
SHA=re.compile(r'[0-9a-f]{64}\Z')
ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z')
METHODS={'countTokens':10000,'generateContent':250000}
MAX_PIPE=1800000
MAX_BODY=131072
MAX_RESPONSE=1048576
BINDING_KEYS={'python_executable','python_sha256','python_version','helper_path','helper_sha256',
              'gcloud_entry','gcloud_entry_sha256','sdk_version','proxy','tls_trust'}
SAFE_HEADERS={'x-request-id','x-goog-request-id','content-type','retry-after'}

class BridgeError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)
def fail(code):raise BridgeError(code) from None
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(obj):
    try:return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (ValueError,TypeError,UnicodeError,RecursionError):fail('JSON_INVALID')
def digest(obj):return sha(encode(obj))
def strict(raw,limit=MAX_PIPE):
    if type(raw) is not bytes or not 0<len(raw)<=limit:fail('PIPE_BYTE_LIMIT')
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result:fail('JSON_DUPLICATE_KEY')
            result[key]=value
        return result
    def number(value):
        value=float(value)
        if not math.isfinite(value):fail('JSON_NONFINITE')
        return value
    def constant(_):fail('JSON_NONFINITE')
    try:return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_float=number,parse_constant=constant)
    except BridgeError:raise
    except (ValueError,UnicodeError,RecursionError,OverflowError):fail('JSON_INVALID')
def unbase(value,limit):
    if type(value) is not str or len(value)>4*((limit+2)//3):fail('BASE64_LIMIT')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,TypeError):fail('BASE64_INVALID')
    if len(raw)>limit or base64.b64encode(raw).decode()!=value:fail('BASE64_INVALID')
    return raw
def path_check(value,suffix):
    if type(value) is not str or not PureWindowsPath(value).is_absolute() or len(value)>1024:fail('HOST_PATH')
    if PureWindowsPath(value).drive.lower()!='c:' or '..' in PureWindowsPath(value).parts or re.search(r'["%&|<>^;\r\n\x00]',value):fail('HOST_PATH')
    if not value.lower().endswith(suffix):fail('HOST_PATH')
def validate_binding(binding):
    if type(binding) is not dict or set(binding)!=BINDING_KEYS:fail('HOST_BINDING_FIELDS')
    for name,suffix in [('python_executable','python.exe'),('helper_path','api001_bridge.py'),('gcloud_entry','gcloud.cmd')]:path_check(binding[name],suffix)
    for key in ('python_sha256','helper_sha256','gcloud_entry_sha256'):
        if type(binding[key]) is not str or not SHA.fullmatch(binding[key]):fail('HOST_HASH')
    if type(binding['python_version']) is not str or not re.fullmatch(r'3\.(12|13)\.[0-9]+',binding['python_version']):fail('HOST_PYTHON_VERSION')
    if type(binding['sdk_version']) is not str or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',binding['sdk_version']):fail('HOST_SDK_VERSION')
    if binding['proxy']!={'type':'http','address':'127.0.0.1','port':'10090'}:fail('PROXY_BINDING')
    if binding['tls_trust']!='WINDOWS_DEFAULT_VERIFIED_TLS':fail('TLS_BINDING')
    return binding
def validate_envelope(value):
    keys={'version','operation','manifest_sha256','request_id','kind','body_b64','body_sha256','reservation','host_binding','config_sha256'}
    if type(value) is not dict or set(value)!=keys or value['version']!=VERSION:fail('ENVELOPE_FIELDS')
    validate_binding(value['host_binding'])
    for key in ('manifest_sha256','config_sha256','body_sha256'):
        if type(value[key]) is not str or not SHA.fullmatch(value[key]):fail('ENVELOPE_HASH')
    if type(value['request_id']) is not str or not ID.fullmatch(value['request_id']):fail('REQUEST_ID')
    raw=unbase(value['body_b64'],MAX_BODY)
    if sha(raw)!=value['body_sha256']:fail('REQUEST_HASH')
    if value['operation']=='preflight':
        if value['kind'] is not None or raw!=b'' or value['reservation'] is not None:fail('PREFLIGHT_FIELDS')
    elif value['operation']=='send':
        if value['kind'] not in METHODS:fail('ENDPOINT_METHOD')
        if type(strict(raw,MAX_BODY)) is not dict:fail('REQUEST_JSON')
        desired={'request_id':value['request_id'],'kind':value['kind'],'amount_microusd':METHODS[value['kind']],
                 'reserved_before_io':True,'manifest_sha256':value['manifest_sha256'],'mode':'LIVE'}
        if type(value['reservation']) is not dict or encode(value['reservation'])!=encode(desired):fail('RESERVATION_BINDING')
    else:fail('PIPE_OPERATION')
    return raw
def classify(raw):
    for needle,code in ((b'SERVICE_DISABLED','SERVICE_DISABLED'),(b'PERMISSION_DENIED','PERMISSION_DENIED'),
                        (b'UNAUTHENTICATED','UNAUTHENTICATED'),(b'invalid_grant','USER_LOGIN_REFRESH_FAILED'),
                        (b'ProxyError','PROXY_CONNECTION_FAILED'),(b'Connection refused','PROXY_CONNECTION_REFUSED'),
                        (b'CERTIFICATE_VERIFY_FAILED','TLS_CERTIFICATE_FAILED'),(b'has no property','GCLOUD_UNSUPPORTED_LOCAL_PROPERTY')):
        if needle in raw:return code
    return 'GCLOUD_FAILED_RAW_WITHHELD'
def native_command(binding,args,resource=False):
    # Args originate exclusively from constants in this module, never the model.
    argv=[binding['gcloud_entry'],*args,'--project='+PROJECT,'--account='+ACCOUNT,
          *(['--billing-project='+PROJECT] if resource else []),'--quiet','--verbosity=warning']
    command='"'+str(Path(os.environ['SystemRoot'])/'System32/cmd.exe')+'" /d /s /c "'+subprocess.list2cmdline(argv)+'"'
    return argv,command
def sdk_call(binding,args,audit,resource=False):
    argv,command=native_command(binding,args,resource)
    record={'argv':argv,'operation':'SHORT_LIVED_CREDENTIAL_ISSUANCE' if args==['auth','print-access-token'] else 'LOCAL_METADATA',
            'project_id':PROJECT,'login_account':ACCOUNT,'service_account':None,'auth_mode':'GCLOUD_USER',
            'principal_type':'USER','credential_http_requests':None,'started_unix_ns':time.time_ns()}
    audit.append(record)
    try:r=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45,check=False)
    except subprocess.TimeoutExpired:record['error_code']='GCLOUD_TIMEOUT';fail('GCLOUD_TIMEOUT')
    except OSError:record['error_code']='GCLOUD_START_FAILED';fail('GCLOUD_START_FAILED')
    record['exit_code']=r.returncode
    if r.returncode:record['error_code']=classify(r.stderr);fail(record['error_code'])
    if len(r.stdout)>65536:fail('GCLOUD_OUTPUT_LIMIT')
    return r.stdout,record
def native_host(binding):
    if os.name!='nt' or sys.platform!='win32':fail('NATIVE_WINDOWS_REQUIRED')
    if str(Path(sys.executable).resolve()).casefold()!=str(Path(binding['python_executable']).resolve()).casefold():fail('HOST_RUNTIME_PATH')
    if str(Path(__file__).resolve()).casefold()!=str(Path(binding['helper_path']).resolve()).casefold():fail('HOST_HELPER_PATH')
    for pathkey,hashkey in [('python_executable','python_sha256'),('helper_path','helper_sha256'),('gcloud_entry','gcloud_entry_sha256')]:
        path=Path(binding[pathkey])
        if path.is_symlink() or sha(path.read_bytes())!=binding[hashkey]:fail('DEPLOYED_SOURCE_CHANGED')
    if platform.python_version()!=binding['python_version']:fail('HOST_RUNTIME_VERSION')
    return {'os':'nt','platform':sys.platform,'pid':os.getpid(),'python_version':platform.python_version(),
            'python_executable':str(Path(sys.executable).resolve()),'clock_scope':'WINDOWS_PID_'+str(os.getpid())+'_PERF_COUNTER',
            'host_binding_sha256':digest(binding),'helper_sha256':binding['helper_sha256']}
def auth_preflight(binding,audit):
    forbidden=('CLOUDSDK_AUTH_ACCESS_TOKEN','CLOUDSDK_AUTH_ACCESS_TOKEN_FILE','CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE',
       'GOOGLE_APPLICATION_CREDENTIALS','CLOUDSDK_AUTH_LOGIN_CONFIG_FILE','CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT',
       'CLOUDSDK_API_ENDPOINT_OVERRIDES_AIPLATFORM','CLOUDSDK_API_ENDPOINT_OVERRIDES_IAMCREDENTIALS',
       'CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE','SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE')
    if any(os.environ.get(k) for k in forbidden):fail('WINDOWS_AUTH_OR_TLS_OVERRIDE_PRESENT')
    props={'auth/credential_file_override':None,'auth/access_token_file':None,'auth/impersonate_service_account':None,
        'auth/login_config_file':None,'api_endpoint_overrides/aiplatform':None,'api_endpoint_overrides/iamcredentials':None,
        'core/custom_ca_certs_file':None,'proxy/username':None,'proxy/password':None,
        'core/log_http':'false','auth/disable_ssl_validation':'false','auth/disable_credentials':'false',
        'auth/token_host':'https://oauth2.googleapis.com/token','auth/mtls_token_host':'https://oauth2.mtls.googleapis.com/token','billing/quota_project':PROJECT,
        'proxy/type':'http','proxy/address':'127.0.0.1','proxy/port':'10090'}
    for prop,expected in props.items():
        raw,record=sdk_call(binding,['config','get-value',prop],audit)
        try:value=raw.decode('utf-8').strip()
        except UnicodeError:fail('GCLOUD_METADATA_ENCODING')
        present=value not in ('','(unset)');record.update(property=prop,present=present)
        if expected is None:valid=not present
        elif prop.startswith('proxy/') or prop in ('auth/token_host','auth/mtls_token_host'):valid=value==expected
        elif prop=='billing/quota_project':valid=not present or value in (PROJECT,'CURRENT_PROJECT')
        else:valid=not present or value.lower()=='false'
        record['matches_authorized_value']=valid
        if not valid:fail('WINDOWS_EFFECTIVE_CONFIG_MISMATCH')
    raw,_=sdk_call(binding,['auth','list','--filter=account:'+ACCOUNT,'--format=json(account,status)'],audit)
    accounts=strict(raw)
    if type(accounts) is not list or not any(type(x) is dict and x.get('account')==ACCOUNT for x in accounts):fail('USER_NOT_LOGGED_IN')
    raw,_=sdk_call(binding,['version','--format=json'],audit)
    if strict(raw).get('Google Cloud SDK')!=binding['sdk_version']:fail('HOST_SDK_VERSION_CHANGED')
    return {'principal':ACCOUNT,'principal_type':'USER','auth_mode':'GCLOUD_USER','project_id':PROJECT,
            'quota_project':PROJECT,'service_account':None,'proxy':binding['proxy'],'tls_trust':binding['tls_trust']}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):fail('HTTP_REDIRECT_DENIED')
def post(kind,raw,token,binding):
    url='https://aiplatform.googleapis.com/v1/projects/'+PROJECT+'/locations/global/publishers/google/models/'+MODEL+':'+kind
    context=ssl.create_default_context()
    if context.verify_mode!=ssl.CERT_REQUIRED or not context.check_hostname:fail('TLS_VALIDATION_REQUIRED')
    # Explicit SDK-matched proxy. Environment no_proxy must not bypass it.
    handler=urllib.request.ProxyHandler({})
    opener=urllib.request.build_opener(handler,NoRedirect(),urllib.request.HTTPSHandler(context=context))
    req=urllib.request.Request(url,data=raw,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
        'Accept':'application/json','Accept-Encoding':'identity','Host':'aiplatform.googleapis.com','x-goog-user-project':PROJECT},method='POST')
    req.set_proxy(binding['proxy']['address']+':'+binding['proxy']['port'],'http')
    started=time.perf_counter_ns()
    try:
        try:response=opener.open(req,timeout=120)
        except urllib.error.HTTPError as error:response=error
        with response:
            chunks=[];size=0
            while True:
                remaining=120-(time.perf_counter_ns()-started)/1_000_000_000
                if remaining<=0:fail('HTTP_DEADLINE_EXCEEDED')
                # The socket timeout shrinks with the same-host monotonic deadline.
                sock=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
                if sock is not None:sock.settimeout(remaining)
                chunk=response.read(min(65536,MAX_RESPONSE+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>MAX_RESPONSE:fail('RESPONSE_BYTE_LIMIT')
            data=b''.join(chunks);status=response.code
            headers={k.lower():v for k,v in response.headers.items() if k.lower() in SAFE_HEADERS}
        if len(data)>MAX_RESPONSE:fail('RESPONSE_BYTE_LIMIT')
        if time.perf_counter_ns()-started>120_000_000_000:fail('HTTP_DEADLINE_EXCEEDED')
        if 300<=status<400:fail('HTTP_REDIRECT_DENIED')
        if token.encode() in data or any(token in v for v in headers.values()):fail('SECRET_ECHO_WITHHELD')
        return status,data,headers,time.perf_counter_ns()-started
    except BridgeError:raise
    except (TimeoutError,urllib.error.URLError,OSError):fail('HTTP_TRANSPORT_UNCERTAIN_NO_RETRY')
def handle(value,emit):
    raw=validate_envelope(value);binding=value['host_binding'];auth=[];dispatched=False
    result={'version':VERSION,'event':'RESULT','manifest_sha256':value['manifest_sha256'],'config_sha256':value['config_sha256'],
            'request_id':value['request_id'],'kind':value['kind'],'request_sha256':value['body_sha256'],
            'reservation_sha256':digest(value['reservation']),'host':None,'auth':auth,'identity':None,
            'started_unix_ns':time.time_ns(),'dispatch_attempted':False,'provider_receipt':'NOT_DISPATCHED',
            'transport_retry_index':0,'status':'PREFLIGHT_OK','http_status':None,'response_b64':None,
            'response_sha256':None,'headers':{},'http_elapsed_ns':None,'error_code':None}
    started=time.perf_counter_ns()
    try:
        result['host']=native_host(binding);result['identity']=auth_preflight(binding,auth)
        if value['operation']=='send':
            token_raw,issued=sdk_call(binding,['auth','print-access-token'],auth,True)
            try:token=token_raw.decode('ascii').strip()
            except UnicodeError:fail('USER_TOKEN_INVALID')
            if not 20<=len(token)<=8192 or re.search(r'\s',token):fail('USER_TOKEN_INVALID')
            issued['status']='CREDENTIAL_CAPTURED_IN_WINDOWS_MEMORY'
            marker={k:result[k] for k in ('version','manifest_sha256','config_sha256','request_id','kind','request_sha256','reservation_sha256','host')}
            marker['event']='DISPATCHING';emit(marker)
            dispatched=True
            status,data,headers,elapsed=post(value['kind'],raw,token,binding)
            result.update(status='HTTP_OBSERVED',http_status=status,response_b64=base64.b64encode(data).decode('ascii'),
                          response_sha256=sha(data),headers=headers,http_elapsed_ns=elapsed,provider_receipt='HTTP_RESPONSE_OBSERVED')
    except BridgeError as error:
        result.update(status='FAILED',error_code=error.code,provider_receipt='UNKNOWN' if dispatched else 'NOT_DISPATCHED')
    except Exception:
        result.update(status='FAILED',error_code='WINDOWS_HELPER_INTERNAL_ERROR',provider_receipt='UNKNOWN' if dispatched else 'NOT_DISPATCHED')
    result.update(dispatch_attempted=dispatched,helper_elapsed_ns=time.perf_counter_ns()-started)
    return result
def main():
    def emit(value):sys.stdout.buffer.write(encode(value)+b'\n');sys.stdout.buffer.flush()
    try:
        if len(sys.argv)!=1:fail('NO_HELPER_ARGUMENTS_ALLOWED')
        value=strict(sys.stdin.buffer.read(MAX_PIPE+1));validate_envelope(value)
        result=handle(value,emit);emit(result)
        return 0
    except Exception as error:
        code=error.code if type(error) is BridgeError else 'WINDOWS_PIPE_INVALID'
        emit({'version':VERSION,'event':'REJECTED','error_code':code,'dispatch_attempted':False})
        return 2
if __name__=='__main__':raise SystemExit(main())
