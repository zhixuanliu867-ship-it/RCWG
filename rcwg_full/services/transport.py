"""Use already bound API001 authentication and HTTPS; never log in or retry."""
import re
import time
import hashlib
import json
import http.client
from datetime import datetime,timezone
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from rcwg_api.common import fail
from rcwg_api.vertex import Response
from .bindings import validate_binding,account_hash
from .transport_evidence import PROFILE,TransportFailure,exception_fields
from .timeout3 import validate as validate_timeout,Deadline


class ExistingVertexTransport:
    mode='LIVE'
    def __init__(self,binding,existing):
        self.binding=validate_binding(binding,live=True);self.existing=existing
        if account_hash(existing.config)!=binding['account_binding_hash']:raise PermissionError('EXISTING_AUTH_BINDING_MISMATCH')
        path=urlsplit(binding['endpoint']).path
        if '/projects/'+existing.config['project_id']+'/' not in path or binding['region']!=existing.config['location']:raise PermissionError('EXISTING_PROJECT_REGION_MISMATCH')
        if not hasattr(existing,'opener') or not hasattr(existing,'token_source'):raise ValueError('EXISTING_VERTEX_TRANSPORT_REQUIRED')

    def send(self,kind,body,request_id,*,reservation):
        return self.send_with_evidence(kind,body,request_id,reservation=reservation)

    def send_with_evidence(self,kind,body,request_id,*,reservation,evidence_sink=None):
        if reservation is None:raise PermissionError('RESERVATION_REQUIRED')
        if kind not in {'G','E','COUNT'} or type(body) is not bytes or len(body)>131072:raise ValueError('REQUEST_INPUT')
        started=time.perf_counter_ns()
        state={'transport_profile':PROFILE,'local_request_id':request_id,'kind':kind,
               'request_body_sha256':hashlib.sha256(body).hexdigest(),'phase':'CREDENTIALS',
               'sent':False,'http_status':None,'response_headers':{},'response_complete':False,
               'received_bytes':0,'provider_response_id':None,'model_version':None,'usage':None}
        raw=bytearray();token=None;sequence=0;prefix_saved=0;absolute=None
        def emit(event):
            nonlocal sequence,prefix_saved
            if evidence_sink is None:return
            sequence+=1;prefix=bytes(raw[:65536])
            sanitized=prefix.replace(token.encode(),b'<REDACTED_CREDENTIAL>') if token else prefix
            record={**state,'event':event,'sequence':sequence,'observed_utc':datetime.now(timezone.utc).isoformat(),
                    'elapsed_ns':time.perf_counter_ns()-started,'raw_prefix_bytes':len(prefix),
                    'raw_prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                    'credential_echo_redacted':sanitized!=prefix}
            fragment=sanitized if len(prefix)>prefix_saved else None
            evidence_sink(record,fragment);prefix_saved=len(prefix)
        def observe(phase,inference_send_started):
            state['phase']=phase
            state['sent']=None if inference_send_started else False
            emit('TRANSPORT_PHASE')
        try:
            emit('REQUEST_REGISTERED')
            token=self.existing.token_source()
            if type(token) is not str or not token or re.search(r'\s',token):fail('AUTH_FAILED')
            state['phase']='REQUEST_PREPARATION'
            endpoint=self.binding['endpoint']+(':countTokens' if kind=='COUNT' else ':generateContent')
            request=urllib.request.Request(endpoint,data=body,headers={'Authorization':'Bearer '+token,
                  'Content-Type':'application/json','Accept':'application/json','Accept-Encoding':'identity',
                  'x-goog-user-project':self.existing.config['project_id']},method='POST')
            request._rcwg_transport_observer=observe
            timeout=self.existing.config['request_timeout_s']
            policy=self.existing.config.get('timeout_profile')
            if policy is not None:
                policy=validate_timeout(policy)
                if kind=='E':raise PermissionError('HTTP_TIMEOUT_3_E_NOT_ADMITTED')
                timeout=policy[kind+'_http_seconds']
                absolute=Deadline(timeout)
                request._rcwg_deadline=absolute
                request._rcwg_connect_timeout=policy['connect_seconds']
                state['timeout_profile']=policy['revision']
                state['connect_timeout_seconds']=policy['connect_seconds']
            # An uninstrumented legacy opener cannot distinguish connect/write/wait.
            # Only the traced connection may subsequently prove zero POST bytes.
            state.update(phase='OPEN_SEND_OR_WAIT',sent=None)
            deadline=absolute.end if absolute else time.monotonic()+timeout
            state['http_deadline_seconds']=timeout
            emit('HTTP_DISPATCH_ENTERED');self.existing.dispatch_count+=1
            if absolute:absolute.start()
            try:response=self.existing.opener.open(request,timeout=policy['connect_seconds'] if absolute else timeout)
            except urllib.error.HTTPError as exc:response=exc
            with response:
                code=response.code;headers={}
                for key,value in response.headers.items():
                    key=key.lower()
                    if key in {'x-request-id','x-goog-request-id','content-type','retry-after','content-length','date'}:
                        value=str(value)
                        if len(value)<=512 and not any(ord(c)<32 for c in value) and token not in value:
                            headers[key]=value
                state.update(phase='RESPONSE_HEADERS',sent=True,http_status=code,response_headers=headers)
                emit('RESPONSE_HEADERS')
                if absolute:absolute.remaining()
                limit=self.existing.config['max_response_bytes']
                state['phase']='RESPONSE_BODY'
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('HTTP_TOTAL_DEADLINE')
                    sock=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
                    if sock is not None:sock.settimeout(remaining)
                    try:chunk=(getattr(response,'read1',response.read) if absolute else response.read)(min(16384,limit+1-len(raw)))
                    except http.client.IncompleteRead as exc:
                        raw.extend(exc.partial[:limit+1-len(raw)]);state['received_bytes']=len(raw)
                        emit('PARTIAL_BODY');raise
                    if not chunk:
                        if absolute:absolute.remaining()
                        break
                    raw.extend(chunk);state['received_bytes']=len(raw);emit('BODY_CHUNK')
                    if absolute:absolute.remaining()
                    if len(raw)>limit:fail('RESPONSE_BYTE_LIMIT')
                if 'content-length' in headers and not (headers['content-length'].isascii() and headers['content-length'].isdigit()):
                    raise ValueError('INVALID_CONTENT_LENGTH')
                if headers.get('content-length','').isdigit() and len(raw)!=int(headers['content-length']):
                    raise http.client.IncompleteRead(b'',int(headers['content-length'])-len(raw))
                state['response_complete']=True
                if token.encode() in raw:fail('CREDENTIAL_ECHO_IN_RESPONSE')
                try:
                    envelope=json.loads(raw)
                    if isinstance(envelope,dict):
                        for key,target in [('responseId','provider_response_id'),('modelVersion','model_version')]:
                            value=envelope.get(key)
                            if isinstance(value,str) and re.fullmatch(r'[\w.:-]{1,256}',value):state[target]=value
                        usage=envelope.get('usageMetadata')
                        if isinstance(usage,dict):
                            state['usage']={k:v for k,v in usage.items() if re.fullmatch(r'[A-Za-z]{1,64}',k) and type(v) is int and v>=0}
                except (ValueError,UnicodeError):pass
                state['phase']='COMPLETE';emit('RESPONSE_COMPLETE')
            if 300<=code<400:fail('HTTP_REDIRECT_DENIED')
            return Response(code,bytes(raw),headers,time.perf_counter_ns()-started)
        except Exception as exc:
            state.update(exception_fields(exc))
            known={'AUTH_FAILED','AUTH_PREFLIGHT_FAILED','AUTH_OVERRIDE_CONFIG','RESPONSE_BYTE_LIMIT',
                   'CREDENTIAL_ECHO_IN_RESPONSE','HTTP_REDIRECT_DENIED'}
            state['error_code']=getattr(exc,'code',None) if getattr(exc,'code',None) in known else None
            try:emit('TRANSPORT_FAILURE')
            except Exception:state['evidence_persistence_failed']=True
            code='TRANSPORT_UNCERTAIN_NO_RETRY' if state['sent'] is None else 'TRANSPORT_CONFIRMED_NOT_SENT' if state['sent'] is False else 'RESPONSE_INCOMPLETE_OR_REJECTED'
            raise TransportFailure(code,state) from None
        finally:
            if absolute:absolute.close()


class ExistingWindowsTransport:
    mode='LIVE'
    def __init__(self,binding,existing):
        from rcwg_api.policy import endpoint
        self.binding=validate_binding(binding,live=True);self.existing=existing
        if account_hash(existing.config)!=binding['account_binding_hash'] or endpoint(existing.config,'generateContent')!=binding['endpoint']+':generateContent':
            raise PermissionError('WINDOWS_BRIDGE_EXACT_REGISTERED_MODEL_ONLY')

    def send(self,kind,body,request_id,*,reservation):
        if reservation is None:raise PermissionError('RESERVATION_REQUIRED')
        method='countTokens' if kind=='COUNT' else 'generateContent'
        receipt={'request_id':request_id,'kind':method,'amount_microusd':reservation,
                 'reserved_before_io':True,'manifest_sha256':self.existing.manifest_hash,'mode':'LIVE'}
        return self.existing.send_reserved(method,body,request_id,receipt)


class ExistingCloudTransport:
    mode='LIVE'
    def __init__(self,binding,http):
        from rcwg_cloud.transport import CloudHTTP,PROJECT,RUNTIME
        self.binding=validate_binding(binding,live=True);self.http=http
        expected={'auth_mode':'CLOUD_RUN_SERVICE_IDENTITY_1','project_id':PROJECT,'login_account':None,'service_account':RUNTIME,'location':'global'}
        if type(http) is not CloudHTTP or not http.identity.verified:raise PermissionError('EXISTING_CLOUD_IDENTITY_REQUIRED')
        if binding['account_binding_hash']!=account_hash(expected) or binding['region']!='global' or '/projects/'+PROJECT+'/' not in urlsplit(binding['endpoint']).path:
            raise PermissionError('EXISTING_CLOUD_BINDING_MISMATCH')

    def send(self,kind,body,request_id,*,reservation):
        if reservation is None:raise PermissionError('RESERVATION_REQUIRED')
        if kind not in {'G','E','COUNT'} or type(body) is not bytes or len(body)>131072:raise ValueError('REQUEST_INPUT')
        method='countTokens' if kind=='COUNT' else 'generateContent'
        status,raw,headers,elapsed=self.http.request('POST',self.binding['endpoint']+':'+method,body,limit=1048576,timeout=60)
        return Response(status,raw,headers,elapsed)
