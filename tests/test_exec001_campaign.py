from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from rcwg_spec.common import canonical,digest
from rcwg_exec.acceptance_cases import LOGICAL
from rcwg_exec.campaign import freeze_attempts,run_campaign,reopen_campaign
from rcwg_exec.demo import prepare_fixture
from rcwg_exec.errors import ExecFault
from rcwg_exec.journal import read_json


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,data=prepare_fixture(self.root/'fixture',n=17,k=3)
        self.base={'task':self.task,'recipe':self.recipe,'locations':{self.task['datasets'][0]['id']:data},'allowed_root':self.root}
    def tearDown(self):self.tmp.cleanup()
    def case(self,ident,protocol='P0',plan=None,**kwargs):
        p=plan or self.plans['streaming_heap']
        responses=[canonical(p)] if protocol=='P0' else [canonical(LOGICAL),canonical(p)]
        return {**deepcopy(self.base),'attempt_id':ident,'protocol':protocol,'responses':responses,**kwargs}
    def test_p0_p1_real_parser_compiler_worker_request_counts(self):
        cases=[self.case('p0'),self.case('p1','P1')];r=run_campaign(cases,output=self.root/'campaign')
        self.assertEqual(r['fixed_denominator'],2)
        for ident,count in [('p0',1),('p1',2)]:
            folder=self.root/'campaign'/ident;record=read_json(folder/'attempt.json');generation=read_json(folder/'generation.json')
            self.assertEqual(record['mock_requests'],count);self.assertEqual(record['generation_attempts'],1)
            self.assertEqual(record['execution_attempts'],1);self.assertEqual(record['real_requests'],0)
            self.assertEqual(record['verification'],'PASS');self.assertEqual(generation['plan'],read_json(folder/'execution/plan.json'))
            for request in generation['records']:
                payload=canonical(request['request']['provider_payload'])
                self.assertNotIn(self.recipe['revision'].encode(),payload);self.assertNotIn(b'expected_result_sha256',payload)
    def test_mock_plan_not_replaced_by_successful_fixed_plan(self):
        c=self.case('wrong',plan=self.plans['omitted_filter']);r=run_campaign([c],output=self.root/'campaign')
        self.assertEqual(r['outcomes'][0]['verification'],'FAIL')
        self.assertEqual(read_json(self.root/'campaign/wrong/execution/plan.json'),self.plans['omitted_filter'])
    def test_parse_static_gap_and_crash_keep_predeclared_slots(self):
        invalid=deepcopy(self.plans['streaming_heap']);invalid['nodes'][2]['params']['k']=-1
        gap=deepcopy(self.plans['streaming_heap']);gap['nodes'][2]['after']=['keep']
        cases=[self.case('parse',responses=[b'{']),self.case('static',plan=invalid),self.case('gap',plan=gap),self.case('crash',fault='crash')]
        r=run_campaign(cases,output=self.root/'campaign')
        self.assertEqual(r['fixed_denominator'],4);self.assertEqual(r['reread']['observed_count'],4)
        self.assertEqual([x['outcome'] for x in r['outcomes']],['MOCK_RESPONSE_INVALID','PLAN_INVALID','RUNTIME_IMPLEMENTATION_GAP','INFRA_FAILURE'])
        for name in ('parse','static','gap'):self.assertFalse((self.root/'campaign'/name/'execution').exists())
    def test_p1_invalid_logical_stops_before_second_request(self):
        r=run_campaign([self.case('logical','P1',responses=[b'{}',canonical(self.plans['streaming_heap'])])],output=self.root/'campaign')
        a=read_json(self.root/'campaign/logical/attempt.json')
        self.assertEqual(a['mock_requests'],1);self.assertEqual(a['execution_attempts'],0)
        self.assertEqual(r['outcomes'][0]['outcome'],'MOCK_RESPONSE_INVALID')
    def test_manifest_is_snapshot_not_mutable_case_reference(self):
        cases=[self.case('a')];e=freeze_attempts(cases);h=e.sha256
        cases[0]['task']['task_id']='changed';cases[0]['responses']=[b'{}']
        self.assertEqual(e.sha256,h);self.assertEqual(e.as_dict()['attempts'][0]['task_hash'],digest(self.task))
        duplicate=[self.case('a'),self.case('a')]
        with self.assertRaises(ExecFault):freeze_attempts(duplicate)
    def test_missing_attempt_remains_in_denominator(self):
        cases=[self.case('a'),self.case('b',responses=[b'{'])];expected=freeze_attempts(cases)
        r=run_campaign(cases,output=self.root/'campaign');(self.root/'campaign/b/attempt.json').unlink()
        reopened=reopen_campaign(self.root/'campaign',expected=expected,summary_sha256=r['summary_sha256'])
        self.assertEqual(reopened['fixed_denominator'],2);self.assertEqual(reopened['missing_attempt_ids'],['b'])
        self.assertEqual(reopened['status'],'CAMPAIGN_INCOMPLETE')
    def test_changed_generation_or_expected_manifest_rejected(self):
        cases=[self.case('a')];e=freeze_attempts(cases);r=run_campaign(cases,output=self.root/'campaign')
        p=self.root/'campaign/a/generation.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ExecFault):reopen_campaign(self.root/'campaign',expected=e,summary_sha256=r['summary_sha256'])
        p=self.root/'campaign/expected_attempts.json';p.write_bytes(b'{}')
        with self.assertRaises(ExecFault):reopen_campaign(self.root/'campaign',expected=e,summary_sha256=r['summary_sha256'])
    def test_execution_repeats_separate_from_generation_ids(self):
        cases=[self.case('r0',generation_id='same-generation',repeat_id='r0'),self.case('r1',generation_id='same-generation',repeat_id='r1')]
        r=run_campaign(cases,output=self.root/'campaign')
        records=[read_json(self.root/'campaign'/name/'attempt.json') for name in ('r0','r1')]
        self.assertNotEqual(records[0]['result']['execution_key'],records[1]['result']['execution_key'])
        self.assertEqual([x['repeat_id'] for x in records],['r0','r1'])
        self.assertEqual([x['generation_attempts'] for x in records],[1,0])
        self.assertEqual([x['mock_requests'] for x in records],[1,0])

if __name__=='__main__':unittest.main()
