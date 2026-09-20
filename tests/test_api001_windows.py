from copy import deepcopy
import base64
import json
import secrets
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch,Mock
from rcwg_api import windows_helper as h
from rcwg_api.windows_bridge import WindowsUserTransport,envelope,decode_result,validate_host,wsl_path
from rcwg_api.common import ApiError,ROOT,sha,canonical,digest
from rcwg_api.policy import windows_config,validate_config,default_config,approval_template,validate_approval
from rcwg_api.auth_binding import validate_live_binding
from rcwg_api.budget import Budget

TOKEN='runtime-canary-'+secrets.token_hex(24)
def binding():
    return {'python_executable':r'C:\Users\中文\Python\python.exe','python_sha256':'1'*64,'python_version':'3.13.4',
            'helper_path':r'C:\Users\中文\private\api001_bridge.py','helper_sha256':sha((ROOT/'rcwg_api/windows_helper.py').read_bytes()),
            'gcloud_entry':r'C:\Users\中文\SDK\gcloud.cmd','gcloud_entry_sha256':'2'*64,'sdk_version':'585.0.0',
            'proxy':{'type':'http','address':'127.0.0.1','port':'10090'},'tls_trust':'WINDOWS_DEFAULT_VERIFIED_TLS'}
def env(kind='countTokens',body=b'{"contents":[]}'):
    config=windows_config(binding());rid='api001.p0.g0.physical.'+('count' if kind=='countTokens' else 'generate')
    reserve={'request_id':rid,'kind':kind,'amount_microusd':h.METHODS[kind],'reserved_before_io':True,'manifest_sha256':'a'*64,'mode':'LIVE'}
    return envelope(config,'a'*64,rid,kind,body,reserve)
def host(b):return {'os':'nt','platform':'win32','pid':123,'python_version':b['python_version'],'python_executable':b['python_executable'],
                    'clock_scope':'WINDOWS_PID_123_PERF_COUNTER','host_binding_sha256':digest(b),'helper_sha256':b['helper_sha256']}
def identity(b):return {'principal':h.ACCOUNT,'principal_type':'USER','auth_mode':'GCLOUD_USER','project_id':h.PROJECT,'quota_project':h.PROJECT,
                         'service_account':None,'proxy':b['proxy'],'tls_trust':b['tls_trust']}
def fake_sdk(b,args,audit,resource=False):
    r={'operation':'SHORT_LIVED_CREDENTIAL_ISSUANCE','exit_code':0,'project_id':h.PROJECT,'login_account':h.ACCOUNT,'service_account':None,
       'auth_mode':'GCLOUD_USER','principal_type':'USER','argv':[b['gcloud_entry'],'auth','print-access-token','--project='+h.PROJECT,
          '--account='+h.ACCOUNT,'--billing-project='+h.PROJECT]};audit.append(r);return TOKEN.encode(),r
def result(value=None,status=200,raw=b'{"totalTokens":10}'):
    value=value or env();events=[]
    with patch.object(h,'native_host',side_effect=host),patch.object(h,'auth_preflight',side_effect=lambda b,a:identity(b)),patch.object(h,'sdk_call',side_effect=fake_sdk),patch.object(h,'post',return_value=(status,raw,{'content-type':'application/json'},1)):
        r=h.handle(value,events.append)
    return value,events+[r]
def packet(events):return b'\n'.join(h.encode(x) for x in events)+b'\n'

