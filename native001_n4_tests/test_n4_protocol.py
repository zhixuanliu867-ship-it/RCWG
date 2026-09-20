"""Receipt, finite denominator, statistics and crash preservation regressions."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import copy,json,os,subprocess,tempfile,time,unittest
from unittest.mock import patch
from rcwg_native.evidence import canonical,sha,write,read
from rcwg_native_n4.plan import slots
from rcwg_native_n4.evidence import Journal,inspect_journal,reconcile
from rcwg_native_n4.approval import validate,claim
from rcwg_native_n4.runtime import one
from rcwg_native_n4.runner import watchdog
from rcwg_native_n4.statistics import overhead,classify_oom,sample_gaps
from rcwg_native_n4.assess import assess

BUILD=None
class PlanTests(unittest.TestCase):
    def test_exact_resource_cartesian_and_adjacent_pairs(self):
        rows=[s for s in slots() if s['category']=='resource'];self.assertEqual(len(rows),648)
        from itertools import product
        expected=set(product([17,29,101],[1024,16384,65536],[8,128],[67108864,134217728],['full_sort','streaming_heap','scalar','vectorized','column_view','copy'],range(3)))
        observed={(s['seed'],s['rows'],s['k'],s['memory_max'],s['algorithm'],s['repeat']) for s in rows};self.assertEqual(observed,expected)
        for a,b in zip(rows[::2],rows[1::2]):self.assertEqual(a['pair_id'],b['pair_id']);self.assertNotEqual(a['algorithm'],b['algorithm'])
    def test_reviewer_expansion_same_order_and_conditions(self):
        import importlib.util
        p=Path(__file__).resolve().parents[1]/'specs/native001n4/review_expand_resource_slots.py';spec=importlib.util.spec_from_file_location('review_expansion',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        actual=[s for s in slots() if s['category']=='resource'];review=m.expand()['slots']
        self.assertEqual([(s['seed'],s['rows'],s['k'],s['memory_max'],s['algorithm'],s['repeat']) for s in actual],[(s['seed'],s['rows'],s['k'],s['memory_bytes'],s['implementation'],s['repeat']) for s in review])
    def test_all_slots_unique_finite_and_unapproved(self):
        s=slots();self.assertEqual(len({r['run_id'] for r in s}),len(s));self.assertEqual(len(s),888)
        self.assertEqual(sum(r['category']=='warmup' for r in s),10)
        self.assertTrue(all(r['status']=='NOT_RUN' and not r['formal_ready'] and r['timeout_s']<=20 and r['children_max']<=2 for r in s))
    def test_sampler_pair_changes_only_switch_and_identity(self):
        groups={}
        for s in slots():
            if s['run_id'].startswith('n4-overhead'):groups.setdefault(s['pair_id'],[]).append(s)
        self.assertEqual(len(groups),100)
        for a,b in groups.values():
            for key in a:
                if key not in ['run_id','sampler','sequence']:self.assertEqual(a[key],b[key])
    def test_no_workload_without_receipt(self):
        with self.assertRaisesRegex(RuntimeError,'EXPLICIT_OWNER_RECEIPT_REQUIRED'):one({}, {}, '/unused')
    def test_unstarted_matrix_retains_all(self):
        manifest={'slots':slots(),'tolerances':{'cpu_relative_error':0.2}}
        with tempfile.TemporaryDirectory() as t:r=reconcile(manifest,t)
        a=assess(manifest,r);self.assertEqual(a['expected'],888);self.assertTrue(all(v['status']=='NOT_RUN' for v in a['cases'].values()))

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
        self.now=datetime(2026,9,20,15,tzinfo=timezone.utc);self.identity={'simulated':True};manifest={'slots':slots()}
        write(self.d/'manifest.json',manifest)
        self.plan={'approved':False,'revision':'N4_OWNER_CHANGE_PLAN_V1','receipt_required':{'bindings_sha256':'a'*64},'host':self.identity,'max_service_starts':1,'automatic_retries':0,'manifest_path':str(self.d/'manifest.json'),'workload_total':len(manifest['slots']),'per_run_wall_s_max':20}
        write(self.d/'plan.json',self.plan)
        self.receipt={'approved':True,'owner_confirmation':'Explicit owner approval of exact SHA','plan_sha256':sha((self.d/'plan.json').read_bytes()),'bindings_sha256':'a'*64,'max_uses':1,'valid_from_utc':self.now.isoformat(),'valid_until_utc':(self.now+timedelta(hours=1)).isoformat()}
    def call(self):
        p=self.d/('receipt-%d.json'%len(list(self.d.glob('receipt*'))));write(p,self.receipt)
        return validate(self.d/'plan.json',p,now=self.now,observed_host=self.identity,check_files=False)
    def test_exact_simulated_receipt_validates(self):self.assertEqual(self.call()[0],self.plan)
    def test_unapproved_receipt_rejected(self):
        self.receipt['approved']=False
        with self.assertRaises(ValueError):self.call()
    def test_plan_hash_changed_invalidates(self):
        self.receipt['plan_sha256']='b'*64
        with self.assertRaises(ValueError):self.call()
    def test_binding_hash_changed_invalidates(self):
        self.receipt['bindings_sha256']='c'*64
        with self.assertRaises(ValueError):self.call()
    def test_expired_invalidates(self):
        self.receipt['valid_until_utc']=(self.now-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):self.call()
    def test_overlong_validity_rejected(self):
        self.receipt['valid_until_utc']=(self.now+timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):self.call()
    def test_naive_timezone_rejected(self):
        self.receipt['valid_until_utc']='2026-09-20T16:00:00'
        with self.assertRaises(ValueError):self.call()
    def test_repeated_service_use_rejected(self):
        claim(self.d/'use.json',self.d/'plan.json',self.receipt)
        with self.assertRaises(FileExistsError):claim(self.d/'use.json',self.d/'plan.json',self.receipt)
    def test_receipt_count_expansion_rejected(self):
        self.receipt['max_uses']=2
        with self.assertRaises(ValueError):self.call()

class EvidenceTests(unittest.TestCase):
    def test_journal_chain_detects_tamper(self):
        with tempfile.TemporaryDirectory() as t:
            j=Journal(Path(t)/'j');j.emit('RAW',{'cpu':'usage_usec 5'});j.emit('FINAL',{'value':5})
            self.assertFalse(inspect_journal(j.path)['errors']);(j.path/'000000.json').write_text('{}');self.assertTrue(inspect_journal(j.path)['errors'])
    def test_controller_crash_retains_attempt(self):
        s=slots()[0]
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/s['run_id'];d.mkdir();Journal(d/'journal').emit('START',s)
            r=reconcile({'slots':[s,slots()[1]]},t);self.assertEqual([x['status'] for x in r['slots']],['UNKNOWN','NOT_RUN'])
    def test_terminal_binding_mismatch_is_unknown(self):
        s=slots()[0]
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/s['run_id'];d.mkdir();write(d/'terminal.json',{'run_id':'wrong','slot_sha256':'x','terminal_status':'COMPLETED'})
            self.assertEqual(reconcile({'slots':[s]},t)['slots'][0]['status'],'UNKNOWN')
    def test_external_watchdog_covers_hung_spawn(self):
        start=time.monotonic();r=watchdog(lambda:time.sleep(5),start+0.1)
        self.assertEqual(r['reason'],'EXTERNAL_WATCHDOG');self.assertLess(time.monotonic()-start,2)
    def test_external_watchdog_preserves_child_failure(self):
        r=watchdog(lambda:os._exit(77),time.monotonic()+2);self.assertEqual(r['exitcode'],77)
    def test_external_watchdog_output_cap(self):
        r=watchdog(lambda:time.sleep(5),time.monotonic()+2,size_check=lambda:True);self.assertEqual(r['reason'],'OUTPUT_CAP')

class StatisticsTests(unittest.TestCase):
    def test_overhead_pass_ci_below_threshold(self):self.assertEqual(overhead([{'off_ns':1000000000,'on_ns':1010000000}]*20)['status'],'PASS')
    def test_overhead_fail_ci_above_threshold(self):self.assertEqual(overhead([{'off_ns':1000000000,'on_ns':1100000000}]*20)['status'],'FAIL')
    def test_overhead_noise_inconclusive(self):self.assertEqual(overhead([{'off_ns':1000000000,'on_ns':1000000000+(i%2)*60000000} for i in range(20)])['status'],'INCONCLUSIVE')
    def test_missing_pairs_never_removed(self):self.assertEqual(overhead([{'off_ns':1000000000,'on_ns':1000000000}]*19)['status'],'INCONCLUSIVE')
    def test_subresolution_batch_inconclusive(self):self.assertEqual(overhead([{'off_ns':1,'on_ns':1}]*20)['status'],'INCONCLUSIVE')
    def test_oom_coincidence_unknown(self):self.assertEqual(classify_oom({'local_oom_delta':1,'local_oom_kill_delta':1}),'UNKNOWN')
    def test_ancestor_overrides_local_events(self):self.assertEqual(classify_oom({'ancestor_oom_delta':1,'local_oom_delta':1}),'FACILITY_OR_ANCESTOR_OOM')
    def test_global_oom_distinct(self):self.assertEqual(classify_oom({'global_oom_confirmed':True}),'GLOBAL_OOM')
    def test_manual_stop_not_oom(self):self.assertEqual(classify_oom({'manual_stop':True}),'CONTROLLED_STOP')
    def test_bound_causal_record_allows_run_attribution(self):self.assertEqual(classify_oom({'kernel_victim_group_matches':True,'local_oom_delta':1,'local_oom_kill_delta':1,'ancestor_events_complete':True,'hard_limit_readback_matches':True}),'RUN_MEMORY_LIMIT')
    def test_actual_sample_gap_not_nominal_constant(self):
        r=sample_gaps([{'monotonic_ns':0,'memory_current_bytes':2},{'monotonic_ns':250000000,'memory_current_bytes':None}]);self.assertEqual(r['max_gap_ns'],250000000);self.assertEqual(r['missing_samples'],1)

class BinaryAdmissionTests(unittest.TestCase):
    def test_launcher_refuses_missing_arguments(self):
        r=subprocess.run([str(BUILD/'rcwg-n4-launcher')],capture_output=True,timeout=2);self.assertEqual(r.returncode,64)
    def test_calibration_refuses_no_isolation_marker(self):
        r=subprocess.run([str(BUILD/'rcwg-n4-calibration'),'noop','1'],env={'PATH':'/usr/bin:/bin'},capture_output=True,timeout=2);self.assertEqual(r.returncode,66)
    def test_calibration_rejects_unbounded_batch(self):
        r=subprocess.run([str(BUILD/'rcwg-n4-calibration'),'cpu','999'],capture_output=True,timeout=2);self.assertEqual(r.returncode,65)
