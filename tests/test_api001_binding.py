"""Project-binding regressions; all provider and authentication values are synthetic."""
import json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from rcwg_api.common import ApiError,canonical
from rcwg_api.policy import default_config,source_snapshot
from rcwg_api.vertex import GcloudToken

ACCOUNT='zhixuanliu867@gmail.com'
PROJECT='rcwg-509116'
RUNNER='rcwg-api-runner@rcwg-509116.iam.gserviceaccount.com'
TOKEN=b'synthetic-token-for-unit-test-only-123456789'
ROOT=Path(__file__).resolve().parents[1]
def config():
    c=default_config(PROJECT);c['service_account']=RUNNER;return c

class BindingRegressions(unittest.TestCase):
    def test_credential_command_explicit_account_project_runner(self):
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',return_value=subprocess.CompletedProcess([],0,TOKEN,b'')) as run:
            GcloudToken(config())()
        args=run.call_args.args[0]
        self.assertIn('--account='+ACCOUNT,args);self.assertIn('--project='+PROJECT,args)
        self.assertIn('--impersonate-service-account='+RUNNER,args)
    def test_access_token_override_blocks_before_subprocess(self):
        with patch.dict(os.environ,{'CLOUDSDK_AUTH_ACCESS_TOKEN':'synthetic-override'}),patch('rcwg_api.vertex.subprocess.run') as run:
            with self.assertRaisesRegex(ApiError,'AUTH_OVERRIDE'):GcloudToken(config())()
            run.assert_not_called()
    def test_snapshot_includes_actual_ci_configuration(self):
        sources=source_snapshot()
        self.assertTrue(any(p.startswith('.github/workflows/') for p in sources))
    def test_snapshot_includes_retained_tests(self):
        self.assertIn('tests/test_exec001_supervisor.py',source_snapshot())

if __name__=='__main__':unittest.main()

class AuthEvidenceTests(unittest.TestCase):
    def test_wrong_live_project_and_runner_blocked(self):
        from rcwg_api.auth_binding import validate_live_binding
        for project,runner in [('other-project',RUNNER),(PROJECT,'other-runner@'+PROJECT+'.iam.gserviceaccount.com')]:
            c=config();c['project_id']=project;c['service_account']=runner
            with self.assertRaisesRegex(ApiError,'LIVE_IDENTITY'):validate_live_binding(c)
    def test_changed_login_account_rejected_by_config(self):
        from rcwg_api.policy import validate_config
        c=config();c['login_account']='somebody@example.com'
        with self.assertRaisesRegex(ApiError,'CONFIG_POLICY_CHANGED'):validate_config(c)
    def test_preflight_empty_account_list_no_issuance(self):
        token=GcloudToken(config())
        def answer(cmd,**kw):return subprocess.CompletedProcess(cmd,0,b'[]' if 'list' in cmd else b'',b'')
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',side_effect=answer) as run:
            with self.assertRaisesRegex(ApiError,'AUTH_ACCOUNT_NOT_LOGGED_IN'):token.preflight()
        self.assertEqual(token.command_invocations,0)
        self.assertTrue(all('--account='+ACCOUNT in c.args[0] and '--project='+PROJECT in c.args[0] for c in run.call_args_list))
        self.assertFalse(token.preflight_verified)
    def test_preflight_config_override_stops_without_reading_file(self):
        token=GcloudToken(config())
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'/never-read/secret.json',b'')) as run:
            with self.assertRaisesRegex(ApiError,'AUTH_OVERRIDE_CONFIG'):token.preflight()
        self.assertEqual(run.call_count,1);self.assertNotIn('secret.json',json.dumps(token.audit))
    def test_preflight_approved_identity_verified_separately(self):
        token=GcloudToken(config())
        def answer(cmd,**kw):return subprocess.CompletedProcess(cmd,0,canonical([{'account':ACCOUNT,'status':'ACTIVE'}]) if 'list' in cmd else b'',b'')
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',side_effect=answer):
            self.assertEqual(token.preflight()['status'],'BOUND_LOCAL_IDENTITY_VERIFIED')
        self.assertEqual(token.command_invocations,0);self.assertTrue(token.preflight_verified)
    def test_token_failure_is_counted_and_redacted_without_retry(self):
        token=GcloudToken(config())
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',return_value=subprocess.CompletedProcess([],1,b'secret stdout',b'PERMISSION_DENIED 403 confidential stderr')) as run:
            with self.assertRaisesRegex(ApiError,'AUTH_FAILED'):token()
        self.assertEqual(run.call_count,1);self.assertEqual(token.command_invocations,1)
        self.assertEqual(token.audit[0]['http_status'],403)
        self.assertNotIn('secret stdout',json.dumps(token.audit));self.assertNotIn('confidential',json.dumps(token.audit))
    def test_token_timeout_no_retry(self):
        token=GcloudToken(config())
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',side_effect=subprocess.TimeoutExpired('gcloud',40)) as run:
            with self.assertRaisesRegex(ApiError,'AUTH_FAILED'):token()
        self.assertEqual(run.call_count,1);self.assertIsNone(token.audit[0]['exit_code'])
    def test_environment_override_rechecked_even_when_token_cached(self):
        token=GcloudToken(config());token.cached=TOKEN.decode();token.at=__import__('time').monotonic()
        with patch.dict(os.environ,{'CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT':'unapproved@example.com'}):
            with self.assertRaisesRegex(ApiError,'AUTH_OVERRIDE_PRINCIPAL'):token()
    def test_http_logging_environment_blocked(self):
        with patch.dict(os.environ,{'CLOUDSDK_CORE_LOG_HTTP':'true'}):
            with self.assertRaisesRegex(ApiError,'AUTH_HTTP_LOGGING'):GcloudToken(config())()
    def test_quota_override_cannot_route_to_another_project(self):
        with patch.dict(os.environ,{'CLOUDSDK_BILLING_QUOTA_PROJECT':'other-project'}):
            with self.assertRaisesRegex(ApiError,'AUTH_OVERRIDE_QUOTA_PROJECT'):GcloudToken(config())()
    def test_preserved_test_bytes_checked_not_just_method_ids(self):
        from rcwg_api.policy import check_retained_test_sources
        from rcwg_api.common import sha
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'specs/api001').mkdir(parents=True);(root/'tests').mkdir()
            p=root/'tests/test_api001.py';p.write_bytes(b'original required assertions')
            (root/'specs/api001/retained_test_source_sha256.json').write_bytes(canonical({'files_sha256':{'tests/test_api001.py':sha(p.read_bytes())}}))
            self.assertEqual(check_retained_test_sources(root),1)
            p.write_bytes(b'weakened assertions with same method IDs')
            with self.assertRaisesRegex(ApiError,'RETAINED_TEST_BYTES_CHANGED'):check_retained_test_sources(root)