class WindowsProtocolTests(unittest.TestCase):
    def test_unicode_and_deep_bytes_remain_exact(self):
        raw=(' { "contents": '+json.dumps({'中文':['层'*5,{'a':[1,2,3]}]},ensure_ascii=False)+' } ').encode()
        self.assertEqual(h.validate_envelope(env(body=raw)),raw)
    def test_original_p0_p1_serializer_bytes(self):
        from rcwg_exec.demo import prepare_fixture
        from rcwg_spec.generation import build_request
        from rcwg_api.mock import wire_fixtures
        from rcwg_api.vertex import make_body,count_body
        with tempfile.TemporaryDirectory() as d:
            task,plans,recipe,data=prepare_fixture(Path(d)/'fixture')
            logical=json.loads(json.loads(wire_fixtures(plans['streaming_heap'])[3].body)['candidates'][0]['content']['parts'][0]['text'])
            for protocol,stage,logical in [('P0','physical',None),('P1','logical',None),('P1','physical',logical)]:
                built=build_request(task,protocol=protocol,stage=stage,generation_attempt_id='g',request_id='r',logical_contract=logical)
                body=make_body(built,default_config('rcwg-mock-pilot'))
                for kind,value in [('generateContent',body),('countTokens',count_body(body))]:
                    raw=canonical(value);self.assertEqual(h.validate_envelope(env(kind,raw)),raw)
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(h.BridgeError):h.strict(b'{"x":1,"x":2}')
    def test_bom_invalid_utf8_and_nonfinite(self):
        for raw in (b'\xef\xbb\xbf{}',b'\xff',b'{"x":NaN}',b'{"x":1e999}'):
            with self.subTest(raw=raw),self.assertRaises(h.BridgeError):h.strict(raw)
    def test_envelope_unknown_url_or_command(self):
        for key in ('url','headers','command','script'):
            e=env();e[key]='attack'
            with self.subTest(key=key),self.assertRaises(h.BridgeError):h.validate_envelope(e)
    def test_method_and_request_id_closed(self):
        for key,value in [('kind','delete'),('request_id','../other'),('request_id','x\ncmd')]:
            e=env();e[key]=value
            with self.subTest(key=key),self.assertRaises(h.BridgeError):h.validate_envelope(e)
    def test_request_hash_mismatch(self):
        e=env();e['body_sha256']='b'*64
        with self.assertRaises(h.BridgeError):h.validate_envelope(e)
    def test_reservation_is_exact_not_truthy(self):
        for key,value in [('reserved_before_io',1),('amount_microusd',1),('request_id','another'),('mode','MOCK')]:
            e=env();e['reservation'][key]=value
            with self.subTest(key=key),self.assertRaises(h.BridgeError):h.validate_envelope(e)
    def test_base64_and_body_caps(self):
        for value in ('!!!!','YQ==\n','A'*200000):
            e=env();e['body_b64']=value
            with self.subTest(value=value[:10]),self.assertRaises(h.BridgeError):h.validate_envelope(e)
    def test_pipe_size(self):
        with self.assertRaises(h.BridgeError):h.strict(b' '*1800001)
    def test_path_injection_and_network_paths(self):
        for value in (r'C:\evil&cmd\python.exe',r'C:\%TEMP%\python.exe',r'C:\..\python.exe',r'\\server\share\python.exe','relative/python.exe'):
            b=binding();b['python_executable']=value
            with self.subTest(value=value),self.assertRaises(h.BridgeError):h.validate_binding(b)
    def test_config_user_fixed_identity(self):
        c=windows_config(binding());self.assertEqual(validate_config(c),c);validate_live_binding(c)
        self.assertIsNone(c['service_account'])
        for key,value in [('project_id','rcwg-other'),('principal','other@gmail.com'),('service_account','runner'),('quota_project','other'),('max_requests',{'generateContent':4,'countTokens':3})]:
            bad=deepcopy(c);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ApiError):validate_config(bad)
    def test_old_v1_does_not_become_user(self):
        c=default_config('rcwg-509116');m={'config':c};a=approval_template(m)
        a.update(approved=True,data_location_approved=True,pr4_delivery_proof_verified=True)
        with self.assertRaises(ApiError):validate_approval(a,m)
    def test_user_approval_host_and_version_binding(self):
        m={'config':windows_config(binding())};a=approval_template(m)
        a.update(approved=True,data_location_approved=True,pr4_delivery_proof_verified=True,expires_unix=200,
                 pricing_rechecked_unix=100,offline_api_acceptance_sha256='b'*64,windows_acceptance_sha256='c'*64,owner_note='Explicit owner WIN-01 approval')
        validate_approval(a,m,now=100)
        for key,value in [('windows_host_sha256','0'*64),('principal','other'),('version','API001_APPROVAL_1')]:
            wrong=deepcopy(a);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(ApiError):validate_approval(wrong,m,now=100)
    def test_actual_helper_source_is_bound(self):
        b=binding();b['helper_sha256']='f'*64
        with self.assertRaises(ApiError):validate_host(b)
    def test_host_non_windows_fails(self):
        with patch.object(h.os,'name','posix'),self.assertRaises(h.BridgeError):h.native_host(binding())
    def test_proxy_tls_binding_cannot_disable(self):
        for key,value in [('proxy',{'type':'http','address':'0.0.0.0','port':'10090'}),('tls_trust','DISABLED')]:
            b=binding();b[key]=value
            with self.subTest(key=key),self.assertRaises(h.BridgeError):h.validate_binding(b)
    def test_implicit_windows_impersonation_and_file_overrides(self):
        for key in ('CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT','CLOUDSDK_AUTH_ACCESS_TOKEN_FILE','GOOGLE_APPLICATION_CREDENTIALS','SSL_CERT_FILE'):
            with self.subTest(key=key),patch.dict(os.environ,{key:secrets.token_hex(24)},clear=True),patch.object(h,'sdk_call') as call,self.assertRaises(h.BridgeError):h.auth_preflight(binding(),[])
            call.assert_not_called()
    def test_native_fixed_command_has_no_impersonation(self):
        with patch.dict(os.environ,{'SystemRoot':r'C:\Windows'}):
            argv,cmd=h.native_command(binding(),['auth','print-access-token'],True)
        self.assertIn('--billing-project='+h.PROJECT,argv);self.assertIn('--account='+h.ACCOUNT,argv)
        self.assertFalse(any('impersonate' in s for s in argv));self.assertNotIn(TOKEN,cmd)
    def test_canary_sdk_failure_withheld(self):
        r=Mock(returncode=1,stdout=TOKEN.encode(),stderr=b'PERMISSION_DENIED '+TOKEN.encode());audit=[]
        with patch.dict(os.environ,{'SystemRoot':r'C:\Windows'}),patch.object(h.subprocess,'run',return_value=r),self.assertRaises(h.BridgeError):h.sdk_call(binding(),['auth','print-access-token'],audit,True)
        self.assertNotIn(TOKEN,h.encode(audit).decode());self.assertEqual(audit[0]['error_code'],'PERMISSION_DENIED')
    def test_effective_proxy_password_blocks_without_leak(self):
        canary='proxy-canary-'+secrets.token_hex(24)
        def sdk(b,args,audit,resource=False):
            prop=args[-1];v=canary if prop=='proxy/password' else '(unset)'
            audit.append({});return v.encode(),audit[-1]
        audit=[]
        with patch.dict(os.environ,{},clear=True),patch.object(h,'sdk_call',side_effect=sdk),self.assertRaises(h.BridgeError):h.auth_preflight(binding(),audit)
        self.assertNotIn(canary,h.encode(audit).decode())
    def test_http_raw_bytes_proxy_tls_headers(self):
        r=Mock();r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=None);r.read.side_effect=[b'{}',b''];r.code=200;r.headers={'content-type':'application/json','set-cookie':'SECRET'}
        opener=Mock();opener.open.return_value=r
        with patch.object(h.urllib.request,'build_opener',return_value=opener):
            status,body,headers,elapsed=h.post('countTokens','{"x":"中文"}'.encode(),TOKEN,binding())
        req=opener.open.call_args.args[0]
        self.assertEqual(req.data,'{"x":"中文"}'.encode());self.assertEqual(req._tunnel_host,'aiplatform.googleapis.com')
        self.assertEqual(req.host,'127.0.0.1:10090');self.assertEqual(req.get_header('X-goog-user-project'),h.PROJECT)
        self.assertEqual(headers,{'content-type':'application/json'});opener.open.assert_called_once()
    def test_canary_echo_never_returned(self):
        r=Mock();r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=None);r.read.side_effect=[TOKEN.encode(),b''];r.code=200;r.headers={}
        opener=Mock();opener.open.return_value=r
        with patch.object(h.urllib.request,'build_opener',return_value=opener),self.assertRaises(h.BridgeError):h.post('countTokens',b'{}',TOKEN,binding())
    def test_no_retry_http_error_statuses(self):
        for status in (401,403,429,500,503):
            value,events=result(status=status,raw=b'{"error":"test"}')
            decoded=decode_result(packet(events),value)
            self.assertEqual(decoded['http_status'],status);self.assertEqual(len(events),2)
    def test_timeout_marker_and_no_retry(self):
        e=env();events=[]
        with patch.object(h,'native_host',side_effect=host),patch.object(h,'auth_preflight',side_effect=lambda b,a:identity(b)),patch.object(h,'sdk_call',side_effect=fake_sdk),patch.object(h,'post',side_effect=h.BridgeError('HTTP_TRANSPORT_UNCERTAIN_NO_RETRY')) as post:
            r=h.handle(e,events.append)
        post.assert_called_once();self.assertTrue(r['dispatch_attempted']);self.assertEqual(r['provider_receipt'],'UNKNOWN');self.assertEqual(len(events),1)
        self.assertNotIn(TOKEN,packet(events+[r]).decode())
    def test_receipt_request_host_and_hash_tampering(self):
        for key,value in [('request_sha256','f'*64),('manifest_sha256','f'*64),('request_id','wrong'),('config_sha256','f'*64)]:
            e,events=result();events[-1][key]=value
            with self.subTest(key=key),self.assertRaises(ApiError):decode_result(packet(events),e)
        e,events=result();events[-1]['host']['os']='posix'
        with self.assertRaises(ApiError):decode_result(packet(events),e)
    def test_receipt_clock_and_response_bytes(self):
        e,events=result();self.assertEqual(decode_result(packet(events),e)['http_status'],200)
        for key,value in [('http_elapsed_ns',-1),('response_sha256','f'*64),('transport_retry_index',1),('headers',{'authorization':'SECRET'})]:
            wrong=deepcopy(events);wrong[-1][key]=value
            with self.subTest(key=key),self.assertRaises(ApiError):decode_result(packet(wrong),e)
    def test_missing_or_repeated_dispatch_marker(self):
        e,events=result()
        for rows in ([events[-1]],events+events,events[::-1]):
            with self.assertRaises(ApiError):decode_result(packet(rows),e)
    def test_partial_without_marker_is_unknown(self):
        t=WindowsUserTransport(windows_config(binding()),'a'*64);t._partial(b'',env())
        self.assertIsNone(t.last_dispatch);self.assertEqual(t.unknown_dispatches,1)
    def test_partial_marker_proves_dispatch_attempt_only(self):
        e,events=result();t=WindowsUserTransport(windows_config(binding()),'a'*64);t._partial(h.encode(events[0])+b'\n{',e)
        self.assertTrue(t.last_dispatch);self.assertEqual(t.dispatch_count,1);self.assertEqual(t.last_receipt['provider_receipt'],'UNKNOWN')
    def test_helper_start_failure_is_known_not_dispatched(self):
        t=WindowsUserTransport(windows_config(binding()),'a'*64)
        with patch('rcwg_api.windows_bridge.validate_host'),patch('rcwg_api.windows_bridge.subprocess.run',side_effect=FileNotFoundError),self.assertRaises(ApiError):t.invoke(env())
        self.assertIs(t.last_dispatch,False)
    def test_helper_timeout_retains_unknown(self):
        t=WindowsUserTransport(windows_config(binding()),'a'*64)
        with patch('rcwg_api.windows_bridge.validate_host'),patch('rcwg_api.windows_bridge.subprocess.run',side_effect=subprocess.TimeoutExpired('fixed',300)),self.assertRaises(ApiError):t.invoke(env())
        self.assertIsNone(t.last_dispatch)
    def test_reserved_request_survives_ambiguous_bridge(self):
        with tempfile.TemporaryDirectory() as d:
            c=windows_config(binding());b=Budget(Path(d)/'ledger.sqlite','a'*64,c);b.reserve('same','countTokens')
            t=WindowsUserTransport(c,'a'*64);t._partial(b'',env());b.observe('same','UNKNOWN','f'*64)
            reopened=Budget(Path(d)/'ledger.sqlite','a'*64,c)
            with self.assertRaises(ApiError):reopened.reserve('same','countTokens')
            self.assertEqual(reopened.summary()['reserved_microusd'],10000)
    def test_live_rejects_unregistered_transport_and_executor(self):
        from rcwg_api.pilot import make_manifest,run_pilot
        from rcwg_exec.demo import prepare_fixture
        with tempfile.TemporaryDirectory() as d:
            task,plans,recipe,data=prepare_fixture(Path(d)/'fixture');m=make_manifest(task,windows_config(binding()),{},recipe_sha256=digest(recipe))
            for transport,executor in [(Mock(),None),(WindowsUserTransport(m['config'],digest(m)),lambda:None)]:
                with self.subTest(transport=type(transport).__name__),self.assertRaises(ApiError) as error:
                    run_pilot(task,recipe,data,m,output=Path(d)/'out',mode='LIVE',transport=transport,executor=executor)
                self.assertEqual(error.exception.code,'LIVE_TRANSPORT_OR_EXECUTOR')
    def test_send_without_preflight_never_starts_helper(self):
        t=WindowsUserTransport(windows_config(binding()),'a'*64)
        with patch.object(t,'invoke') as invoke,self.assertRaises(ApiError):t.send_reserved('countTokens',b'{}','r',{})
        invoke.assert_not_called()

    def test_synthetic_driver_receipt_cannot_enter_live_decoder(self):
        e,events=result();events[-1]['synthetic_fixture']=True
        with self.assertRaises(ApiError):decode_result(packet(events),e)
    def test_live_blocks_instance_callable_injection(self):
        from rcwg_api.pilot import make_manifest,run_pilot
        from rcwg_exec.demo import prepare_fixture
        with tempfile.TemporaryDirectory() as d:
            task,plans,recipe,data=prepare_fixture(Path(d)/'fixture');m=make_manifest(task,windows_config(binding()),{},recipe_sha256=digest(recipe))
            transport=WindowsUserTransport(m['config'],digest(m));transport.invoke=lambda v:None
            with self.assertRaises(ApiError) as error:run_pilot(task,recipe,data,m,output=Path(d)/'out',mode='LIVE',transport=transport)
            self.assertEqual(error.exception.code,'LIVE_TRANSPORT_OR_EXECUTOR')
    def test_one_preparation_cannot_reset_by_output_directory(self):
        from rcwg_api.pilot import prepare
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as d,patch('rcwg_api.pilot.ROOT',Path(d)):
            prepare(Path(d)/'runs/first',windows_config(binding()))
            with self.assertRaises(FileExistsError):prepare(Path(d)/'runs/second',windows_config(binding()))
    def test_shared_ledger_concurrent_duplicate_wins_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as d:
            c=windows_config(binding());path=Path(d)/'ledger.sqlite';Budget(path,'a'*64,c)
            def attempt(_):
                try:Budget(path,'a'*64,c).reserve('one','generateContent');return True
                except ApiError:return False
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,range(8)))
            self.assertEqual(results.count(True),1);self.assertEqual(Budget(path,'a'*64,c).summary()['reserved_microusd'],250000)
    def test_real_pilot_reserves_before_bridge_and_reports_unknown(self):
        import time
        from rcwg_api.pilot import make_manifest,run_pilot
        from rcwg_api.policy import source_snapshot
        from rcwg_exec.demo import prepare_fixture
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as d:
            root=Path(d);(root/'runs').mkdir();prepared=root/'runs/prepared';prepared.mkdir()
            task,plans,recipe,data=prepare_fixture(prepared/'fixture');c=windows_config(binding());sources=source_snapshot()
            manifest=make_manifest(task,c,sources,recipe_sha256=digest(recipe));approval=approval_template(manifest)
            offline=root/'offline.json';offline.write_bytes(canonical({'status':'API001_TARGET_OFFLINE_PASS','source_sha256':sources}))
            native=root/'windows.json';native.write_bytes(canonical({'status':'API001_WINDOWS_OFFLINE_PASS','source_sha256':sources,'windows_host':binding()}))
            approval.update(approved=True,data_location_approved=True,pr4_delivery_proof_verified=True,pricing_rechecked_unix=int(time.time()),
                            offline_api_acceptance_sha256=sha(offline.read_bytes()),windows_acceptance_sha256=sha(native.read_bytes()),owner_note='Synthetic test only')
            (root/'runs/api001-win01-one-pilot.json').write_bytes(canonical({'config_sha256':digest(c),'output':str(prepared)}))
            transport=WindowsUserTransport(c,digest(manifest));observed=[]
            def send(self,kind,body,rid,reservation):
                budget=Budget(root/'runs/api001-win01-budget.sqlite',digest(manifest),c).summary()
                observed.append(budget['reservations'][0]['request_id']==rid)
                self._partial(b'',env());raise ApiError('WINDOWS_HELPER_TIMEOUT_NO_RETRY')
            with patch('rcwg_api.pilot.ROOT',root),patch.object(WindowsUserTransport,'validate_live'),patch.object(WindowsUserTransport,'preflight'),patch.object(WindowsUserTransport,'send_reserved',send):
                complete=run_pilot(task,recipe,data,manifest,output=prepared/'observations',mode='LIVE',transport=transport,
                                   approval=approval,offline_acceptance=offline,windows_acceptance=native)
            self.assertEqual(observed,[True]);self.assertIsNone(complete['report']['real_model_service_dispatches'])
            self.assertEqual(complete['report']['unknown_model_dispatches'],1)
            self.assertEqual(Budget(root/'runs/api001-win01-budget.sqlite',digest(manifest),c).summary()['reserved_microusd'],10000)
            self.assertEqual(complete['report']['generations'][1]['status'],'NOT_ATTEMPTED')

    def test_user_independent_audit_handles_null_service_account(self):
        from rcwg_api.live_review import review_live
        c=windows_config(binding());m={'config':c,'expected_generations':[{'generation_id':'p0','stages':['physical']}]}
        auth=[];fake_sdk(binding(),['auth','print-access-token'],auth,True);auth[0]['status']='CREDENTIAL_CAPTURED_IN_WINDOWS_MEMORY'
        report={'mode':'LIVE','real_model_service_dispatches':1,'credential_command_invocations':1,'generations':[{'execution':None}]}
        records={'report.json':report,'expected_generations.json':m,'credential_audit.json':auth,'physical_requests.json':[]}
        with patch('rcwg_api.live_review.audit'),patch('rcwg_api.live_review.read',side_effect=lambda p:records[p.name]):
            reviewed=review_live(Path('/synthetic'),manifest_sha256='a'*64,seal_sha256='b'*64)
        self.assertEqual(reviewed['status'],'API001_LIVE_INCOMPLETE');self.assertFalse(reviewed['formal_ready'])
        auth[0]['argv'].append('--impersonate-service-account=unexpected')
        with patch('rcwg_api.live_review.audit'),patch('rcwg_api.live_review.read',side_effect=lambda p:records[p.name]),self.assertRaises(ApiError):
            review_live(Path('/synthetic'),manifest_sha256='a'*64,seal_sha256='b'*64)

    def test_real_urllib_pipeline_preserves_origin_host_through_proxy(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
        response.read.side_effect=[b'{"totalTokens":1}',b''];response.status=200;response.code=200
        response.reason='OK';response.headers={'content-type':'application/json'};response.fp=None
        connection=Mock();connection.getresponse.return_value=response
        with patch('http.client.HTTPSConnection',return_value=connection) as factory:
            h.post('countTokens',b'{}',TOKEN,binding())
        connection.set_tunnel.assert_called_once_with('aiplatform.googleapis.com',headers={})
        headers=connection.request.call_args.args[3]
        self.assertEqual(headers['Host'],'aiplatform.googleapis.com')
        self.assertEqual(factory.call_args.args[0],'127.0.0.1:10090')

if __name__=='__main__':unittest.main()
