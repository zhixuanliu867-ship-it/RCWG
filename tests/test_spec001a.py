"""Offline conformance tests for SPEC001A calculation/profile implementation."""
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from rcwg_spec.common import ContractError,load,digest,write_new,number
from rcwg_spec.task_input import validate_task,assemble_public
from rcwg_spec.metrology import measurement,validate_measurement,score_repeat,score_manifest,tri_and
from rcwg_spec.lifetimes import live_buffers,byte_totals,evidence_coverage
from rcwg_spec.cgroup_probe import read_snapshot,cpu_delta
ROOT=Path(__file__).resolve().parents[1]

def fixture():
    e={'record_id':'r1','model_id':'m','protocol':'P0','case_id':'c1','family':'F1','template_id':'t1','base_id':'b1','condition_id':'C0','generation_id':'g1','repeat_id':'0','budget':{'wall_s':5.0,'memory_peak_bytes':1000}}
    o={'record_id':'r1','status':'COMPLETED','semantic_pass':True,'metrics':{'wall_s':measurement(1.0,'s','worker_exec'),'memory_peak_bytes':measurement(500,'byte','worker_cgroup')},'evidence_id':'synthetic','reason':None}
    ref={'case_id':'c1','budget_hash':digest(e['budget']),'time_s':1.0,'confirmation_id':'synthetic-confirmation','frozen':True}
    return e,o,ref

class TestStrictPrimitives(unittest.TestCase):
    def test_bool_not_number(self):
        with self.assertRaises(ContractError):number(True,'x')
    def test_nan_infinity_rejected(self):
        for x in (float('nan'),float('inf'),-1):
            with self.subTest(x=x),self.assertRaises(ContractError):number(x,'x')
    def test_json_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ContractError):load(p)
    def test_json_nan_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.json';p.write_text('{"a":NaN}')
            with self.assertRaises(ContractError):load(p)
    def test_canonical_key_order(self):self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
    def test_write_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'e.json';write_new(p,{'x':1})
            with self.assertRaises(FileExistsError):write_new(p,{'x':2})
    def test_three_valued_logic(self):
        self.assertFalse(tri_and([False,None]));self.assertIsNone(tri_and([True,None]));self.assertTrue(tri_and([True,True]))

class TestTaskProfile(unittest.TestCase):
    def setUp(self):self.task=load(ROOT/'specs/reference_v1_0/examples/task_input.json')
    def test_existing_example_accepted(self):self.assertEqual(validate_task(self.task)['status'],'TASKINPUT_PROFILE_PASS')
    def test_public_assembly_is_copy(self):
        packed=assemble_public(self.task);packed['task']['instruction']='changed'
        self.assertNotEqual(self.task['instruction'],'changed')
    def test_top_level_gold_rejected(self):
        self.task['gold']='PRIVATE_CANARY'
        with self.assertRaises(ContractError):assemble_public(self.task)
    def test_nested_gold_rejected(self):
        self.task['datasets'][0]['stats']['gold']='PRIVATE_CANARY'
        with self.assertRaises(ContractError):assemble_public(self.task)
    def test_unknown_resource_field_rejected(self):
        self.task['resources']['api_key']='NOT_A_KEY'
        with self.assertRaises(ContractError):assemble_public(self.task)
    def test_bool_resource_rejected(self):
        self.task['resources']['cpu_slots']=True
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_cpu_above_reference_limit(self):
        self.task['resources']['cpu_slots']=9
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_duplicate_dataset_rejected(self):
        self.task['datasets'].append(copy.deepcopy(self.task['datasets'][0]))
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_unknown_modality_fails_explicitly(self):
        self.task['datasets'][0]['schema']['foo']='Graph'
        with self.assertRaisesRegex(ContractError,'UNSUPPORTED_TYPE_PROFILE'):validate_task(self.task)
    def test_estimate_requires_source(self):
        del self.task['datasets'][0]['stats']['estimate_source']
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_zero_k_is_outside_current_profile(self):
        self.task['output_contract']['k']=0
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_empty_result_is_allowed_by_source_example(self):
        self.task['datasets'][0]['stats']['row_count']=0
        self.assertEqual(validate_task(self.task)['status'],'TASKINPUT_PROFILE_PASS')
    def test_negative_memory_rejected(self):
        self.task['resources']['worker_memory_limit_bytes']=-1
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_tie_breaker_must_be_output(self):
        self.task['output_contract']['tie_breaker']='missing'
        with self.assertRaises(ContractError):validate_task(self.task)
    def test_canary_private_bundle_never_read(self):
        private={'public':self.task,'gold':'PRIVATE_CANARY'}
        result=assemble_public(private['public'])
        self.assertNotIn('PRIVATE_CANARY',json.dumps(result))

