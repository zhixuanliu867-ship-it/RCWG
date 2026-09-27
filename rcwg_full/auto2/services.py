"""AUTO2 uses the existing wire parser, request index and HTTP implementation."""
from datetime import datetime,timezone
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import re
import ssl
import time
import urllib.request
import uuid
from urllib.parse import urlsplit
from rcwg_full.evidence import digest,read,sha,write
from rcwg_full.services.bindings import validate_binding,account_hash
from rcwg_full.services.client import ServiceClient
from rcwg_full.services.transport import ExistingVertexTransport
from rcwg_api.vertex import NoRedirect


def validate_requested(binding):
    """All pre-response constraints are checked without inventing a revision."""
    b=validate_binding(binding,live=True,require_reported_revision=False)
    p=b['price_snapshot']['billing_policy']
    if p.get('revision')!='FULL001_BILLING_BOUND_1' or p.get('rates_are_upper_bounds') is not True:
        raise PermissionError('BILLING_BOUND_NOT_FROZEN')
    if not b['price_snapshot'].get('evidence_sha256'):raise PermissionError('PRICE_EVIDENCE_REQUIRED')
    return b


class ScopeBudget:
    def __init__(self,state,scope,identity,amounts):
        self.state=state;self.scope=scope;self.identity=identity;self.manifest_hash=digest(scope)
        self.config={'reservation_microusd':amounts}
    def reserve(self,rid,kind):
        return self.state.reserve(self.scope,rid,kind,self.config['reservation_microusd'][kind],self.identity())
    def observe(self,rid,status,evidence):self.state.observe(rid,status,{'response_sha256':evidence})


class DelegatedClient(ServiceClient):
    def __init__(self,binding,transport,budget,index):
        self.binding=validate_requested(binding);self.transport=transport;self.budget=budget
        self.index=index;self.mode='LIVE';self.scope_hash=budget.manifest_hash;self.receipt=None
        if transport.mode!='LIVE':raise ValueError('ACTUAL_PROVIDER_REQUIRED')
        self.authorize_live()
    def authorize_live(self):
        validate_requested(self.binding)
        self.budget.state.validate_scope(self.budget.scope,self.budget.identity())
        models=json.loads(read(self.budget.state.root/'MODEL_LOCK.json'))
        if digest(models)!=self.budget.scope['identity']['models'] or self.binding not in models['bindings']:
            raise PermissionError('MODEL_NOT_IN_SCOPE_LOCK')
    def revision_drift(self,returned):
        if not returned:return True
        if self.binding['reported_revision'] is not None:return super().revision_drift(returned)
        # Persist first observed revision without mutating the requested binding.
        file=self.index.root/('observed-model-'+digest(self.binding)+'.json')
        if file.exists():return json.loads(read(file))['reported_revision']!=returned
        write(file,{'binding_hash':digest(self.binding),'reported_revision':returned,'observed_only_in_phase':'B'})
        return False

    def measure(self,request,*,local_counter=None):
        if self.binding['count_method']!='PROVIDER_COUNT':return super().measure(request,local_counter=local_counter)
        body={k:v for k,v in request['body'].items() if k in {'contents','systemInstruction'}}
        rid=str(uuid.uuid5(uuid.UUID(request['request_id']),'COUNT'))
        counted=self.call({**request,'request_id':rid,'body':body,'body_hash':digest(body)},'COUNT')
        if counted['status']!='COMPLETED':return None,counted
        return {'method':'PROVIDER_COUNT','tokenizer':self.binding['tokenizer'],'tokens':counted['response']['estimated_input_tokens'],
                'body_hash':request['body_hash'],'count_request_id':rid},None


class DelegatedVertexTransport(ExistingVertexTransport):
    def __init__(self,binding,existing):
        self.binding=validate_requested(binding);self.existing=existing
        if account_hash(existing.config)!=binding['account_binding_hash']:
            raise PermissionError('EXISTING_AUTH_BINDING_MISMATCH')
        if '/projects/'+existing.config['project_id']+'/' not in urlsplit(binding['endpoint']).path:
            raise PermissionError('EXISTING_PROJECT_MISMATCH')


class ExistingWindowsIdentity:
    """Reuse the reviewed Windows gcloud preflight and in-memory user token path."""
    def __init__(self,binding):
        from rcwg_api.windows_helper import auth_preflight,sdk_call
        self.binding=binding;self.audit=[];self.cached=None;self.at=0;self.sdk_call=sdk_call
        for pathkey,hashkey in [('python_executable','python_sha256'),('gcloud_entry','gcloud_entry_sha256'),('helper_path','helper_sha256')]:
            if sha(read(binding[pathkey]))!=binding[hashkey]:raise PermissionError('EXISTING_AUTH_SOURCE_CHANGED')
        self.identity=auth_preflight(binding,self.audit)
    def __call__(self):
        if self.cached and time.monotonic()-self.at<1800:return self.cached
        raw,_=self.sdk_call(self.binding,['auth','print-access-token'],self.audit,True)
        token=raw.decode('ascii').strip()
        if not 20<=len(token)<=8192 or re.search(r'\s',token):raise PermissionError('AUTH_TOKEN_INVALID')
        self.cached=token;self.at=time.monotonic();return token
    def existing_transport(self):
        config={'auth_mode':'GCLOUD_USER','project_id':self.identity['project_id'],
                'login_account':self.identity['principal'],'service_account':None,'location':'global',
                'request_timeout_s':90,'max_response_bytes':1048576}
        proxy=self.binding['proxy'];url=f"http://{proxy['address']}:{proxy['port']}"
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':url}),NoRedirect(),
                                          urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        return SimpleNamespace(config=config,opener=opener,token_source=self,dispatch_count=0)
