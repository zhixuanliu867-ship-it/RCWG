import io,json,os,unittest,urllib.parse
from unittest.mock import patch
from rcwg_cloud.transport import MetadataIdentity,CloudHTTP,CloudError,GCSStore,VertexCloud,BUCKET,RUNTIME,NoRedirect
from rcwg_cloud.admission import AlreadyExists,WriteUncertain

class Reply(io.BytesIO):
    def __init__(self,body=b'{}',status=200,headers=None):
        super().__init__(body);self.status=self.code=status;self.headers=headers or {}
class Opener:
    def __init__(self,reply=None,error=None):self.calls=[];self.reply=reply;self.error=error
    def open(self,request,**kwargs):
        self.calls.append(request)
        if self.error:raise self.error
        return self.reply
class HTTP:
    def __init__(self,response):self.calls=[];self.response=response
    def request(self,*a,**k):
        self.calls.append((a,k))
        if isinstance(self.response,Exception):raise self.response
        return self.response

class CloudTransportTests(unittest.TestCase):
    def identity(self):
        i=MetadataIdentity();i.verified=True;i._token='TEST_TOKEN_NEVER_REAL_123456';i._until=float('inf');return i
    def test_fixed_gcs_create_uses_generation_zero(self):
        h=HTTP((200,json.dumps({'bucket':BUCKET,'name':'cloud001/claims/live.json','generation':'7'}).encode(),{},1))
        s=GCSStore(h);r=s.create('cloud001/claims/live.json',b'{}')
        self.assertEqual(r['generation'],'7')
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(h.calls[0][0][1]).query)['ifGenerationMatch'],['0'])
        self.assertEqual(len(h.calls),1)
    def test_existing_reservation_never_overwritten(self):
        h=HTTP((412,b'precondition',{},1))
        with self.assertRaises(AlreadyExists):GCSStore(h).create('cloud001/reservations/p0.physical.count.json',b'{}')
        self.assertEqual(len(h.calls),1)
    def test_ambiguous_gcs_write_does_not_retry(self):
        h=HTTP(CloudError('timeout'))
        with self.assertRaises(WriteUncertain):GCSStore(h).create('cloud001/claims/live.json',b'{}')
        self.assertEqual(len(h.calls),1)
    def test_runtime_cannot_write_manifest_or_input_or_escape_prefix(self):
        for key in ('cloud001/inputs/a','cloud001/manifests/live.json','cloud001/claims/../manifest','cloud001/claims//a','outside/a'):
            h=HTTP(None)
            with self.assertRaises(CloudError):GCSStore(h).create(key,b'{}')
            self.assertEqual(h.calls,[])
    def test_pinned_gcs_generation_checked_not_only_hash(self):
        h=HTTP((200,b'correct bytes',{'x-goog-generation':'8'},1))
        with self.assertRaises(CloudError):GCSStore(h).get('cloud001/inputs/a',generation='7')
        self.assertIn('generation=7',h.calls[0][0][1])
    def test_cloud_http_endpoint_allowlist_rejects_proxy_redirect_destination(self):
        h=CloudHTTP(self.identity());h.opener=Opener()
        for url in ('http://storage.googleapis.com/a','https://evil.example/a','https://storage.googleapis.com.evil/a','https://storage.googleapis.com:443/a','https://aiplatform.googleapis.com/a#x'):
            with self.assertRaises(CloudError):h.request('POST',url,b'{}')
        self.assertEqual(h.opener.calls,[])
        with self.assertRaises(CloudError):NoRedirect().redirect_request(None,None,None,None,None,None)
    def test_transport_timeout_unknown_one_attempt_no_secret(self):
        h=CloudHTTP(self.identity());h.opener=Opener(error=OSError('secret should not escape'))
        with self.assertRaisesRegex(CloudError,'TRANSPORT_UNCERTAIN_NO_RETRY'):h.request('POST','https://aiplatform.googleapis.com/v1/test',b'{}')
        self.assertEqual(len(h.opener.calls),1);self.assertEqual(h.requests[0]['status'],'DISPATCH_UNKNOWN')
        self.assertNotIn('secret',json.dumps(h.requests));self.assertNotIn('TEST_TOKEN',json.dumps(h.requests))
    def test_credential_echo_not_archived(self):
        h=CloudHTTP(self.identity());h.opener=Opener(Reply(b'TEST_TOKEN_NEVER_REAL_123456'))
        with self.assertRaises(CloudError):h.request('GET','https://storage.googleapis.com/test')
        self.assertNotIn('TEST_TOKEN',json.dumps(h.requests))
    def test_no_automatic_retry_on_server_error(self):
        h=CloudHTTP(self.identity());h.opener=Opener(Reply(b'error',503))
        self.assertEqual(h.request('POST','https://aiplatform.googleapis.com/v1/test',b'{}')[0],503)
        self.assertEqual(len(h.opener.calls),1)
    def test_model_fixed_project_global_model_and_bounded_body(self):
        h=HTTP((200,b'{}',{},1));h.identity=self.identity();v=VertexCloud(h)
        v.send('countTokens',b'{}');self.assertIn('/projects/rcwg-509116/locations/global/publishers/google/models/gemini-3.1-flash-lite:countTokens',h.calls[0][0][1])
        with self.assertRaises(CloudError):v.send('generateContent',b'a'*131073)
        self.assertEqual(v.dispatches,1)
    def test_metadata_token_never_used_before_verified_identity(self):
        with self.assertRaises(CloudError):MetadataIdentity().token()
    def test_metadata_rejects_foreign_principal_and_never_fetches_token(self):
        env={'CLOUD_RUN_JOB':'rcwg-cloud001-live','CLOUD_RUN_TASK_INDEX':'0','CLOUD_RUN_TASK_COUNT':'1','CLOUD_RUN_TASK_ATTEMPT':'0'}
        i=MetadataIdentity();paths=[]
        def get(path):paths.append(path);return b'rcwg-509116' if path=='project/project-id' else b'foreign@example.com'
        i._get=get
        with patch.dict(os.environ,env,clear=True),patch('rcwg_cloud.transport.sys.platform','linux'),patch('rcwg_cloud.transport.sys.version_info',(3,12,14)),patch('rcwg_cloud.transport.platform.machine',return_value='x86_64'):
            with self.assertRaisesRegex(CloudError,'CLOUD_PRINCIPAL'):i.verify('live')
        self.assertNotIn('instance/service-accounts/default/token',paths)
    def test_cloud_runtime_rejects_user_credentials_and_proxy(self):
        env={'CLOUD_RUN_JOB':'rcwg-cloud001-live','CLOUD_RUN_TASK_INDEX':'0','CLOUD_RUN_TASK_COUNT':'1','CLOUD_RUN_TASK_ATTEMPT':'0'}
        for key in ('CLOUDSDK_CONFIG','GOOGLE_APPLICATION_CREDENTIALS','HTTPS_PROXY'):
            with patch.dict(os.environ,dict(env,**{key:'forbidden'}),clear=True),patch('rcwg_cloud.transport.sys.platform','linux'),patch('rcwg_cloud.transport.sys.version_info',(3,12,14)),patch('rcwg_cloud.transport.platform.machine',return_value='x86_64'):
                with self.assertRaisesRegex(CloudError,'CLOUD_CREDENTIAL_OR_PROXY_OVERRIDE'):MetadataIdentity().verify('live')
    def test_platform_retry_attempt_rejected(self):
        env={'CLOUD_RUN_JOB':'rcwg-cloud001-live','CLOUD_RUN_TASK_INDEX':'0','CLOUD_RUN_TASK_COUNT':'1','CLOUD_RUN_TASK_ATTEMPT':'1'}
        with patch.dict(os.environ,env,clear=True),patch('rcwg_cloud.transport.sys.platform','linux'),patch('rcwg_cloud.transport.sys.version_info',(3,12,14)),patch('rcwg_cloud.transport.platform.machine',return_value='x86_64'):
            with self.assertRaisesRegex(CloudError,'CLOUD_TASK_BINDING'):MetadataIdentity().verify('live')

if __name__=='__main__':unittest.main()