class TestResourceScoring(unittest.TestCase):
    def test_success_and_exact_boundary(self):
        e,o,r=fixture();o['metrics']['wall_s']['value']=1.2
        s=score_repeat(e,o,r);self.assertTrue(s['V']);self.assertTrue(s['efficient_success'])
    def test_just_above_near_threshold(self):
        e,o,r=fixture();o['metrics']['wall_s']['value']=1.2000001
        self.assertFalse(score_repeat(e,o,r)['efficient_success'])
    def test_faster_than_reference_ratio_not_clipped(self):
        e,o,r=fixture();o['metrics']['wall_s']['value']=.4
        self.assertEqual(score_repeat(e,o,r)['time_ratio'],.4)
    def test_memory_budget_fail(self):
        e,o,r=fixture();o['metrics']['memory_peak_bytes']['value']=1001
        self.assertFalse(score_repeat(e,o,r)['V'])
    def test_semantic_failure_stays_in_denominator(self):
        e,o,r=fixture();o['semantic_pass']=False
        self.assertFalse(score_repeat(e,o,r)['V'])
    def test_missing_ram_is_unknown_not_zero(self):
        e,o,r=fixture();del o['metrics']['memory_peak_bytes']
        s=score_repeat(e,o,r);self.assertIsNone(s['V']);self.assertEqual(s['missing_budget_metrics'],['memory_peak_bytes'])
    def test_nan_metric_rejected(self):
        e,o,r=fixture();o['metrics']['wall_s']['value']=float('nan')
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_wrong_unit_rejected(self):
        e,o,r=fixture();o['metrics']['wall_s']['unit']='ms'
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_remote_memory_not_worker_memory(self):
        e,o,r=fixture();o['metrics']['memory_peak_bytes']['scope']='remote_gpu'
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_unavailable_must_have_null_and_reason(self):
        for value,reason in ((0,'NOT_OBSERVABLE'),(None,None)):
            m=measurement(value,'s','worker_exec','UNAVAILABLE',reason)
            with self.subTest(value=value),self.assertRaises(ContractError):validate_measurement('wall_s',m)
    def test_timeout_censored_failure(self):
        e,o,r=fixture();o.update(status='TIMEOUT',semantic_pass=False,reason='limit')
        o['metrics']['wall_s']=measurement(5,'s','worker_exec','CENSORED','TIMEOUT_LOWER_BOUND')
        s=score_repeat(e,o,r);self.assertFalse(s['V']);self.assertIsNone(s['time_ratio'])
    def test_oom_with_capped_peak_still_fails(self):
        e,o,r=fixture();o.update(status='OOM',semantic_pass=False,reason='oom kill')
        s=score_repeat(e,o,r);self.assertFalse(s['B']);self.assertFalse(s['V'])
    def test_invalid_plan_missing_measurements_is_zero(self):
        e,o,r=fixture();o.update(status='INVALID_PLAN',semantic_pass=False,metrics={},reason='schema')
        self.assertFalse(score_repeat(e,o,r)['V'])
    def test_infra_failure_is_unresolved_even_if_slow(self):
        e,o,r=fixture();o.update(status='INFRA_FAILURE',semantic_pass=None,reason='verified outage');o['metrics']['wall_s']['value']=100
        self.assertIsNone(score_repeat(e,o,r)['V']);self.assertIsNone(score_repeat(e,o,r)['efficient_success'])
    def test_missing_record_not_discarded(self):
        e,o,r=fixture();report=score_manifest([e],[],[r]);score=report['panels'][0]['success_at_budget']
        self.assertEqual((score['lower'],score['upper']),(0,1));self.assertIsNone(score['point'])
    def test_reference_absent_changes_coverage_only(self):
        e,o,r=fixture();s=score_repeat(e,o,None)
        self.assertTrue(s['V']);self.assertFalse(s['reference_covered']);self.assertIsNone(s['efficient_success'])
    def test_reference_budget_scope_checked(self):
        e,o,r=fixture();r['budget_hash']='different'
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_reference_must_be_confirmed_frozen(self):
        e,o,r=fixture();r['frozen']=False
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_failure_cannot_claim_success(self):
        e,o,r=fixture();o.update(status='OOM',reason='oom')
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_monetary_budget_not_primary(self):
        e,o,r=fixture();e['budget']['usd']=100
        with self.assertRaises(ContractError):score_repeat(e,o,r)
    def test_duplicate_record_rejected(self):
        e,o,r=fixture()
        with self.assertRaises(ContractError):score_manifest([e],[o,o],[r])
    def test_unplanned_record_rejected(self):
        e,o,r=fixture();o['record_id']='notplanned'
        with self.assertRaises(ContractError):score_manifest([e],[o],[r])
    def test_repeat_count_does_not_change_family_weight(self):
        manifest=[];obs=[]
        for i in range(5):
            e,o,r=fixture();ident=f'r{i}';e.update(record_id=ident,repeat_id=str(i),case_id='a' if i<3 else 'b',family='F1' if i<3 else 'F5');o['record_id']=ident
            if i>=3:o['semantic_pass']=False
            manifest.append(e);obs.append(o)
        score=score_manifest(manifest,obs,[])['panels'][0]['success_at_budget']['point']
        self.assertEqual(score,.5)
    def test_models_remain_separate(self):
        e,o,r=fixture();e2=copy.deepcopy(e);o2=copy.deepcopy(o);e2.update(model_id='n',record_id='r2');o2.update(record_id='r2',semantic_pass=False)
        panels=score_manifest([e,e2],[o,o2],[r])['panels'];self.assertEqual(len(panels),2)
        self.assertEqual([p['success_at_budget']['point'] for p in panels],[1,0])
    def test_unequal_case_sets_are_reported(self):
        e,o,r=fixture();e2=copy.deepcopy(e);o2=copy.deepcopy(o);e2.update(model_id='n',record_id='r2',case_id='other');o2['record_id']='r2'
        self.assertFalse(score_manifest([e,e2],[o,o2],[])['panel_case_sets_equal'])
    def test_duplicate_hierarchy_coordinates_rejected(self):
        e,o,r=fixture();e2=copy.deepcopy(e);e2['record_id']='r2'
        with self.assertRaises(ContractError):score_manifest([e,e2],[o],[r])
    def test_seeded_budget_monotonicity(self):
        rng=random.Random(17)
        for _ in range(50):
            e,o,r=fixture();o['metrics']['memory_peak_bytes']['value']=rng.randrange(0,2000)
            low=score_repeat(e,o)['V'];e['budget']['memory_peak_bytes']=2000
            high=score_repeat(e,o)['V'];self.assertFalse(low and not high)

