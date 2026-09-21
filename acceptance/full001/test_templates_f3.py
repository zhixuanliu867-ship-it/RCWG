from copy import deepcopy
import unittest
import test_templates_f1 as fixture
from rcwg_full.data.graph_templates import f3
from rcwg_full.evidence import digest


class F3Templates(unittest.TestCase):
    setUpClass=classmethod(fixture.F1Templates.setUpClass.__func__)
    run_case=fixture.F1Templates.run_case


for number in range(1,13):
    for base in range(5):
        for condition in ['C0','C1','C2','C3']:
            setattr(F3Templates,f'test_F3_{number:02d}_b{base}_{condition}',fixture.case(f'F3-{number:02d}',base,condition))


class F3ConditionDefinitions(unittest.TestCase):
    def test_five_distinct_seeds_and_graphs(self):
        for number in range(1,13):
            cases=[f3(f'F3-{number:02d}',base,'C0') for base in range(5)]
            self.assertEqual(len({r['seed'] for r in cases}),5);self.assertEqual(len({digest(r['rows']) for r in cases}),5)
    def test_ram_only_c2_logical_c3_and_scaled_node_count(self):
        for number in range(1,13):
            for base in range(5):
                c0=f3(f'F3-{number:02d}',base,'C0');c1=f3(f'F3-{number:02d}',base,'C1');c2=f3(f'F3-{number:02d}',base,'C2');c3=f3(f'F3-{number:02d}',base,'C3')
                self.assertEqual(c0['rows'],c2['rows']);self.assertEqual(c0['rows'],c3['rows'])
                self.assertEqual((len(c0['rows']['graph']['nodes']),len(c1['rows']['graph']['nodes'])),(23,67))
                a,b=deepcopy(c0['task']),deepcopy(c2['task']);a.pop('task_id');b.pop('task_id')
                self.assertNotEqual(a['resources']['worker_memory_limit_bytes'],b['resources']['worker_memory_limit_bytes'])
                b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes'];self.assertEqual(a,b)
