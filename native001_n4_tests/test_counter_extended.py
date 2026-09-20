"""Independent N4 fault injection. These IDs are not the missing reviewer tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rcwg_native.metrology import Driver,FakeFS,Limits,FacilityFault,block_io

class ExtendedCounters(unittest.TestCase):
    def driver(self):
        d=Driver(FakeFS(),'n4-mock',Limits());d.prepare()
        d.fs.groups[d.ident]['cpu.stat']='usage_usec 321\nnr_throttled 2\n'
        d.fs.groups[d.ident]['memory.peak']='8192'
        return d
    def test_empty_cpu_is_missing(self):
        d=self.driver();d.fs.groups[d.ident]['cpu.stat']='';r=d.finish()
        self.assertEqual(r['status'],'MEASUREMENT_MISSING');self.assertIsNone(r['cpu_usage_usec'])
        self.assertEqual(r['final']['raw']['cpu.stat'],'')
    def test_missing_usage_with_extra_field(self):
        d=self.driver();d.fs.groups[d.ident]['cpu.stat']='future 9\n';r=d.finish()
        self.assertIn('cpu.stat',r['final']['missing']);self.assertIsNone(r['cpu_usage_usec'])
    def test_initial_oom_key_required(self):
        d=Driver(FakeFS(initial={'memory.events':'oom_kill 0\n'}),'bad-init',Limits())
        with self.assertRaises(FacilityFault):d.prepare()
    def test_whitespace_io_typed(self):
        with self.assertRaises(ValueError):block_io('   \n')
    def test_empty_io_valid(self):
        self.assertEqual(block_io(''),{})
    def test_remove_failure_preserves_final(self):
        d=self.driver();d.fs.fail='remove'
        with self.assertRaises(OSError) as caught:d.finish()
        r=caught.exception.report
        self.assertEqual(r['cpu_usage_usec'],321);self.assertEqual(r['worker_peak_ram_bytes'],8192)
        self.assertIsNone(r['cleanup']['group_retained']);self.assertFalse(r['calibrated'])
    def test_kill_failure_still_observes(self):
        d=self.driver();d.fs.fail='write:cgroup.kill'
        with self.assertRaises(FacilityFault) as caught:d.finish()
        self.assertEqual(caught.exception.report['cpu_usage_usec'],321)
        self.assertEqual(caught.exception.report['cleanup']['kill'],'FAILED')
    def test_wait_failure_still_observes(self):
        d=self.driver();d.fs.fail='read:cgroup.events'
        with self.assertRaises(FacilityFault) as caught:d.finish()
        self.assertEqual(caught.exception.report['worker_peak_ram_bytes'],8192)
    def test_lingering_group_snapshot_retained(self):
        d=self.driver();d.fs.groups[d.ident]['cgroup.events']='populated 1\n'
        with patch.object(d,'kill'):
            with self.assertRaises(FacilityFault) as caught:d.finish(wait_s=0)
        self.assertEqual(caught.exception.report['cpu_usage_usec'],321)
        self.assertTrue(d.created)
    def test_partial_snapshot_continues(self):
        d=self.driver();d.fs.fail='read:memory.current';r=d.finish()
        self.assertEqual(r['cpu_usage_usec'],321);self.assertEqual(r['worker_peak_ram_bytes'],8192)
        self.assertIsNone(r['final']['values']['memory.current'])
    def test_raw_survives_parse_error(self):
        d=self.driver();d.fs.groups[d.ident]['memory.peak']='broken';r=d.finish()
        self.assertEqual(r['final']['raw']['memory.peak'],'broken')
        self.assertIsNone(r['worker_peak_ram_bytes'])
    def test_persistence_before_removal(self):
        d=self.driver();records=[];d.persist=lambda stage,r:records.append((stage,len(d.fs.ops)))
        d.finish();self.assertTrue(records)
        self.assertLess(records[-2][1],len(d.fs.ops))
    def test_snapshot_persistence_failure_blocks_removal(self):
        d=self.driver()
        def fail(*a):raise OSError('disk full')
        d.persist=fail
        with self.assertRaises(FacilityFault) as caught:d.finish()
        self.assertEqual(caught.exception.report['cpu_usage_usec'],321);self.assertTrue(d.created)
    def test_unknown_extra_counter_retained(self):
        d=self.driver();d.fs.groups[d.ident]['cpu.stat']+='future_counter 17\n';r=d.finish()
        self.assertEqual(r['final']['values']['cpu.stat']['future_counter'],17)
    def test_missing_counter_not_zero(self):
        d=self.driver();d.fs.groups[d.ident]['memory.events']='';r=d.finish()
        self.assertIsNone(r['oom_kill_delta']);self.assertIsNone(r['budget_within'])
    def test_sampler_keeps_actual_timestamps_and_errors(self):
        d=self.driver();d.sample();d.fs.fail='read:memory.current';d.sample();d.fs.fail=None;r=d.finish()
        self.assertLessEqual(r['memory_current_samples'][0]['monotonic_ns'],r['memory_current_samples'][1]['monotonic_ns'])
        self.assertIsNone(r['memory_current_samples'][1]['memory_current_bytes'])