class TestBufferAndEvidenceAccounting(unittest.TestCase):
    def test_overlapping_buffers_have_joint_peak(self):
        b=[{'buffer_id':'a','bytes':100,'created_ns':0,'released_ns':3_000_000_000},{'buffer_id':'b','bytes':200,'created_ns':1_000_000_000,'released_ns':2_000_000_000}]
        r=live_buffers(b,3_000_000_000);self.assertEqual(r['peak_live_bytes'],300);self.assertEqual(r['live_byte_seconds'],500)
    def test_sequential_peaks_not_summed(self):
        b=[{'buffer_id':'a','bytes':100,'created_ns':0,'released_ns':1},{'buffer_id':'b','bytes':200,'created_ns':1,'released_ns':2}]
        self.assertEqual(live_buffers(b,2)['peak_live_bytes'],200)
    def test_alias_id_does_not_allocate_twice(self):
        b={'buffer_id':'a','bytes':100,'created_ns':0,'released_ns':1}
        with self.assertRaises(ContractError):live_buffers([b,b],1)
    def test_unreleased_buffers_are_reported(self):
        b={'buffer_id':'a','bytes':100,'created_ns':0,'released_ns':None}
        self.assertEqual(live_buffers([b],1)['unreleased_bytes_at_end'],100)
    def test_zero_duration_has_no_live_peak(self):
        self.assertEqual(live_buffers([{'buffer_id':'a','bytes':100,'created_ns':1,'released_ns':1}],2)['peak_live_bytes'],0)
    def test_invalid_temporal_order(self):
        with self.assertRaises(ContractError):live_buffers([{'buffer_id':'a','bytes':100,'created_ns':2,'released_ns':1}],2)
    def test_byte_dimensions_are_separate(self):
        e={'event_id':'a','payload_bytes':64,'read_bytes':1024,'copy_bytes':0,'wire_bytes':None}
        r=byte_totals([e]);self.assertEqual(r['metrics']['read_bytes']['value'],1024);self.assertIsNone(r['metrics']['wire_bytes']['value'])
    def test_duplicate_transfer_rejected(self):
        e={'event_id':'a','payload_bytes':64,'read_bytes':1024,'copy_bytes':0,'wire_bytes':0}
        with self.assertRaises(ContractError):byte_totals([e,e])
    def test_qualifier_is_part_of_witness(self):
        o={'fact1':[['entity','negation','date']]}
        self.assertEqual(evidence_coverage(o,['entity','date'])['recall'],0)
    def test_alternative_evidence_is_accepted(self):
        o={'fact1':[['a','b'],['c']]}
        self.assertEqual(evidence_coverage(o,['c'])['recall'],1)
    def test_reacquisition_can_restore_coverage(self):
        o={'fact1':[['a','b']]}
        self.assertLess(evidence_coverage(o,['a'])['recall'],evidence_coverage(o,['a','b'])['recall'])
    def test_empty_obligations_are_not_perfect_recall(self):self.assertIsNone(evidence_coverage({},[])['recall'])
    def test_empty_witness_rejected(self):
        with self.assertRaises(ContractError):evidence_coverage({'fact1':[[]]},[])
    def test_duplicate_units_not_double_counted(self):self.assertEqual(evidence_coverage({'f':[['a']]},['a','a'])['recall'],1)
    def test_seeded_sweep_against_discrete_reference(self):
        rng=random.Random(29)
        for _ in range(50):
            b=[]
            for i in range(5):
                a=rng.randrange(0,10);end=rng.randrange(a,11)
                b.append({'buffer_id':str(i),'bytes':rng.randrange(100),'created_ns':a,'released_ns':end})
            expected=max(sum(x['bytes'] for x in b if x['created_ns']<=t<x['released_ns']) for t in range(11))
            self.assertEqual(live_buffers(b,10)['peak_live_bytes'],expected)

