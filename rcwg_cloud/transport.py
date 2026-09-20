"""Fixed metadata identity and bounded GCS/Vertex REST. No gcloud or retries."""
import hashlib,json,os,platform,re,ssl,sys,time,urllib.error,urllib.parse,urllib.request
from rcwg_api.common import strict
from rcwg_api.vertex import Response
from .admission import AlreadyExists,WriteUncertain

PROJECT='rcwg-509116';BUCKET='rcwg-509116-cloud001-private'
RUNTIME='rcwg-cloud001-runtime@'+PROJECT+'.iam.gserviceaccount.com'
MODEL='gemini-3.1-flash-lite'
class CloudError(ValueError):pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k):raise CloudError('REDIRECT_DENIED')

class MetadataIdentity:
    def __init__(self):
        self.audit=[];self._token=None;self._until=0;self.verified=False
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def _get(self,path):
        if path not in ('project/project-id','instance/service-accounts/default/email','instance/service-accounts/default/token'):
            raise CloudError('METADATA_PATH')
        req=urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/'+path,headers={'Metadata-Flavor':'Google'})
        start=time.monotonic_ns()
        try:
            with self.opener.open(req,timeout=5) as r:
                if r.status!=200 or r.headers.get('Metadata-Flavor')!='Google':raise CloudError('METADATA_RESPONSE')
                raw=r.read(16385)
            if len(raw)>16384:raise CloudError('METADATA_SIZE')
        except (OSError,ValueError) as e:
            self.audit.append({'path':path,'status':'FAILED','elapsed_ns':time.monotonic_ns()-start})
            raise CloudError('METADATA_FAILED') from None
        self.audit.append({'path':path,'status':'OBSERVED','elapsed_ns':time.monotonic_ns()-start,'credential_body_archived':False})
        return raw
    def verify(self,phase):
        if sys.platform!='linux' or sys.version_info[:3]!=(3,12,14) or platform.machine()!='x86_64':raise CloudError('CLOUD_RUNTIME_PLATFORM')
        if phase not in ('replay','live') or os.environ.get('CLOUD_RUN_JOB')!='rcwg-cloud001-'+phase:raise CloudError('CLOUD_JOB_BINDING')
        if os.environ.get('CLOUD_RUN_TASK_INDEX')!='0' or os.environ.get('CLOUD_RUN_TASK_COUNT')!='1' or os.environ.get('CLOUD_RUN_TASK_ATTEMPT')!='0':raise CloudError('CLOUD_TASK_BINDING')
        if any(os.environ.get(k) for k in ('GOOGLE_APPLICATION_CREDENTIALS','CLOUDSDK_CONFIG','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')):raise CloudError('CLOUD_CREDENTIAL_OR_PROXY_OVERRIDE')
        if self._get('project/project-id').decode().strip()!=PROJECT:raise CloudError('CLOUD_PROJECT')
        if self._get('instance/service-accounts/default/email').decode().strip()!=RUNTIME:raise CloudError('CLOUD_PRINCIPAL')
        self.verified=True
        return {'mode':'CLOUD_RUN_SERVICE_IDENTITY_1','principal':RUNTIME,'project_id':PROJECT,'token_source':'FIXED_METADATA_ENDPOINT'}
    def token(self):
        if not self.verified:raise CloudError('IDENTITY_NOT_VERIFIED')
        if self._token and time.monotonic()<self._until:return self._token
        value=strict(self._get('instance/service-accounts/default/token'))
        token=value.get('access_token');expires=value.get('expires_in')
        if type(token) is not str or not 20<=len(token)<=8192 or re.search(r'\s',token) or value.get('token_type')!='Bearer' or type(expires) is not int or expires<60:
            raise CloudError('TOKEN_INVALID')
        self._token=token;self._until=time.monotonic()+min(expires-30,2400)
        return token

