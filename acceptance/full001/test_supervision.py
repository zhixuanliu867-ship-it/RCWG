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
