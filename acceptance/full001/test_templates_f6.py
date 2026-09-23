from copy import deepcopy
from pathlib import Path
import unittest
import test_templates_f5 as fixture
from rcwg_full.data.templates import build
from rcwg_full.data.mixed_templates import f6
from rcwg_full.verification.mixed_oracle import f6_expected,verify_mixed_result
from rcwg_full.evidence import digest
from rcwg_full.compiler import FullCompiler
from support import EvidenceDirectory


class F6Templates(unittest.TestCase):
    setUpClass=classmethod(fixture.F5Templates.setUpClass.__func__)
    execute_plan=fixture.F5Templates.execute_plan
    run_case=fixture.F5Templates.run_case


for number in range(1,13):
    for base in range(5):
        for condition in ['C0','C1','C2','C3']:
            setattr(F6Templates,f'test_F6_{number:02d}_b{base}_{condition}',fixture.case(f'F6-{number:02d}',base,condition))


class F6Definitions(unittest.TestCase):
    def test_distinct_seeds_and_c1_candidate_count(self):
        for number in range(1,13):
            cases=[f6(f'F6-{number:02d}',b,'C0') for b in range(5)]
            self.assertEqual(len({r['seed'] for r in cases}),5);self.assertEqual(len({digest(r['rows']) for r in cases}),5)
            for base,small in enumerate(cases):
                large=f6(f'F6-{number:02d}',base,'C1')
                self.assertEqual(len(small['rows']['documents']),9);self.assertEqual(len(large['rows']['documents']),15)
                self.assertEqual(small['rows']['documents'],large['rows']['documents'][:9])
                self.assertEqual(small['rows']['graph']['edges'],large['rows']['graph']['edges'][:len(small['rows']['graph']['edges'])])
    def test_c2_only_ram_c3_same_canonical_evidence(self):
        for number in range(1,13):
            for base in range(5):
                cases={c:f6(f'F6-{number:02d}',base,c) for c in ['C0','C2','C3']}
                for c in ['C2','C3']:self.assertEqual(cases['C0']['rows'],cases[c]['rows'])
                a,b=deepcopy(cases['C0']['task']),deepcopy(cases['C2']['task']);a.pop('task_id');b.pop('task_id')
                self.assertNotEqual(a['resources']['worker_memory_limit_bytes'],b['resources']['worker_memory_limit_bytes'])
                b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes'];self.assertEqual(a,b)
    def test_graph_mapping_document_revision_cannot_be_swapped(self):
        evidence=EvidenceDirectory(self.id());root=Path(evidence.name)
        try:
            built=build('F6-12',1,'C0',root/'data');plan=deepcopy(built['plan'])
            self.assertEqual(FullCompiler().compile(built['task'],plan)['status'],'IR_VALIDATED')
            plan['external_inputs']['documents']='dataset:stale_documents'
            self.assertEqual(FullCompiler().compile(built['task'],plan)['status'],'PLAN_INVALID')
        finally:evidence.cleanup()


def mutator(number):
    def test(self):
        built=f6(f'F6-{number:02d}',2,'C0');expected=f6_expected(built['expected_args'])
        if number==4:
            from rcwg_full.verification.compare import shortest_distances
            from rcwg_full.evidence import canonical
            import math
            obligation=expected['paths'];g=obligation['graph'];distances=shortest_distances(g,[0],'weight');paths=[]
            for target in obligation['targets']:
                distance=distances[canonical(target)];reachable=math.isfinite(distance);nodes=[];edges=[]
                if reachable:
                    current=target;nodes=[current]
                    while current!=0:
                        edge=next(e for e in g['edges'] if e['dst']==current and distances[canonical(e['src'])]+e['weight']==distances[canonical(current)])
                        edges.insert(0,edge['edge_id']);current=edge['src'];nodes.insert(0,current)
                paths.append({'target':target,'reachable':reachable,'distance':distance if reachable else None,'nodes':nodes,'edges':edges})
            actual={'paths':paths,'facts':deepcopy(expected['result'])};docs=built['rows']['documents']
            self.assertEqual(verify_mixed_result(actual,expected,docs)['status'],'PASS')
            wrong=deepcopy(actual);wrong['paths'].pop();self.assertEqual(verify_mixed_result(wrong,expected,docs)['status'],'FAIL')
            wrong=deepcopy(actual);wrong['facts'].pop();self.assertEqual(verify_mixed_result(wrong,expected,docs)['status'],'FAIL')
            wrong=deepcopy(actual);next(p for p in wrong['paths'] if p['edges'])['edges'][0]=999999
            self.assertEqual(verify_mixed_result(wrong,expected,docs)['status'],'FAIL');return
        actual=deepcopy(expected['result']);docs=built['rows']['documents']
        self.assertEqual(verify_mixed_result(actual,expected,docs)['status'],'PASS')
        self.assertEqual(verify_mixed_result(actual,expected,docs,events=[])['status'],'FAIL')
        if type(actual) is dict:actual['dose_branch']=[]
        elif actual:actual.pop()
        else:actual.append({'paper_id':'injected'})
        self.assertEqual(verify_mixed_result(actual,expected,docs)['status'],'FAIL')
    return test


for number in range(1,13):setattr(F6Definitions,f'test_independent_F6_{number:02d}_coverage',mutator(number))
