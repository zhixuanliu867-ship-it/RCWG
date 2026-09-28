from copy import deepcopy
import unittest
import test_templates_f1 as fixture
from rcwg_full.data.relational_f2 import f2
from rcwg_full.evidence import digest


class F2Templates(unittest.TestCase):
    setUpClass=classmethod(fixture.F1Templates.setUpClass.__func__)
    run_case=fixture.F1Templates.run_case


for number in range(1,13):
    for base in range(5):
        for condition in ['C0','C1','C2','C3']:
            setattr(F2Templates,f'test_F2_{number:02d}_b{base}_{condition}',fixture.case(f'F2-{number:02d}',base,condition))


class F2ConditionDefinitions(unittest.TestCase):
    def test_five_distinct_seeds_and_data(self):
        for number in range(1,13):
            cases=[f2(f'F2-{number:02d}',base,'C0') for base in range(5)]
            self.assertEqual(len({r['seed'] for r in cases}),5);self.assertEqual(len({digest(r['rows']) for r in cases}),5)
    def test_c2_c3_logical_invariance_and_c1_single_axis(self):
        for number in range(1,13):
            for base in range(5):
                c0=f2(f'F2-{number:02d}',base,'C0');c1=f2(f'F2-{number:02d}',base,'C1');c2=f2(f'F2-{number:02d}',base,'C2');c3=f2(f'F2-{number:02d}',base,'C3')
                self.assertEqual(c0['rows'],c2['rows']);self.assertEqual(c0['rows'],c3['rows'])
                a,b=deepcopy(c0['task']),deepcopy(c2['task']);a.pop('task_id');b.pop('task_id')
                self.assertNotEqual(a['resources']['worker_memory_limit_bytes'],b['resources']['worker_memory_limit_bytes'])
                b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes'];self.assertEqual(a,b)
                if number in {2,10}:
                    changed='join_key' if number==2 else 'eligible'
                    for name in c0['rows']:
                        self.assertEqual([{k:v for k,v in r.items() if k!=changed} for r in c0['rows'][name]],
                                         [{k:v for k,v in r.items() if k!=changed} for r in c1['rows'][name]])
                    self.assertNotEqual(c0['rows'],c1['rows'])
                else:
                    self.assertEqual((len(c0['rows']['left']),len(c1['rows']['left'])),(37,113))
                    for name in c0['rows']:
                        if name!='left':self.assertEqual(c0['rows'][name],c1['rows'][name])