class CloudHTTP:
    def __init__(self,identity):
        if type(identity) is not MetadataIdentity:raise CloudError('IDENTITY_CLASS')
        self.identity=identity;self.requests=[]
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    def request(self,method,url,body=None,limit=8*1024*1024,timeout=40):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or parsed.netloc not in ('storage.googleapis.com','aiplatform.googleapis.com') or parsed.fragment:raise CloudError('ENDPOINT_DENIED')
        token=self.identity.token()
        req=urllib.request.Request(url,data=body,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
             'Accept-Encoding':'identity','x-goog-user-project':PROJECT})
        start=time.monotonic_ns();record={'method':method,'host':parsed.netloc,'started_unix_ns':time.time_ns(),'status':'DISPATCH_UNKNOWN','automatic_retries':0}
        self.requests.append(record)
        try:
            try:r=self.opener.open(req,timeout=timeout)
            except urllib.error.HTTPError as e:r=e
            with r:
                raw=r.read(limit+1);status=r.code;headers={k.lower():v for k,v in r.headers.items() if k.lower() in ('content-type','x-goog-generation','x-goog-hash','x-request-id')}
            if len(raw)>limit:raise CloudError('RESPONSE_SIZE')
            if token.encode() in raw or any(token in v for v in headers.values()):raise CloudError('CREDENTIAL_ECHO_REJECTED')
            record.update(status='HTTP_OBSERVED',http_status=status,elapsed_ns=time.monotonic_ns()-start)
            return status,raw,headers,record['elapsed_ns']
        except (OSError,ValueError):
            record['elapsed_ns']=time.monotonic_ns()-start
            raise CloudError('TRANSPORT_UNCERTAIN_NO_RETRY') from None

class GCSStore:
    def __init__(self,http):self.http=http;self.receipts=[]
    @staticmethod
    def _key(key):
        if type(key) is not str or not re.fullmatch(r'cloud001/[a-zA-Z0-9_./-]{1,400}',key) or any(p in ('','..','.') for p in key.split('/')):raise CloudError('OBJECT_KEY')
        return urllib.parse.quote(key,safe='')
    def get(self,key,generation=None):
        q={'alt':'media'}
        if generation is not None:
            if not re.fullmatch(r'[1-9][0-9]{0,30}',str(generation)):raise CloudError('OBJECT_GENERATION')
            q['generation']=str(generation)
        status,raw,headers,_=self.http.request('GET','https://storage.googleapis.com/storage/v1/b/'+BUCKET+'/o/'+self._key(key)+'?'+urllib.parse.urlencode(q))
        if status!=200:raise CloudError('GCS_GET_HTTP_'+str(status))
        receipt={'object':key,'generation':headers.get('x-goog-generation'),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'method':'GET'}
        if generation is not None and receipt['generation']!=str(generation):raise CloudError('GCS_GENERATION_MISMATCH')
        self.receipts.append(receipt);return raw,receipt
    def create(self,key,raw):
        self._key(key)
        if not key.startswith(('cloud001/claims/','cloud001/reservations/','cloud001/output/')):raise CloudError('OBJECT_WRITE_PREFIX')
        if type(raw) is not bytes or len(raw)>8*1024*1024:raise CloudError('OBJECT_SIZE')
        q=urllib.parse.urlencode({'uploadType':'media','name':key,'ifGenerationMatch':0})
        try:status,body,_,_=self.http.request('POST','https://storage.googleapis.com/upload/storage/v1/b/'+BUCKET+'/o?'+q,raw)
        except CloudError:raise WriteUncertain('GCS_CREATE_UNKNOWN_NO_RETRY') from None
        if status==412:raise AlreadyExists('DURABLE_OBJECT_ALREADY_EXISTS')
        if status not in (200,201):raise WriteUncertain('GCS_CREATE_HTTP_'+str(status))
        meta=strict(body)
        if meta.get('name')!=key or meta.get('bucket')!=BUCKET or not str(meta.get('generation','')).isdigit():raise WriteUncertain('GCS_CREATE_RECEIPT_INVALID')
        receipt={'object':key,'generation':str(meta['generation']),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'method':'POST','ifGenerationMatch':0}
        self.receipts.append(receipt);return receipt

class VertexCloud:
    def __init__(self,http):self.http=http;self.dispatches=0
    def send(self,kind,body):
        if kind not in ('countTokens','generateContent') or type(body) is not bytes or len(body)>131072:raise CloudError('MODEL_REQUEST_CONTRACT')
        url='https://aiplatform.googleapis.com/v1/projects/'+PROJECT+'/locations/global/publishers/google/models/'+MODEL+':'+kind
        # Token acquisition precedes the dispatch counter; reservation is external and already durable.
        self.http.identity.token();self.dispatches+=1
        status,raw,headers,elapsed=self.http.request('POST',url,body,limit=1048576,timeout=60)
        return Response(status,raw,headers,elapsed)
