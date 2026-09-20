"""N3 mock cgroup tests and separately labelled real local process fault tests."""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from rcwg_native.metrology import Limits,Driver,FakeFS,LinuxFS,FacilityFault,pairs,block_io
from rcwg_native.evidence import read,canonical
from rcwg_native.supervisor import execute
from rcwg_native.adapter import lower
from rcwg_exec.demo import prepare_fixture

OUTPUT=None;BUILD=None;EVIDENCE=[]

class CgroupMockTests(unittest.TestCase):
    def driver(self,**kwargs):return Driver(FakeFS(**kwargs),'mock-run',Limits())
    def test_limits_write_readback_and_cleanup_order(self):
        d=self.driver();d.prepare();d.fs.groups[d.ident]['cpu.stat']='usage_usec 5000\nnr_throttled 2\nthrottled_usec 100\n';d.fs.groups[d.ident]['memory.peak']='4096';d.sample();r=d.finish()
        self.assertEqual(r['cpu_usage_usec'],5000);self.assertEqual(r['worker_peak_ram_bytes'],4096);self.assertEqual(r['evidence_kind'],'SIMULATED');self.assertFalse(r['formal_isolation_verified']);self.assertIsNone(r['budget_within'])
        self.assertEqual(d.fs.ops[-1],('remove','mock-run'));self.assertLess(d.fs.ops.index(('write','memory.max')),d.fs.ops.index(('write','cgroup.kill')))
    def test_actual_host_requires_explicit_approval(self):
        with self.assertRaisesRegex(FacilityFault,'BLOCKED_RUNTIME_HOST_APPROVAL'):LinuxFS('/sys/fs/cgroup',approval=None)
    def test_shared_parent_is_never_valid_target(self):
        with self.assertRaisesRegex(FacilityFault,'SHARED_OR_NON_CGROUP_ROOT_REJECTED'):LinuxFS('/sys/fs/cgroup',approval={'approved':True,'delegated_root':'/sys/fs/cgroup','permission':'NATIVE001_N4_PER_RUN_CGROUP'})
    def test_precreate_failure(self):
        d=self.driver(fail='create')
        with self.assertRaises(OSError):d.prepare()
        self.assertFalse(d.created)
    def test_limit_write_failure_keeps_cleanup_handle(self):
        d=self.driver(fail='write:memory.max')
        with self.assertRaises(OSError):d.prepare()
        self.assertTrue(d.created);d.fs.fail=None;d.finish();self.assertFalse(d.created)
    def test_duplicate_run_cannot_reuse_group(self):
        d=self.driver();d.prepare()
        with self.assertRaises(FileExistsError):Driver(d.fs,d.ident,Limits()).prepare()
        d.finish()
    def test_old_peak_reuse_rejected(self):
        d=self.driver(initial={'memory.peak':'123'})
        with self.assertRaisesRegex(FacilityFault,'FRESH_ZERO_ACCOUNTING_REQUIRED'):d.prepare()
        d.finish()
    def test_nonzero_cpu_initial_rejected(self):
        d=self.driver(initial={'cpu.stat':'usage_usec 2\n'})
        with self.assertRaisesRegex(FacilityFault,'FRESH_ZERO_ACCOUNTING_REQUIRED'):d.prepare()
        d.finish()
    def test_final_missing_peak_is_unknown(self):
        d=self.driver();d.prepare();del d.fs.groups[d.ident]['memory.peak'];r=d.finish()
        self.assertEqual(r['status'],'MEASUREMENT_MISSING');self.assertIsNone(r['worker_peak_ram_bytes']);self.assertIsNone(r['budget_within'])
    def test_memory_current_does_not_replace_peak(self):
        d=self.driver();d.prepare();d.fs.groups[d.ident]['memory.current']='99';d.sample();d.fs.groups[d.ident]['memory.peak']='1000';r=d.finish()
        self.assertEqual(r['worker_peak_ram_bytes'],1000);self.assertEqual(r['memory_current_samples'][0]['memory_current_bytes'],99)
    def test_oom_causal_delta_is_simulated_only(self):
        d=self.driver();d.prepare();d.fs.groups[d.ident]['memory.events']='oom 1\noom_kill 1\n';r=d.finish()
        self.assertEqual(r['oom_kill_delta'],1);self.assertEqual(r['evidence_kind'],'SIMULATED');self.assertFalse(r['calibrated'])
    def test_cpu_counter_regression_is_unknown(self):
        d=self.driver();d.prepare();d.baseline['values']['cpu.stat']['usage_usec']=10;r=d.finish();self.assertIsNone(r['cpu_usage_usec']);self.assertEqual(r['status'],'MEASUREMENT_MISSING')
    def test_descendant_linger_preserves_group(self):
        d=self.driver();d.prepare();d.fs.groups[d.ident]['cgroup.events']='populated 1\n'
        with patch.object(d,'kill'):
            with self.assertRaisesRegex(FacilityFault,'DESCENDANTS_REMAIN'):d.finish(wait_s=0)
        self.assertTrue(d.created);d.finish()
    def test_limits_invalid_and_thread_budget(self):
        for kw in [{'memory_max':True},{'memory_max':1},{'threads':2},{'swap_max':1},{'timeout_s':float('nan')},{'affinity':(-1,)}]:
            with self.assertRaises(FacilityFault):Limits(**kw).validate()
    def test_malformed_counter_and_io_are_not_zero(self):
        for raw in ['usage_usec -1','usage_usec nope','usage_usec 1\nusage_usec 2']:
            with self.assertRaises(ValueError):pairs(raw)
        self.assertEqual(block_io('8:0 rbytes=50 wbytes=3\n'),{'8:0':{'rbytes':50,'wbytes':3}})
        with self.assertRaises(ValueError):block_io('8:0 rbytes=-1')
    def test_removal_failure_retains_ownership(self):
        d=self.driver();d.prepare();d.fs.fail='remove'
        with self.assertRaises(OSError):d.finish()
        self.assertTrue(d.created);d.fs.fail=None;d.finish()

class ProcessLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.base=OUTPUT/self._testMethodName;self.base.mkdir(mode=0o700)
        task,plans,recipe,data=prepare_fixture(self.base/'fixture',n=7,k=1)
        self.request=lower(task,plans['streaming_heap'],locations={task['datasets'][0]['id']:data},allowed_root=self.base,ident=self._testMethodName)['request']
    def call(self,**kw):
        result=execute(self.request,build=BUILD,output=self.base/'execution',context={'case_id':self.id(),'evidence_kind':'LOCAL_PROCESS_FAULT_INJECTION'},**kw)
        EVIDENCE.append({'test_id':self.id(),'run_directory':str((self.base/'execution').relative_to(OUTPUT)),'result':result,'scope':'LOCAL_PROCESS_FAULT_INJECTION'})
        return result
    def factory(self,code):
        def spawn(args,**kw):return subprocess.Popen([sys.executable,'-c',code],**kw)
        return spawn
    def test_spawn_failure_expected_slot_written_first(self):
        def fail(*a,**kw):
            self.assertTrue((self.base/'execution/expected_manifest.json').exists());raise OSError('synthetic spawn failure')
        r=self.call(spawn=fail);self.assertEqual(r['expected_slots'],1);self.assertFalse(r['execution_started']);self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['archive_status'],'PASS')
    def test_crash_keeps_raw_stderr_and_unknown_answer(self):
        r=self.call(spawn=self.factory('import sys; sys.stderr.write("synthetic crash\\n"); sys.exit(7)'))
        self.assertEqual(r['failure']['code'],'NATIVE_PROCESS_CRASH');self.assertEqual(r['verification']['status'],'UNKNOWN')
    def test_real_hard_deadline(self):
        r=self.call(spawn=self.factory('import time; time.sleep(10)'),timeout_s=0.05)
        self.assertEqual(r['terminal_status'],'TIMEOUT');self.assertIsNone(r['completed_wall_ns']);self.assertEqual(r['process_group_final']['live'],[])
    def test_real_owner_cancel(self):
        r=self.call(spawn=self.factory('import time; time.sleep(10)'),cancel=lambda:True)
        self.assertEqual(r['terminal_status'],'CANCELLED');self.assertEqual(r['failure']['attribution'],'owner')
    def test_real_descendant_group_timeout_cleanup(self):
        code='import os,time,signal; pid=os.fork(); time.sleep(10)'
        r=self.call(spawn=self.factory(code),timeout_s=0.1)
        self.assertEqual(r['terminal_status'],'TIMEOUT');self.assertEqual(r['process_group_final']['live'],[])
    def test_native_archive_failure_preserves_unsealed_artifacts(self):
        def fail(_):raise OSError('synthetic archive failure')
        r=self.call(archive=fail);self.assertEqual(r['archive_status'],'FAILED');self.assertTrue((self.base/'execution/result.json').exists());self.assertTrue((self.base/'execution/ARCHIVE_FAILURE.json').exists());self.assertNotIn('seal_sha256',r)
    def test_verifier_exception_is_unknown_not_worker_failure(self):
        def fail(_):raise RuntimeError('synthetic verifier failure')
        r=self.call(verify=fail);self.assertEqual(r['terminal_status'],'COMPLETED');self.assertEqual(r['verification']['status'],'UNKNOWN')
    def test_worker_environment_excludes_credentials(self):
        with patch.dict(os.environ,{'GOOGLE_APPLICATION_CREDENTIALS':'private-secret-path','GITHUB_TOKEN':'synthetic_secret'}):
            r=self.call(spawn=self.factory('import os,json; print(json.dumps(dict(os.environ)))'))
        env=read(self.base/'execution/worker.report.json');self.assertNotIn('GITHUB_TOKEN',env);self.assertNotIn('GOOGLE_APPLICATION_CREDENTIALS',env)
    def test_mock_driver_cannot_claim_real_execution(self):
        r=self.call(driver=Driver(FakeFS(),self.request['run_id'],Limits()))
        self.assertEqual(r['failure']['code'],'SIMULATED_DRIVER_CANNOT_LAUNCH_NATIVE');self.assertFalse(r['execution_started'])
