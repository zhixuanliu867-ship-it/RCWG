"""Offline API contract tests. All HTTP responses below are synthetic fixtures."""
from __future__ import annotations
from copy import deepcopy
import concurrent.futures
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from rcwg_api.common import ApiError,canonical,strict,digest,Archive,read,sha
from rcwg_api.policy import default_config,validate_config,endpoint,approval_template,validate_approval,check_exec_sources,source_snapshot
from rcwg_api.budget import Budget
from rcwg_api.vertex import Response,VertexTransport,GcloudToken,NoRedirect,make_body,count_body,parse_count,parse_generation,usage_metadata,RUNTIME_NOTE
from rcwg_api.mock import MockTransport,count,generated,wire_fixtures
from rcwg_api.pilot import make_manifest,run_pilot,audit
from rcwg_spec.generation import build_request
from rcwg_spec.common import load
from rcwg_exec.demo import prepare_fixture

ROOT=Path(__file__).resolve().parents[1]

def cfg():return default_config('rcwg-pilot-test')
def fake_exec(task,plan,recipe,data,output,generation_id):
    from rcwg_spec.compiler import validate_workflow
    result=validate_workflow(task,plan)
    return {'status':result['status'],'terminal_status':'COMPLETED','verification':{'status':'UNKNOWN'},
            'execution_started':False,'test_only':True,'observed_plan_sha256':digest(plan),'formal_ready':False}

class JsonTests(unittest.TestCase):
    def test_duplicates(self):
        with self.assertRaises(ApiError):strict(b'{"a":1,"a":2}')
    def test_exponent_overflow(self):
        with self.assertRaises(ApiError):strict(b'{"a":1e400}')
    def test_nan(self):
        with self.assertRaises(ApiError):strict(b'{"a":NaN}')
    def test_invalid_utf8(self):
        with self.assertRaises(ApiError):strict(b'\xff')
    def test_empty(self):
        with self.assertRaises(ApiError):strict(b'')
    def test_limit(self):
        with self.assertRaises(ApiError):strict(b'{}',limit=1)
    def test_roundtrip(self):self.assertEqual(strict(canonical({'汉字':[1,0.5,None]})),{'汉字':[1,0.5,None]})
    def test_json_nan_write(self):
        with self.assertRaises(ApiError):canonical(float('nan'))
    def test_private_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            a=Archive(Path(d)/'a');a.json('x.json',{})
            with self.assertRaises(FileExistsError):a.json('x.json',{})
            self.assertEqual((a.path/'x.json').stat().st_mode&0o777,0o600)
    def test_private_path_escape_name(self):
        with tempfile.TemporaryDirectory() as d:
            a=Archive(Path(d)/'a')
            with self.assertRaises(ApiError):a.json('../x',{})
    def test_private_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'real').mkdir();(p/'link').symlink_to(p/'real',target_is_directory=True)
            with self.assertRaises(ApiError):Archive(p/'link'/'a')

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.c=cfg();self.c['service_account']='rcwg-infer@rcwg-pilot-test.iam.gserviceaccount.com'
        task=load(ROOT/'specs/reference_v1_0/examples/task_input.json')
        self.m=make_manifest(task,self.c,{})
        self.a=approval_template(self.m);self.a.update(approved=True,data_location_approved=True,
             pr4_delivery_proof_verified=True,offline_api_acceptance_sha256='a'*64,owner_note='test fixture',
             expires_unix=2000,pricing_rechecked_unix=999)
    def test_valid_config(self):self.assertEqual(validate_config(self.c),self.c)
    def test_fixed_endpoint(self):self.assertEqual(endpoint(self.c,'generateContent'),'https://aiplatform.googleapis.com/v1/projects/rcwg-pilot-test/locations/global/publishers/google/models/gemini-3.1-flash-lite:generateContent')
    def test_invalid_kind(self):
        with self.assertRaises(ApiError):endpoint(self.c,'delete')
    def test_project_url_injection(self):
        self.c['project_id']='a/../../secrets'
        with self.assertRaises(ApiError):validate_config(self.c)
    def test_model_override(self):
        self.c['model']='other-model'
        with self.assertRaises(ApiError):validate_config(self.c)
    def test_policy_unknown_field(self):
        self.c['endpoint']='https://evil.example'
        with self.assertRaises(ApiError):validate_config(self.c)
    def test_high_request_cap(self):
        self.c['max_requests']['generateContent']=10
        with self.assertRaises(ApiError):validate_config(self.c)
    def test_token_limits_unchanged(self):self.assertEqual(self.c['output_limits']['P0.physical'],self.c['output_limits']['P1.logical']+self.c['output_limits']['P1.physical'])
    def test_other_project_principal(self):
        self.c['service_account']='rcwg-infer@other-project.iam.gserviceaccount.com'
        with self.assertRaises(ApiError):validate_config(self.c)
    def test_no_approval(self):
        self.a['approved']=False
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_exact_approval(self):self.assertTrue(validate_approval(self.a,self.m,now=1000)['approved'])
    def test_truthy_string_rejected(self):
        self.a['approved']='true'
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_expired(self):
        self.a['expires_unix']=1000
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_long_approval(self):
        self.a['expires_unix']=1000000
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_wrong_manifest(self):
        self.a['manifest_sha256']='b'*64
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_price_future(self):
        self.a['pricing_rechecked_unix']=1001
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_x15_proof_required(self):
        self.a['pr4_delivery_proof_verified']=False
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_private_region_approval(self):
        self.a['data_location_approved']=False
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)
    def test_no_offline_proof(self):
        self.a['offline_api_acceptance_sha256']=''
        with self.assertRaises(ApiError):validate_approval(self.a,self.m,now=1000)

class BudgetTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'ledger.sqlite';self.c=cfg()
    def tearDown(self):self.tmp.cleanup()
    def test_reserve_persists(self):
        b=Budget(self.p,'a'*64,self.c);b.reserve('r1','generateContent')
        self.assertEqual(Budget(self.p,'a'*64,self.c).summary()['reserved_microusd'],250000)
    def test_no_refund(self):
        b=Budget(self.p,'a'*64,self.c);b.reserve('r1','generateContent');b.observe('r1','HTTP_500','b'*64)
        self.assertEqual(b.summary()['reserved_microusd'],250000)
    def test_duplicate_id(self):
        b=Budget(self.p,'a'*64,self.c);b.reserve('r1','countTokens')
        with self.assertRaises(ApiError):b.reserve('r1','countTokens')
    def test_other_manifest(self):
        Budget(self.p,'a'*64,self.c)
        with self.assertRaises(ApiError):Budget(self.p,'b'*64,self.c)
    def test_request_limits(self):
        b=Budget(self.p,'a'*64,self.c)
        for i in range(3):b.reserve('r'+str(i),'generateContent')
        with self.assertRaises(ApiError):b.reserve('r3','generateContent')
    def test_six_total_reserve(self):
        b=Budget(self.p,'a'*64,self.c)
        for i in range(3):
            b.reserve('c'+str(i),'countTokens');b.reserve('g'+str(i),'generateContent')
        self.assertEqual(b.summary()['reserved_microusd'],780000)
        self.assertIsNone(b.summary()['invoice_cost_usd'])
    def test_concurrent_limits(self):
        Budget(self.p,'a'*64,self.c)
        def reserve(i):
            try:Budget(self.p,'a'*64,self.c).reserve('g'+str(i),'generateContent');return True
            except ApiError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(reserve,range(16))),3)
    def test_finish_without_reserve(self):
        with self.assertRaises(ApiError):Budget(self.p,'a'*64,self.c).observe('a','PASS','b'*64)
    def test_finish_twice(self):
        b=Budget(self.p,'a'*64,self.c);b.reserve('r','generateContent');b.observe('r','PASS','b'*64)
        with self.assertRaises(ApiError):b.observe('r','PASS','b'*64)
    def test_world_readable_ledger(self):
        self.p.write_text('');self.p.chmod(0o644)
        with self.assertRaises(ApiError):Budget(self.p,'a'*64,self.c)
    def test_symlink_ledger(self):
        original=Path(self.tmp.name)/'original';original.write_text('');self.p.symlink_to(original)
        with self.assertRaises(ApiError):Budget(self.p,'a'*64,self.c)

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.c=cfg();self.task=load(ROOT/'specs/reference_v1_0/examples/task_input.json')
        self.a=build_request(self.task,protocol='P0',stage='physical',generation_attempt_id='g',request_id='r')
    def test_system_in_count(self):
        body=make_body(self.a,self.c);cnt=count_body(body)
        self.assertEqual(cnt['systemInstruction'],body['systemInstruction']);self.assertEqual(cnt['contents'],body['contents'])
    def test_no_tools_or_schema_conversion(self):
        body=make_body(self.a,self.c)
        self.assertEqual(set(body),{'systemInstruction','contents','generationConfig'})
        self.assertEqual(body['generationConfig']['responseMimeType'],'application/json')
    def test_supported_profile_public(self):self.assertIn('ENGINEERING PROFILE',make_body(self.a,self.c)['systemInstruction']['parts'][-1]['text'])
    def test_seed_not_claimed(self):self.assertNotIn('seed',make_body(self.a,self.c)['generationConfig'])
    def test_count(self):self.assertEqual(parse_count(count(123))['estimated_input_tokens'],123)
    def test_count_boolean(self):
        with self.assertRaises(ApiError):parse_count(count(True))
    def test_count_http_failure(self):
        with self.assertRaises(ApiError):parse_count(Response(429,b'{}',{},1))
    def test_valid_text(self):self.assertEqual(parse_generation(generated({'a':1}),self.c)['text'],'{"a":1}')
    def test_truncation_never_parseable_success(self):self.assertEqual(parse_generation(generated({},finish='MAX_TOKENS'),self.c)['status'],'OUTPUT_TRUNCATED')
    def test_candidate_count(self):
        body={'candidates':[{},{}]}
        with self.assertRaises(ApiError):parse_generation(Response(200,canonical(body),{},1),self.c)
    def test_safety_block(self):
        body={'promptFeedback':{'blockReason':'SAFETY'}}
        self.assertEqual(parse_generation(Response(200,canonical(body),{},1),self.c)['status'],'PROVIDER_BLOCKED')
    def test_bad_feedback_shape(self):
        with self.assertRaises(ApiError):parse_generation(Response(200,b'{"promptFeedback":null}',{},1),self.c)
    def test_function_call_rejected(self):
        body=strict(generated({}).body);body['candidates'][0]['content']['parts']=[{'functionCall':{'name':'run'}}]
        with self.assertRaises(ApiError):parse_generation(Response(200,canonical(body),{},1),self.c)
    def test_missing_usage_not_zero(self):
        v=parse_generation(generated({},usage=False),self.c)['usage']
        self.assertIsNone(v['provider_fields']['promptTokenCount']);self.assertIsNone(v['cost_usd_list_price_upper_estimate'])
    def test_thoughts_in_cost(self):
        v=usage_metadata({'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'thoughtsTokenCount':30,'totalTokenCount':150}},self.c)
        self.assertEqual(Decimal(v['cost_usd_list_price_upper_estimate']),Decimal('0.000100'))
    def test_missing_thoughts_stays_null(self):
        v=usage_metadata({'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'totalTokenCount':150}},self.c)
        self.assertIsNone(v['provider_fields']['thoughtsTokenCount']);self.assertIsNotNone(v['cost_usd_list_price_upper_estimate'])
    def test_usage_inconsistency(self):
        with self.assertRaises(ApiError):usage_metadata({'usageMetadata':{'promptTokenCount':10,'totalTokenCount':9}},self.c)
    def test_usage_boolean(self):
        with self.assertRaises(ApiError):usage_metadata({'usageMetadata':{'totalTokenCount':True}},self.c)
    def test_tool_usage(self):
        with self.assertRaises(ApiError):usage_metadata({'usageMetadata':{'toolUsePromptTokenCount':1}},self.c)
    def test_redirect(self):
        with self.assertRaises(ApiError):NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
    def test_auth_command_no_shell_or_stderr(self):
        c=self.c;c['service_account']='rcwg-infer@rcwg-pilot-test.iam.gserviceaccount.com'
        result=subprocess.CompletedProcess([],1,b'',b'confidential auth failure')
        with patch('rcwg_api.vertex.shutil.which',return_value='/fake/gcloud'),patch('rcwg_api.vertex.subprocess.run',return_value=result) as run:
            with self.assertRaisesRegex(ApiError,'AUTH_FAILED'):GcloudToken(c)()
            self.assertNotIn('shell',run.call_args.kwargs)
    def test_auth_token_not_persisted(self):
        c=self.c;c['service_account']='rcwg-infer@rcwg-pilot-test.iam.gserviceaccount.com'
        result=subprocess.CompletedProcess([],0,b'test-token-only-01234567890123456789\n',b'')
        with patch('rcwg_api.vertex.shutil.which',return_value='/fake/gcloud'),patch('rcwg_api.vertex.subprocess.run',return_value=result) as run:
            token=GcloudToken(c);self.assertEqual(token(),token());self.assertEqual(run.call_count,1)
    def test_transport_no_retry(self):
        c=self.c;t=VertexTransport(c,lambda:'offline-token-fixture')
        with patch.object(t.opener,'open',side_effect=OSError('must not disclose credentials')) as opened:
            with self.assertRaisesRegex(ApiError,'TRANSPORT_UNCERTAIN'):t.send('generateContent',b'{}','r')
            self.assertEqual(opened.call_count,1)
    def test_transport_body_cap_before_auth(self):
        t=VertexTransport(self.c,lambda:self.fail('auth should not run'))
        with self.assertRaises(ApiError):t.send('generateContent',b'x'*131073,'r')

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,self.data=prepare_fixture(self.root/'fixture',n=37,k=5)
        self.manifest=make_manifest(self.task,cfg(),source_snapshot())
    def tearDown(self):self.tmp.cleanup()
    def run_it(self,responses=None,executor=fake_exec):
        self.transport=MockTransport(responses or wire_fixtures(self.plans['streaming_heap']))
        return run_pilot(self.task,self.recipe,self.data,self.manifest,output=self.root/'run',transport=self.transport,executor=executor)
    def test_manifest_before_unknown_responses(self):
        text=canonical(self.manifest).decode();self.assertNotIn('response_sha256',text);self.assertNotIn('plan_sha256',text)
        self.assertEqual(self.manifest['fixed_generation_denominator'],2)
    def test_p0_p1_six_wire_calls(self):
        r=self.run_it();self.assertEqual(len(self.transport.calls),6)
        self.assertEqual(r['report']['actual_generate_dispatches'],3);self.assertEqual(r['report']['real_model_service_dispatches'],0)
    def test_exact_plan_to_executor(self):
        seen=[]
        def execute(task,plan,*args):seen.append(deepcopy(plan));return {'status':'TEST_ONLY','terminal_status':'COMPLETED'}
        self.run_it(executor=execute);self.assertEqual(seen,[self.plans['streaming_heap']]*2)
    def test_no_recipe_in_requests(self):
        self.recipe['PRIVATE_CANARY']='HIDDEN_PRIVATE_FACT_7319'
        self.run_it()
        for _,body,_ in self.transport.calls:self.assertNotIn(b'HIDDEN_PRIVATE_FACT_7319',body)
    def test_failed_first_keeps_second_slot(self):
        r=self.run_it([Response(403,b'{"error":"private"}',{},1)])['report']
        self.assertEqual(len(r['generations']),2);self.assertEqual(r['generations'][1]['status'],'NOT_ATTEMPTED');self.assertEqual(len(self.transport.calls),1)
    def test_count_over_cap_no_generate(self):
        self.run_it([count(12289)]);self.assertEqual(len(self.transport.calls),1)
    def test_transport_failure_reserved(self):
        self.run_it([ApiError('TRANSPORT_UNCERTAIN_NO_RETRY')])
        b=Budget(self.root/'api001-budget.sqlite',digest(self.manifest),cfg())
        self.assertEqual(b.summary()['reserved_microusd'],10000)
    def test_invalid_json_output(self):
        body=strict(generated({}).body);body['candidates'][0]['content']['parts'][0]['text']='```json\n{}\n```'
        r=self.run_it([count(),Response(200,canonical(body),{},1)])['report'];self.assertEqual(r['generations'][1]['status'],'NOT_ATTEMPTED')
    def test_p1_invalid_logical_no_physical(self):
        r=self.run_it([count(),generated(self.plans['streaming_heap']),count(),generated({})])
        self.assertEqual(len(self.transport.calls),4);self.assertEqual(r['report']['actual_generate_dispatches'],2)
    def test_truncated_stop(self):
        r=self.run_it([count(),generated({},finish='MAX_TOKENS')])['report'];self.assertEqual(r['stop_reason'],'OUTPUT_TRUNCATED')
    def test_archive_tamper(self):
        r=self.run_it();(self.root/'run/physical_requests.json').write_bytes(b'[]')
        with self.assertRaises(ApiError):audit(self.root/'run',digest(self.manifest),r['seal_sha256'])
    def test_archive_added_file(self):
        r=self.run_it();(self.root/'run/extra').write_bytes(b'x')
        with self.assertRaises(ApiError):audit(self.root/'run',digest(self.manifest),r['seal_sha256'])
    def test_output_not_overwritten(self):
        self.run_it()
        with self.assertRaises(FileExistsError):self.run_it()
    def test_budget_cannot_reset_by_output_name(self):
        self.run_it()
        t=MockTransport(wire_fixtures(self.plans['streaming_heap']))
        r=run_pilot(self.task,self.recipe,self.data,self.manifest,output=self.root/'other-output',transport=t,executor=fake_exec)
        self.assertEqual(len(t.calls),0);self.assertEqual(r['report']['stop_reason'],'REQUEST_ALREADY_RESERVED')
    def test_live_mock_transport_blocked(self):
        with self.assertRaises(ApiError):run_pilot(self.task,self.recipe,self.data,self.manifest,output=self.root/'live',transport=MockTransport([]),mode='LIVE')
    def test_mock_live_transport_blocked(self):
        with self.assertRaises(ApiError):run_pilot(self.task,self.recipe,self.data,self.manifest,output=self.root/'mock',transport=VertexTransport(cfg(),lambda:'not-used'),mode='MOCK')
    def test_modified_slot_rejected(self):
        self.manifest['expected_generations'].pop()
        with self.assertRaises(ApiError):self.run_it()
    def test_real_reference_positive_pipeline(self):
        from rcwg_exec.runner import run_f1_reference
        from rcwg_exec.datasets import FileRegistry
        def execute(task,plan,recipe,data,output,generation_id):
            reg=FileRegistry(task,{recipe['source_id']:data},allowed_root=self.root)
            return run_f1_reference(task,plan,registry=reg,recipe=recipe,output=output,record_id=generation_id,generation_id=generation_id)
        r=self.run_it(executor=execute)['report']
        self.assertEqual([g['execution']['verification']['status'] for g in r['generations']],['PASS','PASS'])
        self.assertIsNone(r['budget_within'])
    def test_real_reference_wrong_answer_preserved(self):
        from rcwg_exec.runner import run_f1_reference
        from rcwg_exec.datasets import FileRegistry
        def execute(task,plan,recipe,data,output,generation_id):
            return run_f1_reference(task,plan,registry=FileRegistry(task,{recipe['source_id']:data},allowed_root=self.root),recipe=recipe,output=output,record_id=generation_id,generation_id=generation_id)
        r=self.run_it(wire_fixtures(self.plans['omitted_filter']),execute)['report']
        self.assertEqual([g['execution']['verification']['status'] for g in r['generations']],['FAIL','FAIL'])

if __name__=='__main__':unittest.main()

class EvidenceBoundaryTests(unittest.TestCase):
    def test_mock_archive_cannot_be_live_review(self):
        from rcwg_api.live_review import review_live
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);task,plans,recipe,data=prepare_fixture(p/'fixture',n=5,k=2)
            m=make_manifest(task,cfg(),source_snapshot())
            r=run_pilot(task,recipe,data,m,output=p/'run',transport=MockTransport(wire_fixtures(plans['streaming_heap'])),executor=fake_exec)
            with self.assertRaisesRegex(ApiError,'LIVE_EVIDENCE_REQUIRED'):
                review_live(p/'run',manifest_sha256=digest(m),seal_sha256=r['seal_sha256'])
    def test_thought_flag_must_be_boolean(self):
        value=strict(generated({}).body);value['candidates'][0]['content']['parts'][0]['thought']='true'
        with self.assertRaises(ApiError):parse_generation(Response(200,canonical(value),{},1),cfg())
    def test_missing_gcloud_no_token_print(self):
        c=cfg();c['service_account']='rcwg-infer@rcwg-pilot-test.iam.gserviceaccount.com'
        with patch('rcwg_api.vertex.shutil.which',return_value=None):
            with self.assertRaisesRegex(ApiError,'GCLOUD_NOT_INSTALLED'):GcloudToken(c)()
    def test_private_token_never_serialized_by_request_builder(self):
        a=build_request(load(ROOT/'specs/reference_v1_0/examples/task_input.json'),protocol='P0',stage='physical',generation_attempt_id='g',request_id='r')
        self.assertNotIn(b'Authorization',canonical(make_body(a,cfg())))
    def test_nonstop_preserves_finish(self):
        p=parse_generation(generated({},finish='SAFETY'),cfg());self.assertEqual(p['finish_reason'],'SAFETY');self.assertIsNone(p['text'])

class ArchiveFailureTests(unittest.TestCase):
    def test_post_io_archive_failure_preserves_dispatch_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);task,plans,recipe,data=prepare_fixture(p/'fixture',n=5,k=2)
            m=make_manifest(task,cfg(),source_snapshot());t=MockTransport(wire_fixtures(plans['streaming_heap']))
            original=Archive.put
            def broken(store,name,raw):
                if name.endswith('.response.bin'):raise OSError('simulated disk fault')
                return original(store,name,raw)
            with patch.object(Archive,'put',broken):
                report=run_pilot(task,recipe,data,m,output=p/'run',transport=t,executor=fake_exec)['report']
            self.assertEqual(report['observed_transport_dispatches'],1)
            self.assertEqual(report['actual_count_dispatches'],1)
            self.assertTrue(report['transport_and_ledger_counts_match'])
            self.assertEqual(Budget(p/'api001-budget.sqlite',digest(m),cfg()).summary()['reservations'][0]['status'],'RESERVED_BEFORE_IO')

class PreFreezeTests(unittest.TestCase):
    def test_live_requires_pre_generation_verifier_recipe(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);task,plans,recipe,data=prepare_fixture(p/'fixture',n=5,k=2)
            m=make_manifest(task,cfg(),source_snapshot())
            t=VertexTransport(cfg(),lambda:self.fail('credentials must not be accessed'))
            with patch('rcwg_api.pilot.check_exec_sources',return_value='verified'):
                with self.assertRaisesRegex(ApiError,'VERIFIER_RECIPE_NOT_PREFROZEN'):
                    run_pilot(task,recipe,data,m,output=p/'run',transport=t,mode='LIVE')
    def test_live_data_integrity_checked_before_credential_access(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);task,plans,recipe,data=prepare_fixture(p/'fixture',n=5,k=2)
            m=make_manifest(task,cfg(),source_snapshot(),recipe_sha256=digest(recipe))
            data.write_bytes(b'changed')
            t=VertexTransport(cfg(),lambda:self.fail('credentials must not be accessed'))
            with patch('rcwg_api.pilot.check_exec_sources',return_value='verified'):
                with self.assertRaisesRegex(ApiError,'DATA_CHANGED_BEFORE_API'):
                    run_pilot(task,recipe,data,m,output=p/'run',transport=t,mode='LIVE')