class TestReadOnlyCgroup(unittest.TestCase):
    def test_fixture_snapshot_never_claims_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'memory.peak').write_text('1000\n');(p/'cgroup.procs').write_text('111\n222\n')
            r=read_snapshot(p);self.assertFalse(r['formal_ready']);self.assertEqual(r['fields']['memory.peak']['text'],'1000');self.assertEqual(r['fields']['cgroup.procs']['text'],'process_count=2')
    def test_unavailable_fields_are_null(self):
        with tempfile.TemporaryDirectory() as d:self.assertIsNone(read_snapshot(d)['fields']['memory.peak']['text'])
    def test_cpu_delta_uses_microseconds(self):self.assertEqual(cpu_delta('usage_usec 1000','usage_usec 2001000'),2)
    def test_counter_reset_is_an_error(self):
        with self.assertRaises(ContractError):cpu_delta('usage_usec 1000','usage_usec 5')
    def test_missing_cpu_stat_is_error(self):
        with self.assertRaises(ContractError):cpu_delta('user_usec 1000','user_usec 2000')
    def test_symlink_cgroup_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'other').write_text('hidden');(p/'cpu.stat').symlink_to(p/'other')
            self.assertEqual(read_snapshot(p)['fields']['cpu.stat']['status'],'UNAVAILABLE')



class TestReducerInputBoundaries(unittest.TestCase):
    def test_available_units_cannot_be_bare_string(self):
        with self.assertRaises(ContractError): evidence_coverage({'q':[['a']]}, 'a')
    def test_available_units_cannot_contain_objects(self):
        with self.assertRaises(ContractError): evidence_coverage({'q':[['a']]}, [{}])
    def test_buffers_require_array(self):
        with self.assertRaises(ContractError): live_buffers(None, 1)
    def test_byte_events_require_array(self):
        with self.assertRaises(ContractError): byte_totals(None)

if __name__=='__main__':unittest.main()
