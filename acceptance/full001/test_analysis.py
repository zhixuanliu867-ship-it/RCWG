"""Independent hand-computed acceptance cases for fixed-denominator statistics."""
from copy import deepcopy
from pathlib import Path
import itertools
import json
import unittest
from rcwg_full.analysis.metrics import capability,normalize,summarize,template_means,macro,tri_and,pair_e2,frontier
from rcwg_full.analysis.statistics import paired_inference,holm,hypothesis_registry
from rcwg_full.evidence import write
from support import EvidenceDirectory


def sample(families=('F1',),templates=1):
    expected=[];observed=[]
    for family in families:
        for template,base,condition,trial,repeat in itertools.product(range(templates),range(2),['C0','C1'],[17,29],range(2 if family in {'F5','F6'} else 3)):
            sid=f'{family}-{template}-{base}-{condition}-{trial}-{repeat}'
            row={'slot_id':sid,'slot_kind':'execution','ledger_role':'PRIMARY','family':family,
                'template_id':f'{family}-{template}','base_id':base,'condition':condition,'trial_label':trial,'execution_repeat':repeat,
                'generator':'G0','protocol':'P0','task_id':sid.rsplit('-',2)[0]}
            expected.append(row)
            observed.append({**row,'attempt_id':'a-'+sid,'status':'COMPLETED','semantic':True,'budget':True,
                             'evidence_valid':True,'timing_valid':True,'exec_elapsed_ns':50,'comparison_context_hash':'ctx',
                             'mode':'ENGINEERING_NATIVE'})
    return expected,observed