class LiveAdmissionEvidenceTests(unittest.TestCase):
    def setup_case(self,root):
        from rcwg_exec.demo import prepare_fixture
        from rcwg_api.pilot import make_manifest
        from rcwg_api.policy import approval_template
        from rcwg_api.common import digest,sha
        import time
        task,plans,recipe,data=prepare_fixture(root/'fixture',n=11,k=3)
        manifest=make_manifest(task,config(),source_snapshot(),recipe_sha256=digest(recipe))
        offline=root/'synthetic-offline.json';offline.write_bytes(canonical({'status':'API001_TARGET_OFFLINE_PASS','source_sha256':manifest['source_sha256']}))
        approval=approval_template(manifest);approval.update(approved=True,data_location_approved=True,pr4_delivery_proof_verified=True,
            offline_api_acceptance_sha256=sha(offline.read_bytes()),owner_note='SYNTHETIC UNIT TEST ONLY',pricing_rechecked_unix=int(time.time()))
        return task,recipe,data,manifest,approval,offline
    def test_auth_failure_sealed_with_fixed_slots_and_zero_reservations(self):
        from rcwg_api.pilot import run_pilot
        from rcwg_api.vertex import VertexTransport
        from rcwg_api.common import read
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,recipe,data,m,a,offline=self.setup_case(root)
            token=GcloudToken(config());transport=VertexTransport(config(),token)
            with patch.object(token,'preflight',side_effect=ApiError('AUTH_ACCOUNT_NOT_LOGGED_IN')),patch.object(transport.opener,'open',side_effect=AssertionError('NETWORK FORBIDDEN')) as opened:
                result=run_pilot(task,recipe,data,m,output=root/'observation',mode='LIVE',transport=transport,approval=a,offline_acceptance=offline)
            opened.assert_not_called();report=result['report']
            self.assertEqual(report['stop_reason'],'AUTH_ACCOUNT_NOT_LOGGED_IN')
            self.assertEqual([g['status'] for g in report['generations']],['NOT_ATTEMPTED','NOT_ATTEMPTED'])
            self.assertEqual(report['real_model_service_dispatches'],0)
            self.assertEqual(read(root/'observation/budget_snapshot.json')['reserved_microusd'],0)
            self.assertEqual(result['reread']['status'],'API001_EVIDENCE_REOPENED')
    def test_transport_config_mismatch_blocked_before_authentication(self):
        from rcwg_api.pilot import run_pilot
        from rcwg_api.vertex import VertexTransport
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,recipe,data,m,a,offline=self.setup_case(root)
            wrong=config();wrong['allow_environment_proxy']=True
            token=GcloudToken(config());transport=VertexTransport(wrong,token)
            with patch.object(token,'preflight',side_effect=AssertionError('AUTH FORBIDDEN')):
                with self.assertRaisesRegex(ApiError,'LIVE_AUTH_TRANSPORT_BINDING'):
                    run_pilot(task,recipe,data,m,output=root/'observation',mode='LIVE',transport=transport,approval=a,offline_acceptance=offline)
    def test_unapproved_callable_cannot_supply_live_token(self):
        from rcwg_api.pilot import run_pilot
        from rcwg_api.vertex import VertexTransport
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task,recipe,data,m,a,offline=self.setup_case(root)
            transport=VertexTransport(config(),lambda:'UNAPPROVED TEST TOKEN')
            with self.assertRaisesRegex(ApiError,'LIVE_AUTH_TRANSPORT_BINDING'):
                run_pilot(task,recipe,data,m,output=root/'observation',mode='LIVE',transport=transport,approval=a,offline_acceptance=offline)

class GcloudBooleanRegression(unittest.TestCase):
    def test_actual_gcloud_false_spelling_does_not_block_closed_logging(self):
        token=GcloudToken(config())
        def answer(cmd,**kw):
            raw=canonical([{'account':ACCOUNT,'status':'ACTIVE'}]) if 'list' in cmd else b'False\n' if 'core/log_http' in cmd else b''
            return subprocess.CompletedProcess(cmd,0,raw,b'')
        with patch('rcwg_api.vertex.shutil.which',return_value='/synthetic/gcloud'),patch('rcwg_api.vertex.subprocess.run',side_effect=answer):
            self.assertEqual(token.preflight()['status'],'BOUND_LOCAL_IDENTITY_VERIFIED')
        self.assertEqual(token.command_invocations,0)
