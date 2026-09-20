"""Bound WSL orchestration to a native Windows USER/HTTPS subprocess.

Only original request/response bytes cross this pipe. Credentials remain in the
native helper. The durable reservation is made by pilot.py before invoke().
"""
from __future__ import annotations
import base64
from copy import deepcopy
import os
from pathlib import Path,PureWindowsPath
import subprocess
import time
from .common import ROOT,ApiError,fail,canonical,strict,sha,digest
from . import windows_helper as protocol
from .policy import validate_config
from .vertex import Response

def wsl_path(value):
    protocol.path_check(value,'')
    p=PureWindowsPath(value)
    return Path('/mnt/c').joinpath(*p.parts[1:])
def validate_host(binding,*,files=False):
    try:protocol.validate_binding(binding)
    except protocol.BridgeError as error:fail(error.code)
    source=ROOT/'rcwg_api/windows_helper.py'
    if sha(source.read_bytes())!=binding['helper_sha256']:fail('HELPER_SOURCE_BINDING')
    if files:
        for pathkey,hashkey in [('python_executable','python_sha256'),('helper_path','helper_sha256'),('gcloud_entry','gcloud_entry_sha256')]:
            path=wsl_path(binding[pathkey])
            if not path.is_file() or path.is_symlink() or sha(path.read_bytes())!=binding[hashkey]:fail('WINDOWS_DEPLOYMENT_CHANGED')
    return deepcopy(binding)
def envelope(config,manifest_hash,request_id,kind,body,reservation):
    value={'version':protocol.VERSION,'operation':'preflight' if kind is None else 'send',
           'manifest_sha256':manifest_hash,'config_sha256':digest(config),'request_id':request_id,'kind':kind,
           'body_b64':base64.b64encode(body).decode('ascii'),'body_sha256':sha(body),
           'reservation':reservation,'host_binding':config['windows_host']}
    try:protocol.validate_envelope(value)
    except protocol.BridgeError as error:fail(error.code)
    return value
def check_event(event,value):
    for key in ('version','manifest_sha256','config_sha256','request_id','kind'):
        if event.get(key)!=value[key]:fail('BRIDGE_RECEIPT_BINDING')
    if event.get('request_sha256')!=value['body_sha256'] or event.get('reservation_sha256')!=digest(value['reservation']):fail('BRIDGE_RECEIPT_HASH')
    host=event.get('host')
    if type(host) is not dict or host.get('os')!='nt' or host.get('platform')!='win32' or type(host.get('pid')) is not int or host['pid']<=0:fail('BRIDGE_HOST_RECEIPT')
    binding=value['host_binding']
    if host.get('host_binding_sha256')!=digest(binding) or host.get('helper_sha256')!=binding['helper_sha256'] or host.get('python_version')!=binding['python_version']:fail('BRIDGE_HOST_BINDING')
    if host.get('python_executable','').replace('/','\\').casefold()!=binding['python_executable'].replace('/','\\').casefold():fail('BRIDGE_HOST_RUNTIME')
    if host.get('clock_scope')!='WINDOWS_PID_'+str(host['pid'])+'_PERF_COUNTER':fail('BRIDGE_CLOCK_SCOPE')
def decode_result(raw,value):
    if type(raw) is not bytes or len(raw)>protocol.MAX_PIPE:fail('BRIDGE_OUTPUT_LIMIT')
    lines=raw.splitlines()
    if not 1<=len(lines)<=2:fail('BRIDGE_PROTOCOL_LINES')
    events=[strict(line,limit=protocol.MAX_PIPE) for line in lines]
    for event in events:
        if type(event) is not dict:fail('BRIDGE_PROTOCOL_EVENT')
        check_event(event,value)
    result=events[-1]
    if 'synthetic_fixture' in result:fail('SYNTHETIC_RECEIPT_FORBIDDEN')
    if result.get('event')!='RESULT':fail('BRIDGE_RESULT_MISSING')
    dispatched=result.get('dispatch_attempted')
    if type(dispatched) is not bool:fail('BRIDGE_DISPATCH_TYPE')
    if dispatched!=(len(events)==2) or (len(events)==2 and events[0].get('event')!='DISPATCHING'):fail('BRIDGE_DISPATCH_SEQUENCE')
    if result.get('transport_retry_index')!=0:fail('BRIDGE_RETRY_FORBIDDEN')
    if type(result.get('helper_elapsed_ns')) is not int or result['helper_elapsed_ns']<0:fail('BRIDGE_TIMING')
    if result.get('identity') is not None:
        wanted={'principal':protocol.ACCOUNT,'principal_type':'USER','auth_mode':'GCLOUD_USER','project_id':protocol.PROJECT,
                'quota_project':protocol.PROJECT,'service_account':None,'proxy':value['host_binding']['proxy'],'tls_trust':value['host_binding']['tls_trust']}
        if result['identity']!=wanted:fail('BRIDGE_IDENTITY_RECEIPT')
    if result.get('status')=='HTTP_OBSERVED':
        if not dispatched or result.get('identity') is None or type(result.get('http_status')) is not int or not 100<=result['http_status']<=599:fail('BRIDGE_HTTP_STATUS')
        if type(result.get('http_elapsed_ns')) is not int or not 0<=result['http_elapsed_ns']<=result['helper_elapsed_ns']:fail('BRIDGE_HTTP_TIMING')
        if type(result.get('headers')) is not dict or set(result['headers'])-protocol.SAFE_HEADERS:fail('BRIDGE_HEADER_POLICY')
        if any(type(v) is not str or len(v)>1024 or '\r' in v or '\n' in v for v in result['headers'].values()):fail('BRIDGE_HEADER_VALUE')
        try:body=protocol.unbase(result['response_b64'],protocol.MAX_RESPONSE)
        except protocol.BridgeError as error:fail(error.code)
        if sha(body)!=result.get('response_sha256'):fail('BRIDGE_RESPONSE_HASH')
        if result.get('provider_receipt')!='HTTP_RESPONSE_OBSERVED':fail('BRIDGE_PROVIDER_RECEIPT')
    elif result.get('status')=='PREFLIGHT_OK':
        if value['operation']!='preflight' or dispatched or result.get('identity') is None:fail('BRIDGE_PREFLIGHT_RESULT')
    elif result.get('status')=='FAILED':
        if type(result.get('error_code')) is not str or not protocol.ID.fullmatch(result['error_code']):fail('BRIDGE_ERROR_CODE')
    else:fail('BRIDGE_RESULT_STATUS')
    return result
