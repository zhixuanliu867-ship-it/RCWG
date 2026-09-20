"""Focused regression tests; FakeFS only, never writes a real cgroup.

Run with PYTHONPATH pointing to either source_snapshot or the patched repository.
These tests add coverage; they do not replace the frozen NATIVE/EXEC/API gates.
"""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch, Mock
from rcwg_native.metrology import Driver, FakeFS, Limits, FacilityFault
from rcwg_native import supervisor as sup


class CounterIntegrityTests(unittest.TestCase):
    def prepared(self, ident='n4_counter_test'):
        fs=FakeFS(); driver=Driver(fs,ident,Limits()); driver.prepare()
        return fs,driver

    def test_valid_counters_and_empty_io_are_observed(self):
        fs,d=self.prepared(); fs.groups[d.ident]['cpu.stat']='usage_usec 250000\n'
        fs.groups[d.ident]['memory.peak']='67108864'
        r=d.finish(); self.assertEqual(r['status'],'COUNTERS_OBSERVED')
        self.assertEqual(r['cpu_usage_usec'],250000)
        self.assertEqual(r['worker_peak_ram_bytes'],67108864)
        self.assertFalse(r['formal_ready']); self.assertFalse(r['calibrated'])
        self.assertIsNone(r['budget_within'])

    def test_empty_final_cpu_is_missing(self):
        fs,d=self.prepared(); fs.groups[d.ident]['cpu.stat']=''
        r=d.finish(); self.assertEqual(r['status'],'MEASUREMENT_MISSING')
        self.assertIsNone(r['cpu_usage_usec']); self.assertIn('cpu.stat',r['final']['missing'])

    def test_final_cpu_without_usage_is_missing(self):
        fs,d=self.prepared(); fs.groups[d.ident]['cpu.stat']='nr_throttled 0\n'
        r=d.finish(); self.assertEqual(r['status'],'MEASUREMENT_MISSING')
        self.assertIsNone(r['cpu_usage_usec'])

    def test_empty_initial_events_are_rejected(self):
        d=Driver(FakeFS(initial={'memory.events':''}),'n4_empty_initial',Limits())
        with self.assertRaises(FacilityFault): d.prepare()

    def test_initial_events_without_oom_are_rejected(self):
        d=Driver(FakeFS(initial={'memory.events':'oom_kill 0\n'}),'n4_event_initial',Limits())
        with self.assertRaises(FacilityFault): d.prepare()

    def test_empty_final_events_are_missing(self):
        fs,d=self.prepared(); fs.groups[d.ident]['memory.events']=''
        r=d.finish(); self.assertEqual(r['status'],'MEASUREMENT_MISSING')
        self.assertIsNone(r['oom_kill_delta']); self.assertIn('memory.events',r['final']['missing'])

    def test_final_events_without_oom_kill_are_missing(self):
        fs,d=self.prepared(); fs.groups[d.ident]['memory.events']='oom 0\n'
        r=d.finish(); self.assertEqual(r['status'],'MEASUREMENT_MISSING')

    def test_whitespace_io_is_typed_missing_not_indexerror(self):
        fs,d=self.prepared(); fs.groups[d.ident]['io.stat']='   \n'
        r=d.finish(); self.assertEqual(r['status'],'MEASUREMENT_MISSING')
        self.assertIn('io.stat',r['final']['missing'])

    def test_valid_device_io_retained(self):
        fs,d=self.prepared(); fs.groups[d.ident]['io.stat']='8:0 rbytes=4096 wbytes=2048 rios=1 wios=1\n'
        r=d.finish(); self.assertEqual(r['final']['values']['io.stat']['8:0']['rbytes'],4096)

    def test_unknown_extra_cpu_field_allowed(self):
        fs,d=self.prepared(); fs.groups[d.ident]['cpu.stat']='usage_usec 123\nfuture_counter 9\n'
        self.assertEqual(d.finish()['cpu_usage_usec'],123)

    def test_counter_regression_stays_missing(self):
        fs,d=self.prepared(); d.baseline['values']['cpu.stat']['usage_usec']=4
        r=d.finish(); self.assertEqual(r['status'],'MEASUREMENT_MISSING')
        self.assertIsNone(r['cpu_usage_usec'])

    def test_malformed_cpu_stays_missing(self):
        fs,d=self.prepared(); fs.groups[d.ident]['cpu.stat']='usage_usec nope\n'
        self.assertEqual(d.finish()['status'],'MEASUREMENT_MISSING')

    def test_negative_peak_stays_missing(self):
        fs,d=self.prepared(); fs.groups[d.ident]['memory.peak']='-1'
        r=d.finish(); self.assertIsNone(r['worker_peak_ram_bytes'])
        self.assertEqual(r['status'],'MEASUREMENT_MISSING')

    def test_remove_failure_carries_observed_counters(self):
        fs,d=self.prepared(); fs.groups[d.ident]['memory.peak']='67108864'
        fs.groups[d.ident]['cpu.stat']='usage_usec 250000\n'; fs.fail='remove'
        try: d.finish()
        except (OSError,FacilityFault) as exc:
            r=getattr(exc,'partial_report',None)
            self.assertIsNotNone(r,'Observed final counters must survive cleanup failure')
            self.assertEqual(r['worker_peak_ram_bytes'],67108864)
            self.assertEqual(r['cpu_usage_usec'],250000)
            self.assertEqual(r['cleanup']['status'],'FAILED')
            self.assertIsNone(r['cleanup']['group_retained'])
            self.assertIn(d.ident,fs.groups)
        else: self.fail('Cleanup failure must not be reported as success')

    def test_snapshot_retains_raw_counter_text(self):
        fs,d=self.prepared(); fs.groups[d.ident]['cpu.stat']='garbled\n'
        r=d.snapshot(); self.assertEqual(r['raw']['cpu.stat'],'garbled\n')
        self.assertIsNone(r['values']['cpu.stat'])

    def test_never_created_preserves_null_budget(self):
        r=Driver(FakeFS(),'n4_not_created',Limits()).finish()
        self.assertEqual(r['status'],'NOT_CREATED'); self.assertIsNone(r['budget_within'])

    def test_success_removes_owned_fake_group(self):
        fs,d=self.prepared(); r=d.finish()
        self.assertNotIn(d.ident,fs.groups); self.assertFalse(d.created)
        self.assertEqual(r['cleanup']['status'],'REMOVED')

    def test_supervisor_archives_partial_counters_on_exception(self):
        # Isolate the finally-path contract. No subprocess is created; all cgroup
        # behavior is injected. Actual native/cgroup integration remains N4 work.
        observed={'worker_peak_ram_bytes':67108864,'cpu_usage_usec':250000,
                  'status':'MEASUREMENT_OR_CLEANUP_FAILED','formal_ready':False,
                  'calibrated':False,'budget_within':None,'evidence_kind':'SIMULATED',
                  'cleanup':{'status':'FAILED'}}
        failure=FacilityFault('SIMULATED_REMOVE_FAILURE'); failure.partial_report=observed
        driver=Mock(); driver.finish.side_effect=failure
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run'
            def bootstrap(path): Path(path).mkdir(); return Path(path)
            with patch.object(sup,'bootstrap',side_effect=bootstrap),patch.object(sup,'closure_hashes',return_value={}),patch.object(sup,'binary_binding',side_effect=FacilityFault('SIMULATED_PRE_SPAWN_FAILURE')):
                result=sup.execute({'run_id':'n4_supervisor','mode':'performance','nodes':[]},build=tmp,output=out,context={'test':'offline'},driver=driver)
            self.assertEqual(result['terminal_status'],'INFRA_FAILURE')
            self.assertFalse(result['execution_started'])
            self.assertEqual(result['measurements']['worker_peak_ram_bytes'],67108864)
            stored=json.loads((out/'report.json').read_text())
            self.assertEqual(stored['measurements']['cpu_usage_usec'],250000)
            self.assertEqual(result['archive_status'],'PASS')


if __name__=='__main__': unittest.main(verbosity=2)
