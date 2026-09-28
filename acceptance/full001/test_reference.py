"""Public grammar, development fitting, and confirmation timing have separate evidence."""
from copy import deepcopy
from pathlib import Path
import unittest
from rcwg_full.data.templates import f1
from rcwg_full.reference.candidates import candidates,decision_identity,public_rule
from rcwg_full.reference.confirmation import confirm
from rcwg_full.reference.estimator import FEATURES,fit,predict,untrained
from rcwg_full.evidence import write
from support import EvidenceDirectory


class References(unittest.TestCase):
    def test_all_f1_grammars_have_eight_real_distinct_decisions(self):
        for number in range(1,13):
            definition=f1(f'F1-{number:02d}',0,'C0');r=candidates(definition['task'],definition['plan'])
            self.assertTrue(8<=len(r['candidates'])<=32)
            self.assertEqual(len(r['candidates']),len({c['candidate_id'] for c in r['candidates']}))
            self.assertEqual({c['decisions']['storage'] for c in r['candidates']},{'stream','memory','disk'})
    def test_renaming_nodes_does_not_make_a_candidate(self):
        d=f1('F1-01',0,'C0');plan=d['plan'];other=deepcopy(plan)
        names={n['id']:'renamed_'+n['id'] for n in other['nodes']}
        for node in other['nodes']:
            node['id']=names[node['id']]
            node['inputs']={k:v if v.startswith('$') else names[v.split('.')[0]]+'.'+v.split('.',1)[1] for k,v in node['inputs'].items()}
        a,b=other['result'].split('.',1);other['result']=names[a]+'.'+b
        self.assertEqual(decision_identity(plan),decision_identity(other))
    def test_rule_only_public_estimates_and_explicit_copy_requirement(self):
        f={'n':100,'k':20,'left_rows':100,'right_rows':10,'row_bytes':8,'ram_bytes':1024,'sorted_inputs':False,'independent_copy_required':False}
        r=public_rule(f);self.assertEqual(r['top_k'],'streaming_heap');self.assertEqual(r['build_side'],'right');self.assertEqual(r['broadcast'],'shared_ref')
        f['k']=70;f['independent_copy_required']=True;r=public_rule(f);self.assertEqual(r['top_k'],'full_sort');self.assertEqual(r['broadcast'],'copy_each')
        self.assertFalse(r['budget_verified'])
    def test_nnls_hand_linear_cost_and_nonnegative_coefficients(self):
        data=[]
        for n in [0,1,2,3,4,6,8,10]:
            features={k:0. for k in FEATURES};features.update(scan_bytes=n,constant=1.)
            data.append({'split':'development','mode':'ENGINEERING_GOLDEN','dispatch_id':'scan:sequential','measured':True,'features':features,'elapsed_ns':3*n+5})
        model=fit(data);features={k:0. for k in FEATURES};features.update(scan_bytes=7.,constant=1.)
        self.assertAlmostEqual(predict(model,features),26,places=6);self.assertTrue(all(v>=0 for v in model['scaled_coefficients']))
        self.assertFalse(model['formal_coefficients_available']);self.assertIsNone(untrained()['coefficients'])
        data[0]['split']='test'
        with self.assertRaisesRegex(ValueError,'TEST_DATA_LEAKAGE'):fit(data)
    def test_confirmation_screen_not_tref_and_three_to_seven_rule(self):
        tmp=EvidenceDirectory(self.id())
        try:
            d=f1('F1-01',0,'C0');definition=candidates(d['task'],d['plan']);ids=[c['candidate_id'] for c in definition['candidates'][:2]]
            context={k:'engineering' for k in ['task_id','condition','data_hash','budget_hash','hardware_hash','runtime_hash','executor_hash','cache_profile','measurement_profile']}
            calls=[]
            def execute(plan,request):
                calls.append(request)
                elapsed=1 if request['role']=='REFERENCE_SCREEN' else ([100,80,120,100,100,100,100] if request['candidate_id']==ids[0] else [50,51,50])[request['repeat']]
                return {**request,'status':'COMPLETED','semantic':True,'budget':True,'timing_valid':True,'exec_elapsed_ns':elapsed,'mode':'ENGINEERING_GOLDEN'}
            result=confirm(definition,context,execute,Path(tmp.name)/'confirmation',candidate_ids=ids)
            self.assertEqual(result['elapsed_ns'],50);self.assertEqual(sorted(c['confirmation_count'] for c in result['confirmed_candidates']),[3,7])
            self.assertEqual(len(calls),12);self.assertFalse(result['formal_ready'])
        finally:tmp.cleanup()
    def test_invalid_budget_has_no_reference_but_keeps_screen(self):
        tmp=EvidenceDirectory(self.id())
        try:
            d=f1('F1-01',0,'C0');definition=candidates(d['task'],d['plan']);context={k:'engineering' for k in ['task_id','condition','data_hash','budget_hash','hardware_hash','runtime_hash','executor_hash','cache_profile','measurement_profile']}
            def execute(plan,request):return {**request,'status':'COMPLETED','semantic':True,'budget':None,'timing_valid':True,'exec_elapsed_ns':10}
            r=confirm(definition,context,execute,Path(tmp.name)/'confirmation',candidate_ids=[definition['candidates'][0]['candidate_id']])
            self.assertFalse(r['confirmed']);self.assertIsNone(r['elapsed_ns'])
        finally:tmp.cleanup()
