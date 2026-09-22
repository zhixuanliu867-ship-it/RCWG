"""Use already bound API001 authentication and HTTPS; never log in or retry."""
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from rcwg_api.common import fail
from rcwg_api.vertex import Response
from .bindings import validate_binding,account_hash


class ExistingVertexTransport:
    mode='LIVE'
    def __init__(self,binding,existing):
        self.binding=validate_binding(binding,live=True);self.existing=existing
        if account_hash(existing.config)!=binding['account_binding_hash']:raise PermissionError('EXISTING_AUTH_BINDING_MISMATCH')
        path=urlsplit(binding['endpoint']).path
        if '/projects/'+existing.config['project_id']+'/' not in path or binding['region']!=existing.config['location']:raise PermissionError('EXISTING_PROJECT_REGION_MISMATCH')
        if not hasattr(existing,'opener') or not hasattr(existing,'token_source'):raise ValueError('EXISTING_VERTEX_TRANSPORT_REQUIRED')

    def send(self,kind,body,request_id,*,reservation):
        if reservation is None:raise PermissionError('RESERVATION_REQUIRED')
        if kind not in {'G','E','COUNT'} or type(body) is not bytes or len(body)>131072:raise ValueError('REQUEST_INPUT')
        token=self.existing.token_source()
        if type(token) is not str or not token or re.search(r'\s',token):fail('AUTH_FAILED')
        endpoint=self.binding['endpoint']+(':countTokens' if kind=='COUNT' else ':generateContent')
        request=urllib.request.Request(endpoint,data=body,headers={'Authorization':'Bearer '+token,
              'Content-Type':'application/json','Accept':'application/json','Accept-Encoding':'identity',
              'x-goog-user-project':self.existing.config['project_id']},method='POST')
        started=time.perf_counter_ns()
        self.existing.dispatch_count+=1
        try:
            try:response=self.existing.opener.open(request,timeout=self.existing.config['request_timeout_s'])
            except urllib.error.HTTPError as exc:response=exc
            with response:
                raw=response.read(self.existing.config['max_response_bytes']+1)
                if len(raw)>self.existing.config['max_response_bytes']:fail('RESPONSE_BYTE_LIMIT')
                code=response.code
                headers={k.lower():v for k,v in response.headers.items() if k.lower() in {'x-request-id','x-goog-request-id','content-type','retry-after'}}
            if 300<=code<400:fail('HTTP_REDIRECT_DENIED')
            return Response(code,raw,headers,time.perf_counter_ns()-started)
        except (OSError,ValueError,urllib.error.URLError):fail('TRANSPORT_UNCERTAIN_NO_RETRY')


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
