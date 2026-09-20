"""Vertex v1 wire adapter. Text-only, one candidate, no tools or repair."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal,ROUND_CEILING
from copy import deepcopy
import re
import shutil
import ssl
import subprocess
import time
import urllib.request
import urllib.error
from .common import ApiError,fail,canonical,strict,sha,integer
from .policy import validate_config,endpoint,MODEL

RUNTIME_NOTE = '''API001 ENGINEERING PROFILE. The public execution environment currently supports one root-scope linear chain only. Available implementations: scan/sequential; filter/scalar or vectorized; top_k/full_sort or streaming_heap; project/column_view or copy; emit/json_artifact. Use the TaskInput task_id and public output contract exactly, and only dataset IDs already supplied. Do not include code, tool calls, markdown fences, regions, arbitrary URI access, or extra JSON fields. This profile is declared for this engineering pilot, not the full benchmark. Do not assume that an inefficient but legal algorithm is invalid. Return the logical contract at the logical stage and WorkIR at the physical stage.'''

@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict
    elapsed_ns: int

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        fail('HTTP_REDIRECT_DENIED')

class GcloudToken:
    """Short-lived impersonation. Raw token/stdout/stderr are never audit fields."""
    def __init__(self,config):
        self.config=validate_config(config);self.cached=None;self.at=0;self.command_invocations=0
        self.metadata_command_invocations=0;self.audit=[];self.preflight_verified=False
    def _command(self,args):
        exe=shutil.which('gcloud')
        if not exe:fail('GCLOUD_NOT_INSTALLED')
        return [exe,*args,'--project='+self.config['project_id'],
                '--account='+self.config['login_account'],'--quiet','--verbosity=warning']
    def preflight(self):
        from .auth_binding import validate_live_binding,check_auth_environment,safe_failure
        validate_live_binding(self.config);check_auth_environment(self.config)
        self.preflight_verified=False
        import os
        self.audit.append({'operation':'AUTH_CONFIG_SELECTION','config_directory_override_present':bool(os.environ.get('CLOUDSDK_CONFIG')),
                           'config_directory':os.environ.get('CLOUDSDK_CONFIG'),'scope':'INHERITED_PROCESS_ENV_NO_GLOBAL_CHANGE'})
        props={'auth/credential_file_override':None,'auth/access_token_file':None,
               'auth/impersonate_service_account':self.config['service_account'],
               'api_endpoint_overrides/iamcredentials':None,'core/log_http':'false',
               'billing/quota_project':self.config['project_id']}
        for prop,allowed in props.items():
            cmd=self._command(['config','get-value',prop])
            record={'operation':'LOCAL_AUTH_CONFIG_CHECK','property':prop,'argv':cmd,'started_unix_ns':time.time_ns()}
            self.audit.append(record);self.metadata_command_invocations+=1
            try:p=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=50,check=False)
            except (OSError,subprocess.SubprocessError):
                record.update(exit_code=None,error_code='AUTH_PREFLIGHT_FAILED');fail('AUTH_PREFLIGHT_FAILED')
            record['exit_code']=p.returncode
            if p.returncode:
                record.update(safe_failure(p.returncode,p.stderr));fail('AUTH_PREFLIGHT_FAILED')
            value=p.stdout.decode('utf-8',errors='replace').strip()
            present=value not in ('','(unset)');record['present']=present
            record['matches_authorized_value']=not present or (value.lower()==allowed if prop=='core/log_http' else value==allowed)
            if not record['matches_authorized_value']:fail('AUTH_OVERRIDE_CONFIG')
        cmd=self._command(['auth','list','--format=json(account,status)'])
        record={'operation':'LOCAL_LOGGED_IN_ACCOUNT_CHECK','argv':cmd,'started_unix_ns':time.time_ns()}
        self.audit.append(record);self.metadata_command_invocations+=1
        try:p=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=50,check=False)
        except (OSError,subprocess.SubprocessError):
            record.update(exit_code=None,error_code='AUTH_PREFLIGHT_FAILED');fail('AUTH_PREFLIGHT_FAILED')
        record['exit_code']=p.returncode
        if p.returncode:
            record.update(safe_failure(p.returncode,p.stderr));fail('AUTH_PREFLIGHT_FAILED')
        accounts=strict(p.stdout)
        record['approved_account_present']=type(accounts) is list and any(type(x) is dict and x.get('account')==self.config['login_account'] for x in accounts)
        if not record['approved_account_present']:fail('AUTH_ACCOUNT_NOT_LOGGED_IN')
        self.preflight_verified=True
        return {'status':'BOUND_LOCAL_IDENTITY_VERIFIED','project_id':self.config['project_id'],
                'login_account':self.config['login_account'],'service_account':self.config['service_account']}
    def __call__(self):
        from .auth_binding import check_auth_environment,safe_failure
        check_auth_environment(self.config)
        if self.cached is not None and time.monotonic()-self.at<2400:return self.cached
        if self.config['service_account'] is None:fail('RUNNER_IDENTITY_REQUIRED')
        cmd=self._command(['auth','print-access-token','--impersonate-service-account='+self.config['service_account']])
        record={'operation':'SHORT_LIVED_CREDENTIAL_ISSUANCE','argv':cmd,'started_unix_ns':time.time_ns(),
                'login_account':self.config['login_account'],'service_account':self.config['service_account'],
                'project_id':self.config['project_id'],'credential_http_requests':None}
        self.audit.append(record)
        try:
            self.command_invocations+=1
            p=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40,check=False)
        except (OSError,subprocess.SubprocessError):
            record.update(exit_code=None,error_code='AUTH_FAILED',reason='AUTH_SUBPROCESS_FAILED_NO_RETRY');fail('AUTH_FAILED')
        record['exit_code']=p.returncode
        if p.returncode:
            record.update(safe_failure(p.returncode,p.stderr));fail('AUTH_FAILED')
        try:token=p.stdout.decode('ascii').strip()
        except UnicodeError:record['error_code']='AUTH_FAILED';fail('AUTH_FAILED')
        if not 20<=len(token)<=8192 or re.search(r'\s',token):
            record['error_code']='AUTH_FAILED';fail('AUTH_FAILED')
        record['status']='CREDENTIAL_CAPTURED_IN_MEMORY'
        self.cached=token;self.at=time.monotonic()
        return token

class VertexTransport:
    mode='LIVE'
    def __init__(self,config,token_source):
        self.config=validate_config(config);self.token_source=token_source;self.dispatch_count=0
        proxy=urllib.request.ProxyHandler() if config['allow_environment_proxy'] else urllib.request.ProxyHandler({})
        self.opener=urllib.request.build_opener(proxy,NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    def send(self,kind,body,request_id):
        url=endpoint(self.config,kind)
        if type(body) is not bytes or len(body)>131072:fail('REQUEST_BYTE_LIMIT')
        token=self.token_source()
        if type(token) is not str or not token or re.search(r'\s',token):fail('AUTH_FAILED')
        req=urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
               'Accept':'application/json','Accept-Encoding':'identity','x-goog-user-project':self.config['project_id']},method='POST')
        start=time.perf_counter_ns();self.dispatch_count+=1
        try:
            try:r=self.opener.open(req,timeout=self.config['request_timeout_s'])
            except urllib.error.HTTPError as e:r=e
            with r:
                raw=r.read(self.config['max_response_bytes']+1)
                if len(raw)>self.config['max_response_bytes']:fail('RESPONSE_BYTE_LIMIT')
                code=r.code
                headers={k.lower():v for k,v in r.headers.items() if k.lower() in {'x-request-id','x-goog-request-id','content-type','retry-after'}}
            if 300<=code<400:fail('HTTP_REDIRECT_DENIED')
            return Response(code,raw,headers,time.perf_counter_ns()-start)
        except ApiError:raise
        except (OSError,ValueError,urllib.error.URLError):fail('TRANSPORT_UNCERTAIN_NO_RETRY')
        # No SDK transport retries, redirects, automatic model fallback or repair.

def make_body(assembled,config):
    validate_config(config)
    messages=assembled['provider_payload']['messages']
    system=[];contents=[]
    for message in messages:
        if set(message)!={'role','content'} or type(message['content']) is not str:fail('PUBLIC_MESSAGE_INVALID')
        if message['role']=='system':system.append({'text':message['content']})
        elif message['role']=='user':contents.append({'role':'user','parts':[{'text':message['content']}]})
        else:fail('PUBLIC_MESSAGE_ROLE')
    system.append({'text':RUNTIME_NOTE})
    key=assembled['protocol']+'.'+assembled['stage']
    return {'systemInstruction':{'parts':system},'contents':contents,
            'generationConfig':{'maxOutputTokens':config['output_limits'][key],'temperature':config['temperature'],
                                'candidateCount':1,'responseMimeType':'application/json',
                                'thinkingConfig':{'thinkingLevel':config['thinking_level'],'includeThoughts':False}}}

def count_body(generation_body):
    # Vertex CountTokensRequest takes contents/systemInstruction directly;
    # Gemini Developer API's generateContentRequest wrapper is a different API.
    return {k:deepcopy(generation_body[k]) for k in ('systemInstruction','contents')}

def parse_count(response):
    if response.status!=200:fail('HTTP_'+str(response.status))
    value=strict(response.body)
    if type(value) is not dict or not integer(value.get('totalTokens'),0,1048576):fail('COUNT_RESPONSE_INVALID')
    return {'estimated_input_tokens':value['totalTokens'],'scope':'EXACT_REQUEST_CONTENTS_AND_SYSTEM_PROVIDER_COUNT_ESTIMATE',
            'actual_billing_usage':None,'count_billing_cost':None}

def usage_metadata(value,config):
    raw=value.get('usageMetadata')
    keys=('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount','cachedContentTokenCount','toolUsePromptTokenCount')
    values={k:None for k in keys}
    if raw is not None:
        if type(raw) is not dict:fail('USAGE_INVALID')
        for key in keys:
            if key in raw:
                if not integer(raw[key],0,10**9):fail('USAGE_INVALID')
                values[key]=raw[key]
    p=values['promptTokenCount'];t=values['totalTokenCount'];c=values['candidatesTokenCount'];h=values['thoughtsTokenCount']
    if p is not None and t is not None and p>t:fail('USAGE_INCONSISTENT')
    if c is not None and p is not None and t is not None and p+c+(h or 0)>t:fail('USAGE_INCONSISTENT')
    if values['toolUsePromptTokenCount'] not in (None,0):fail('UNEXPECTED_TOOL_USAGE')
    cost=None
    if p is not None and t is not None:
        # All non-prompt tokens charged at output rate; cache discount not applied.
        # A conservative list-price estimate, never asserted to equal an invoice.
        usd=(Decimal(p)*Decimal(config['pricing']['input_usd_per_million'])+
             Decimal(t-p)*Decimal(config['pricing']['output_usd_per_million']))/Decimal(1000000)
        cost=format(usd,'f')
    return {'provider_fields':values,'missing_fields':[k for k in keys if values[k] is None],
            'cost_usd_list_price_upper_estimate':cost,'cost_scope':'REPORTED_TOTAL_MINUS_PROMPT_OUTPUT_RATE_NO_CACHE_DISCOUNT',
            'invoice_cost_usd':None,'remote_cpu_seconds':None,'remote_gpu_memory_bytes':None,
            'remote_resource_reason':'NOT_OBSERVABLE'}

def parse_generation(response,config):
    if response.status!=200:fail('HTTP_'+str(response.status))
    value=strict(response.body)
    if type(value) is not dict:fail('PROVIDER_RESPONSE_INVALID')
    usage=usage_metadata(value,config)
    result={'reported_model_version':value.get('modelVersion'),'provider_response_id':value.get('responseId'),
            'usage':usage,'status':'PROVIDER_RESPONSE_INVALID','finish_reason':None,'text':None}
    feedback=value.get('promptFeedback',{})
    if type(feedback) is not dict:fail('PROVIDER_FEEDBACK_INVALID')
    if feedback.get('blockReason'):
        result['status']='PROVIDER_BLOCKED';return result
    candidates=value.get('candidates')
    if type(candidates) is not list or len(candidates)!=1 or type(candidates[0]) is not dict:fail('CANDIDATE_COUNT')
    candidate=candidates[0];finish=candidate.get('finishReason');result['finish_reason']=finish
    if finish!='STOP':
        result['status']='OUTPUT_TRUNCATED' if finish=='MAX_TOKENS' else 'PROVIDER_NOT_FINISHED';return result
    content=candidate.get('content');texts=[]
    if type(content) is not dict or type(content.get('parts')) is not list:fail('CONTENT_PARTS')
    for part in content['parts']:
        if type(part) is not dict:fail('CONTENT_PARTS')
        if set(part)-{'text','thought','thoughtSignature'}:fail('UNEXPECTED_NON_TEXT_OUTPUT')
        if 'thought' in part and type(part['thought']) is not bool:fail('CONTENT_THOUGHT_FLAG')
        if part.get('thought') is True:continue
        if type(part.get('text')) is not str:fail('CONTENT_TEXT')
        texts.append(part['text'])
    if not texts:fail('CONTENT_EMPTY')
    text=''.join(texts)
    try:raw=text.encode('utf-8')
    except UnicodeError:fail('CONTENT_ENCODING')
    if len(raw)>65536:fail('PLAN_BYTE_LIMIT')
    result.update(status='PROVIDER_TEXT_READY',text=text)
    return result
