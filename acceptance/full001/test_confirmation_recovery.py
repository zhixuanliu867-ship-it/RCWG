from copy import deepcopy
import json
from pathlib import Path
import unittest
from rcwg_full.reference.confirmation import confirm
from rcwg_full.reference.candidates import candidates
from rcwg_full.data.templates import f1
from rcwg_full.evidence import read
from support import EvidenceDirectory


class ConfirmationRecovery(unittest.TestCase):
    def setUp(self):
        self.evidence=EvidenceDirectory(self.id());self.root=Path(self.evidence.name)
        d=f1('F1-01',0,'C0');self.definitions=candidates(d['task'],d['plan'])
        self.ids=[self.definitions['candidates'][0]['candidate_id']]
        self.context={k:'engineering-golden' for k in ['task_id','condition','data_hash','budget_hash','hardware_hash','runtime_hash','executor_hash','cache_profile','measurement_profile']}
        self.calls=[]
    def tearDown(self):self.evidence.cleanup()
    def execute(self,plan,request):
        self.calls.append(request)
        return {**request,'status':'COMPLETED','semantic':True,'budget':True,'timing_valid':True,'exec_elapsed_ns':100,'mode':'ENGINEERING_GOLDEN'}
    def run_confirmation(self,handler=None,**kwargs):
        return confirm(self.definitions,self.context,handler or self.execute,self.root/'c',candidate_ids=self.ids,**kwargs)

    def test_finished_confirmation_resume_checks_logs_and_never_executes_again(self):
        result=self.run_confirmation();self.assertEqual(len(self.calls),4)
        resumed=self.run_confirmation(resume=True);self.assertEqual(result,resumed);self.assertEqual(len(self.calls),4)
        self.assertEqual(len({r['attempt_id'] for r in self.calls}),4)
        record=self.root/'c/r0001.json';record.write_bytes(read(record).replace(b'100',b'101'))
        with self.assertRaisesRegex(ValueError,'OUTCOME_CHANGED'):self.run_confirmation(resume=True)
        self.assertEqual(len(self.calls),4)

    def test_crash_after_request_persisted_pauses_on_resume_without_duplicate(self):
        def crash(plan,request):self.calls.append(request);raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_confirmation(crash)
        result=self.run_confirmation(resume=True)
        self.assertEqual(len(self.calls),1);self.assertEqual(result['status'],'PAUSED_RECONCILIATION')
        self.assertIn('REQUEST_WITHOUT_COMMITTED_OUTCOME',result['paused_reason']);self.assertFalse(result['confirmed'])

    def test_uncertain_service_stops_group_and_is_not_retried(self):
        def uncertain(plan,request):
            self.calls.append(request);return {**request,'status':'SENT_UNCONFIRMED'}
        first=self.run_confirmation(uncertain);second=self.run_confirmation(resume=True)
        self.assertEqual(first,second);self.assertEqual(len(self.calls),1)
        self.assertIsNone(first['elapsed_ns']);self.assertFalse((self.root/'c/reference.json').exists())

    def test_changed_plan_or_predeclared_identity_rejected(self):
        self.run_confirmation();self.definitions['candidates'][0]['plan']['nodes'][0]['params']['unregistered']=1
        with self.assertRaisesRegex(ValueError,'PLAN_HASH'):self.run_confirmation(resume=True)
        self.assertEqual(len(self.calls),4)
