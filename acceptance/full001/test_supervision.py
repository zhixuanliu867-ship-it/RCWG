import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from rcwg_full.evidence import ROOT,read,sha
from rcwg_full.data.prepare import prepare
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.supervisor import execute
from support import EvidenceDirectory
from rcwg_full.verification.layers import verify_layers


class Supervision(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
        self.task=json.loads((ROOT/'specs/reference_v1_0/examples/task_input.json').read_text('utf-8'))
        self.plan=json.loads((ROOT/'specs/reference_v1_0/examples/workflow_topk.json').read_text('utf-8'))
        self.rows=[{'id':i,'score':float(i),'eligible':i%2==0} for i in range(37)]
        self.task['datasets'][0]['stats']['row_count']=len(self.rows)
        self.task['resources'].update(cpu_slots=2,worker_memory_limit_bytes=64*1024*1024,wall_timeout_s=10)
        self.task,self.manifest,self.manifest_path=prepare(self.task,{'dataset:records:v1':pa.Table.from_pylist(self.rows)},self.root/'data')
    def tearDown(self):self.tmp.cleanup()

    def test_real_worker_independent_result_and_existing_identity_binding(self):
        expected=[{'id':r['id'],'score':r['score']} for r in reversed(self.rows) if r['eligible']][:20]
        def verifier(actual,out):return {'status':'PASS' if actual==expected else 'FAIL','recipe':'independent-direct-definition'}
        report=execute(self.task,self.plan,self.manifest_path,build=os.environ['RCWG_FULL_BUILD'],output=self.root/'run',verify=verifier)
        self.assertEqual(report['terminal_status'],'COMPLETED',report)
        self.assertEqual(report['verification']['status'],'PASS');self.assertFalse(report['formal_ready'])
        self.assertEqual(report['exec_elapsed_scope'],'CONTROLLER_GO_TO_COMMITTED_RESULT_RECEIPT')
        self.assertEqual(report['exec_elapsed_ns'],report['result_received_monotonic_ns']-report['exec_started_monotonic_ns'])
        self.assertGreaterEqual(report['exec_elapsed_ns'],report['worker']['worker_exec_wall_ns'])
        self.assertEqual(report['process_group_final']['live'],[]);self.assertEqual(report['cleanup_failures'],[])
        self.assertEqual(report['binding_validation']['expected_count'],1)
        self.assertTrue((self.root/'run'/'sidecar.json').exists());self.assertTrue((self.root/'run'/'seal.json').exists())
        self.assertNotIn('private_verifier_recipe',json.loads(read(self.root/'run'/'request.json')))
        verdict=verify_layers(self.root/'run',{'kind':'relational','expected':expected,'contract':{'comparison':'ordered'}})
        self.assertEqual(verdict['software_result'],'PASS',verdict);self.assertEqual(verdict['status'],'UNKNOWN')
        self.assertEqual(verdict['layers']['L4']['status'],'UNKNOWN')

    def test_external_deadline_has_observed_cause_and_no_oom_guess(self):
        report=execute(self.task,self.plan,self.manifest_path,build=os.environ['RCWG_FULL_BUILD'],output=self.root/'deadline',timeout_s=.001)
        self.assertEqual(report['terminal_status'],'TIMEOUT',report);self.assertEqual(report['failure']['code'],'WALL_TIMEOUT')
        self.assertEqual(report['verification']['status'],'UNKNOWN');self.assertEqual(report['process_group_final']['live'],[])

    def test_real_reference_screen_has_reference_role_and_shared_context(self):
        import uuid
        from rcwg_full.evidence import write,digest
        from rcwg_full.reference.execution import NativeReferenceExecutor
        gold=self.root/'gold.json';expected=[{'id':r['id'],'score':r['score']} for r in reversed(self.rows) if r['eligible']][:20]
        write(gold,{'expected':expected,'comparison':'ordered'})
        executor=NativeReferenceExecutor(self.task,self.manifest_path,gold,os.environ['RCWG_FULL_BUILD'],self.root/'reference-runs',condition='C0')
        request={'candidate_id':'reference-candidate','attempt_id':str(uuid.uuid4()),'plan_hash':digest(self.plan),
            'role':'REFERENCE_SCREEN','repeat':0,'context_hash':executor.context.comparison_context_hash}
        result=executor(self.plan,request);self.assertEqual(result['status'],'COMPLETED')
        self.assertTrue(result['semantic']);self.assertTrue(result['timing_valid']);self.assertIsNone(result['budget'])
        manifest=json.loads(read(self.root/'reference-runs'/request['attempt_id']/'expected.json'))
        self.assertEqual(manifest['expected_records'][0]['record_role'],'REFERENCE')

    def test_real_e2_target_keeps_c0_plan_through_worker_and_seal(self):
        from rcwg_full.campaign.planning import rebind_frozen
        from rcwg_full.evidence import digest
        original=copy.deepcopy(self.plan);task=copy.deepcopy(self.task);task['task_id']=self.task['task_id']+'-C2'
        task['resources']['worker_memory_limit_bytes']//=2
        common={'template_id':'F1-01','base_id':0,'generator':'G0','protocol':'P1','trial_label':17}
        frozen=rebind_frozen(original,{**common,'task_id':self.task['task_id'],'condition':'C0'},{**common,'task_id':task['task_id'],'condition':'C2'})
        expected=[{'id':r['id'],'score':r['score']} for r in reversed(self.rows) if r['eligible']][:20]
        result=execute(task,original,self.manifest_path,build=os.environ['RCWG_FULL_BUILD'],output=self.root/'frozen',condition_id='C2',
            frozen_binding=frozen,verify=lambda actual,out:{'status':'PASS' if actual==expected else 'FAIL'})
        self.assertEqual(result['terminal_status'],'COMPLETED',result);self.assertEqual(result['verification']['status'],'PASS')
        sealed=json.loads(read(self.root/'frozen/expected.json'))
        self.assertEqual(sealed['expected_records'][0]['plan_hash'],digest(original));self.assertEqual(original,self.plan)

    def test_data_file_tamper_prevents_silent_execution(self):
        path=self.manifest_path.parent/self.manifest['sources'][0]['physical_files'][0]['path']
        with path.open('ab') as f:f.write(b'bad')
        with self.assertRaisesRegex(ValueError,'DATA_FILE_HASH'):DataCatalog(self.manifest_path).resolve('dataset:records:v1').table()

    def test_index_range_is_complete_with_nulls_and_keeps_source_order(self):
        import pyarrow as pa
        task=copy.deepcopy(self.task);task['datasets'][0]['schema']['score']={'kind':'Nullable','item':{'kind':'Float64'}}
        task['datasets'][0]['indexes']=[{'id':'score-range','kind':'range','fields':['score'],'revision':task['datasets'][0]['revision'],'source':'full001-prepared-index'}]
        rows=[{'id':i,'score':v,'eligible':True} for i,v in enumerate([4.0,None,1.0,7.0,4.0])]
        task['datasets'][0]['stats']['row_count']=len(rows)
        _,_,path=prepare(task,{'dataset:records:v1':pa.Table.from_pylist(rows)},self.root/'indexed')
        source=DataCatalog(path).resolve('dataset:records:v1')
        self.assertEqual(source.indexed_rows(None),[0,1,2,3,4])
        self.assertEqual(source.indexed_rows({'op':'ge','left':{'field':'score'},'right':{'literal':4.0}}),[0,3,4])
        self.assertEqual(source.indexed_rows({'op':'eq','left':{'field':'eligible'},'right':{'literal':True}}),[0,1,2,3,4])