class GoldenAnalysis(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory(self.id())
    def tearDown(self):self.evidence.cleanup()
    def save(self,name,value):write(Path(self.evidence.name)/(name+'.json'),value)
    def reduce(self,expected,observed,**kwargs):
        normalized=normalize(expected,observed)
        result=summarize(normalized['rows'],evidence_integrity=normalized['evidence_integrity'],**kwargs)
        self.save('fixture',{'expected':expected,'observed':observed,'actual':result})
        return result
    def test_all_success(self):
        e,o=sample();r=self.reduce(e,o,families=('F1',));self.assertEqual(r['point'],1);self.assertEqual(r['denominator'],24)
    def test_all_failure(self):
        e,o=sample()
        for r in o:r['semantic']=False
        self.assertEqual(self.reduce(e,o,families=('F1',))['point'],0)
    def test_half_unknown_is_identification_not_confidence(self):
        e,o=sample()
        for r in o[:12]:r['status']='UNKNOWN'
        r=self.reduce(e,o,families=('F1',));self.assertEqual((r['point'],r['identification_lower'],r['identification_upper']),(None,.5,1))
    def test_missing_log_keeps_slot_and_blocks_point(self):
        e,o=sample();r=self.reduce(e,o[:-1],families=('F1',))
        self.assertEqual(r['denominator'],24);self.assertEqual(r['unknown'],1);self.assertEqual(r['evidence_integrity'],'FAIL')
        self.assertAlmostEqual(r['identification_lower'],23/24);self.assertIsNone(r['point'])
    def test_duplicate_attempt_is_not_an_extra_repeat(self):
        e,o=sample()
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ATTEMPT'):normalize(e,o+[o[0]])
    def test_repeat_counts_do_not_weight_families(self):
        e,o=sample(families=('F1','F5'))
        for r in o:
            if r['family']=='F1':r['semantic']=False
        r=self.reduce(e,o,families=('F1','F5'));self.assertEqual(r['point'],.5)
        self.assertNotEqual(r['point'],16/40)
    def test_unbalanced_template_counts_keep_equal_family_weight(self):
        e,o=sample(('F1',),templates=3);f,p=sample(('F2',),templates=1)
        for r in o:r['semantic']=False
        self.assertEqual(self.reduce(e+f,o+p,families=('F1','F2'))['point'],.5)
    def test_faster_than_reference_retains_rho_below_one(self):
        _,o=sample();r=capability(o[0],{'confirmed':True,'elapsed_ns':100,'context_hash':'ctx'})
        self.assertEqual(r['rho'],.5);self.assertTrue(r['efficient']);self.save('reference',r)
    def test_reference_missing_does_not_remove_success(self):
        _,o=sample();r=capability(o[0]);self.assertTrue(r['success']);self.assertIsNone(r['efficient'])
    def test_facility_retry_replaces_one_slot_only(self):
        e,o=sample();original=o[0];original['status']='INFRA_FAILURE';original['failure_class']='INFRASTRUCTURE'
        retry={**original,'status':'COMPLETED','failure_class':None,'attempt_id':'retry','parent_attempt_id':original['attempt_id'],
               'ledger_role':'INFRA_RETRY','reconciliation':{'worker_stopped':True,'request_uncertain':False}}
        n=normalize(e,[retry,*o]);self.assertEqual(len(n['rows']),24);self.assertTrue(n['rows'][0]['success']);self.assertEqual(n['rows'][0]['attempt_count'],2)
        self.save('retry',n)
    def test_retry_cannot_replace_model_failure(self):
        e,o=sample();o[0]['status']='MODEL_FAILURE'
        retry={**o[0],'attempt_id':'retry','parent_attempt_id':o[0]['attempt_id'],'ledger_role':'INFRA_RETRY',
               'reconciliation':{'worker_stopped':True,'request_uncertain':False}}
        with self.assertRaisesRegex(ValueError,'RETRY_NOT_EQUIVALENT'):normalize(e,o+[retry])
    def test_timing_confirmation_does_not_change_denominator(self):
        e,o=sample();n=normalize(e,o+[{**o[0],'attempt_id':'confirmation','ledger_role':'TIMING_CONFIRMATION','semantic':False}])
        self.assertEqual(len(n['rows']),24);self.assertEqual(n['excluded_timing_attempts'],['confirmation'])
        self.assertEqual(summarize(n['rows'],families=('F1',))['point'],1)
    def test_e2_wrong_pair_or_changed_frozen_plan_rejected(self):
        _,o=sample();a=[r for r in o if r['condition']=='C1'];b=deepcopy(a)
        for r in b:r.update(plan_hash='parent',c0_source_plan_hash='parent')
        self.assertEqual(len(pair_e2(a,b)),12)
        b[0]['plan_hash']='rewritten'
        with self.assertRaisesRegex(ValueError,'E2_FROZEN_BINDING'):pair_e2(a,b)
    def test_bootstrap_resamples_templates_with_replacement(self):
        left={('F1','a'):0.,('F1','b'):1.};right={k:0. for k in left}
        # Two draws with replacement have hand distribution 0,.5,.5,1.
        r=paired_inference(left,right,families=('F1',));self.assertEqual(r['effect'],.5)
        self.assertEqual(r['confidence_interval_95'],[0.,1.]);self.assertGreater(r['p_two_sided'],.45)
        again=paired_inference(left,right,families=('F1',));self.assertEqual(r,again);self.save('bootstrap',r)
    def test_paired_bootstrap_indices_shared_across_methods(self):
        left={(f,'a'):1. for f in ('F1','F2')};right={k:.25 for k in left}
        a=paired_inference(left,right,families=('F1','F2'));b=paired_inference(right,left,families=('F1','F2'))
        self.assertEqual(a['bootstrap_indices_sha256'],b['bootstrap_indices_sha256'])
        self.assertEqual(a['signs_sha256'],b['signs_sha256']);self.assertEqual(a['effect'],-b['effect'])
        self.assertEqual(a['p_two_sided'],b['p_two_sided']);self.save('paired',{'forward':a,'reverse':b})
    def test_holm_known_vector_and_eighteen_declared_tests(self):
        self.assertEqual(holm({'a':.01,'b':.04,'c':.03,'d':.2}),{'a':.04,'c':.09,'b':.09,'d':.2})
        r=hypothesis_registry();self.assertEqual(len(r['tests']),18);self.assertEqual(len({t['id'] for t in r['tests']}),18)
        self.save('registry',r)
    def test_confirmed_oom_is_failure_and_censored_time(self):
        _,o=sample();o[0].update(status='OOM',budget_failure_confirmed=True,timing_valid=False)
        r=capability(o[0]);self.assertFalse(r['success']);self.assertTrue(r['censored']);self.assertIsNone(r['rho']);self.assertIsNone(r['completed_time_ns'])
    def test_unconfirmed_infrastructure_never_becomes_plan_failure(self):
        _,o=sample();o[0].update(status='UNKNOWN',semantic=False,budget=False)
        self.assertIsNone(capability(o[0])['success']);self.assertFalse(tri_and(None,False));self.assertIsNone(tri_and(True,None))
        with self.assertRaises(ValueError):tri_and(1,True)
    def test_replay_cannot_enter_formal_table(self):
        e,o=sample()
        with self.assertRaisesRegex(ValueError,'MODE_CONTAMINATION'):normalize(e,o,mode='FORMAL')
    def test_frontier_uses_complete_resource_vectors(self):
        rows=[{'id':name,'success':True,'time':t,'ram':r,'measurement':{'time':'MEASURED','ram':'MEASURED'}}
              for name,t,r in [('a',1,3),('b',2,2),('c',3,3),('d',0,0)]]
        rows[-1]['measurement']['ram']='UNKNOWN'
        self.assertEqual([r['id'] for r in frontier(rows,['time','ram'])],['a','b'])
    def test_reference_context_mismatch_is_not_covered(self):
        _,o=sample();r=capability(o[0],{'confirmed':True,'elapsed_ns':100,'context_hash':'other'})
        self.assertFalse(r['reference_covered']);self.assertIsNone(r['rho']);self.assertTrue(r['success'])


if __name__=='__main__':unittest.main()
