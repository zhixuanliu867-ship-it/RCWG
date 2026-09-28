from copy import deepcopy
import unittest
import test_templates_f1 as fixture
from rcwg_full.data.stream_templates import f4
from rcwg_full.evidence import digest


class F4Templates(unittest.TestCase):
    setUpClass=classmethod(fixture.F1Templates.setUpClass.__func__)
    run_case=fixture.F1Templates.run_case


for number in range(1,13):
    for base in range(5):
        for condition in ['C0','C1','C2','C3']:
            setattr(F4Templates,f'test_F4_{number:02d}_b{base}_{condition}',fixture.case(f'F4-{number:02d}',base,condition))


class F4ConditionDefinitions(unittest.TestCase):
    def test_five_distinct_data_seeds(self):
        for number in range(1,13):
            cases=[f4(f'F4-{number:02d}',base,'C0') for base in range(5)]
            self.assertEqual(len({r['seed'] for r in cases}),5);self.assertEqual(len({digest(r['rows']) for r in cases}),5)
    def test_object_rows_c1_and_identical_c2_c3(self):
        for number in range(1,13):
            for base in range(5):
                cases={c:f4(f'F4-{number:02d}',base,c) for c in ['C0','C1','C2','C3']}
                for c in ['C2','C3']:self.assertEqual(cases['C0']['rows'],cases[c]['rows'])
                small,large=cases['C0']['rows']['records'],cases['C1']['rows']['records']
                self.assertGreater(len(large),len(small));self.assertEqual(small,large[:len(small)])
                a,b=deepcopy(cases['C0']['task']),deepcopy(cases['C2']['task']);a.pop('task_id');b.pop('task_id')
                self.assertNotEqual(a['resources']['worker_memory_limit_bytes'],b['resources']['worker_memory_limit_bytes'])
                b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes'];self.assertEqual(a,b)
