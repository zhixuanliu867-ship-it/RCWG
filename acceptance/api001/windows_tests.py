"""Actual Windows offline tests; h and binding injected by the fixed runner."""
import base64,json,os,secrets,ssl,sys,unittest
from copy import deepcopy
from unittest.mock import patch,Mock
h=None
binding=None
class NativeWindowsTests(unittest.TestCase):
    def envelope(self,raw=b'{"contents":[]}',kind='countTokens'):
        return {'version':h.VERSION,'operation':'send','manifest_sha256':'a'*64,'config_sha256':'b'*64,
                'request_id':'win01.native.r0','kind':kind,'body_b64':base64.b64encode(raw).decode(),'body_sha256':h.sha(raw),
                'reservation':{'request_id':'win01.native.r0','kind':kind,'amount_microusd':h.METHODS[kind],
                    'reserved_before_io':True,'manifest_sha256':'a'*64,'mode':'LIVE'},'host_binding':binding}
    def test_actual_native_runtime_deployment_hash_and_chinese_path(self):
        record=h.native_host(binding)
        self.assertEqual(record['os'],'nt');self.assertEqual(record['pid'],os.getpid())
        self.assertEqual(record['python_version'],binding['python_version']);self.assertIn('志轩',binding['helper_path'])
    def test_fixed_sdk_native_command_unicode_quoting(self):
        argv,cmd=h.native_command(binding,['auth','print-access-token'],True)
        self.assertTrue(argv[0].endswith('gcloud.cmd'));self.assertIn('志轩',cmd)
        self.assertIn('--billing-project='+h.PROJECT,argv);self.assertNotIn('impersonate',cmd)
    def test_original_unicode_and_deep_json_bytes(self):
        obj={'中文':{'nested':[{'deep':{'原样':'α 中文'}}]}};raw=('  '+json.dumps(obj,ensure_ascii=False)+'\n').encode()
        self.assertEqual(h.validate_envelope(self.envelope(raw)),raw)
    def test_host_hash_mismatch(self):
        b=deepcopy(binding);b['helper_sha256']='0'*64
        with self.assertRaises(h.BridgeError):h.native_host(b)
    def test_windows_ssl_default_verifies_host(self):
        context=ssl.create_default_context();self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
    def test_closed_protocol_rejects_injection_and_bom(self):
        for raw in (b'\xef\xbb\xbf{}',b'{"x":1,"x":2}',b'\xff'):
            with self.assertRaises(h.BridgeError):h.strict(raw)
        e=self.envelope();e['url']='http://unapproved'
        with self.assertRaises(h.BridgeError):h.validate_envelope(e)
    def test_no_live_override_from_windows_environment(self):
        for key in ('CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT','CLOUDSDK_AUTH_ACCESS_TOKEN','CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE'):
            with patch.dict(os.environ,{key:secrets.token_hex(24)}),patch.object(h,'sdk_call') as call,self.assertRaises(h.BridgeError):h.auth_preflight(binding,[])
            call.assert_not_called()
    def test_http_raw_bytes_proxy_and_canary_no_logs(self):
        token=secrets.token_hex(24);raw='{"中文":"字节"}'.encode()
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
        response.read.side_effect=[b'{"totalTokens":3}',b''];response.code=200;response.headers={'content-type':'application/json'}
        opener=Mock();opener.open.return_value=response
        with patch.object(h.urllib.request,'build_opener',return_value=opener):r=h.post('countTokens',raw,token,binding)
        req=opener.open.call_args.args[0];self.assertEqual(req.data,raw);self.assertEqual(req.host,'127.0.0.1:10090')
        self.assertNotIn(token,str(r));opener.open.assert_called_once()
    def test_no_retry_401_403_429_5xx(self):
        for code in (401,403,429,500,503):
            response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
            response.read.side_effect=[b'{}',b''];response.code=code;response.headers={}
            opener=Mock();opener.open.return_value=response
            with patch.object(h.urllib.request,'build_opener',return_value=opener):r=h.post('countTokens',b'{}',secrets.token_hex(24),binding)
            self.assertEqual(r[0],code);opener.open.assert_called_once()
    def test_timeout_does_not_retry(self):
        opener=Mock();opener.open.side_effect=TimeoutError
        with patch.object(h.urllib.request,'build_opener',return_value=opener),self.assertRaises(h.BridgeError):h.post('countTokens',b'{}',secrets.token_hex(24),binding)
        opener.open.assert_called_once()
    def test_credential_and_proxy_password_never_emitted(self):
        canary=secrets.token_hex(24)
        process=Mock(returncode=1,stdout=canary.encode(),stderr=('PERMISSION_DENIED '+canary).encode());audit=[]
        with patch.object(h.subprocess,'run',return_value=process),self.assertRaises(h.BridgeError):h.sdk_call(binding,['auth','print-access-token'],audit,True)
        self.assertNotIn(canary,h.encode(audit).decode())
    def test_body_size_and_reservation_link(self):
        e=self.envelope();e['reservation']['manifest_sha256']='c'*64
        with self.assertRaises(h.BridgeError):h.validate_envelope(e)
        with self.assertRaises(h.BridgeError):h.strict(b'x'*(h.MAX_PIPE+1))