class WindowsUserTransport:
    mode='LIVE'
    def __init__(self,config,manifest_hash):
        self.config=validate_config(config)
        if self.config.get('auth_mode')!='GCLOUD_USER':fail('WINDOWS_MODE_REQUIRED')
        self.manifest_hash=manifest_hash;self.dispatch_count=0;self.unknown_dispatches=0
        self.last_dispatch=False;self.last_receipt=None;self.audit=[];self.receipts=[]
        self.command_invocations=0;self.metadata_command_invocations=0;self.preflight_verified=False
    def validate_live(self,config,manifest_hash):
        if self.config!=config or self.manifest_hash!=manifest_hash:fail('LIVE_AUTH_TRANSPORT_BINDING')
        if os.name!='posix' or not ROOT.is_relative_to(Path('/home')):fail('WSL_LINUX_ORCHESTRATOR_REQUIRED')
        validate_host(config['windows_host'],files=True)
    def invoke(self,value):
        validate_host(self.config['windows_host'],files=True)
        binding=self.config['windows_host']
        argv=[str(wsl_path(binding['python_executable'])),'-I','-B',binding['helper_path']]
        self.last_dispatch=None;self.last_receipt=None;start=time.perf_counter_ns()
        try:
            # stdin contains public prompts/opaque receipts only. No token passes
            # to Linux and no model-controlled arguments reach a shell.
            child=subprocess.run(argv,input=canonical(value),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=300,check=False)
        except OSError:
            self.last_dispatch=False;fail('WINDOWS_HELPER_START_FAILED')
        except subprocess.TimeoutExpired as error:
            self._partial(error.stdout or b'',value);fail('WINDOWS_HELPER_TIMEOUT_NO_RETRY')
        elapsed=time.perf_counter_ns()-start
        try:
            result=decode_result(child.stdout,value)
            if child.returncode!=0:fail('WINDOWS_HELPER_EXIT_FAILED')
        except ApiError:
            self._partial(child.stdout,value);raise
        self.last_dispatch=result['dispatch_attempted']
        self.dispatch_count+=int(self.last_dispatch)
        result['wsl_bridge_elapsed_ns']=elapsed
        result['wsl_clock_scope']='LINUX_PID_'+str(os.getpid())+'_PERF_COUNTER'
        self.last_receipt=result;self.receipts.append(deepcopy(result));self.audit.extend(result['auth'])
        self.command_invocations=sum(x.get('operation')=='SHORT_LIVED_CREDENTIAL_ISSUANCE' for x in self.audit)
        self.metadata_command_invocations=len(self.audit)-self.command_invocations
        if result['status']=='FAILED':fail(result['error_code'])
        return result
    def _partial(self,raw,value):
        # An absent or truncated marker proves nothing about a killed helper.
        # Keep the reservation and record unknown, never zero.
        self.last_dispatch=None
        try:
            first=strict(raw.splitlines()[0]);check_event(first,value)
            if first.get('event')=='DISPATCHING':self.last_dispatch=True;self.dispatch_count+=1
        except (ApiError,IndexError,TypeError,KeyError):pass
        if self.last_dispatch is None:self.unknown_dispatches+=1
        self.last_receipt={'status':'PIPE_INTERRUPTED','dispatch_attempted':self.last_dispatch,'provider_receipt':'UNKNOWN',
                           'request_id':value['request_id'],'manifest_sha256':value['manifest_sha256'],
                           'request_sha256':value['body_sha256'],'transport_retry_index':0}
    def preflight(self):
        result=self.invoke(envelope(self.config,self.manifest_hash,'win01.preflight',None,b'',None))
        self.preflight_verified=True
        return result
    def send_reserved(self,kind,body,request_id,reservation):
        if not self.preflight_verified:fail('WINDOWS_PREFLIGHT_REQUIRED')
        result=self.invoke(envelope(self.config,self.manifest_hash,request_id,kind,body,reservation))
        return Response(result['http_status'],base64.b64decode(result['response_b64']),result['headers'],result['http_elapsed_ns'])
