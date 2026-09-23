"""F4 builder contracts on named fixtures; no formal-scale host allocation."""
import json
from pathlib import Path
import unittest
from rcwg_full.evidence import read,digest
from rcwg_full.data.formal_stream import definition,build_fixture,build_formal,build_request
from rcwg_full.data.conditions import check_group
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.verification.stream_oracle import f4_expected
from rcwg_full.verification.compare import check_output
from support import EvidenceDirectory


class FormalStreamBuilders(unittest.TestCase):
    def setUp(self):self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_twelve_builders_four_conditions_and_independent_values(self):
        for number in range(1,13):
            siblings={}
            for condition in ['C0','C1','C2','C3']:
                with self.subTest(template=number,condition=condition):
                    directory=self.root/f'{number}-{condition}';siblings[condition]=directory
                    result=build_fixture(f'F4-{number:02d}',1,condition,directory)
                    self.assertEqual(result['proof']['status'],'IR_VALIDATED',result['proof'])
                    catalog=DataCatalog(result['manifest_path']).bind(result['task'])
                    values={ident.removeprefix('dataset:'):source.table().to_pylist() for ident,source in catalog.sources.items()}
                    expected=f4_expected(number,values,1)
                    if number==12:
                        n=len(values['records']);iterations=min(16,(n+15)//16)
                        expected={'remaining':n-16*iterations,'iterations':iterations,'active':True}
                    actual=json.loads(read(result['private_verifier']))
                    self.assertEqual(check_output(actual['expected'],expected,{'comparison':actual['comparison']})['status'],'PASS')
                    self.assertTrue(all(v>=result['build']['data_parameters']['object_target_bytes'] for v in result['build']['actual_source_arrow_payload_bytes'].values()))
                    self.assertLessEqual(max(s['builder_observations']['peak_batch_rows'] for s in result['manifest']['sources']),31)
                    self.assertFalse(result['build']['native_execution_performed']);self.assertFalse(result['build']['formal_frozen'])
            self.assertEqual(check_group(siblings)['status'],'PASS',number)
    def test_formal_metadata_fixed_capacity_and_no_dynamic_row_expansion(self):
        large=definition('F4-11',0,'C1')
        self.assertEqual(large['data_parameters']['object_target_bytes'],4*1024**3)
        self.assertEqual(len(large['sources']),2)
        for number in [8,10]:
            d=definition(f'F4-{number:02d}',0,'C1')
            self.assertFalse(any(n['operator'] in {'map','collect'} for n in d['plan']['nodes']))
        output=self.root/'forbidden';seen=[]
        with self.assertRaisesRegex(PermissionError,'HOST_ADMISSION_REQUIRED'):build_formal('F4-11',0,'C1',output,host_admit=lambda r:seen.append(r))
        self.assertEqual(seen,[build_request('F4-11',0,'C1')]);self.assertFalse(output.exists())
        self.assertNotEqual(large['seed'],definition('F4-11',0,'C1',fixture=True)['seed'])
    def test_initial_false_loop_remains_zero_iterations(self):
        result=build_fixture('F4-12',0,'C1',self.root/'initial-false')
        expected=json.loads(read(result['private_verifier']))['expected']
        self.assertEqual(expected,{'active':False,'iterations':0,'remaining':result['build']['data_parameters']['rows']})
