"""Full N4 controller with injected FakeFS/processes; no real cgroup workload."""
from pathlib import Path
import json,os,tempfile,unittest
from unittest.mock import patch
from rcwg_native.metrology import FakeFS
from rcwg_native.evidence import read,write
from rcwg_native_n4.plan import slots
from rcwg_native_n4.runtime import one
from rcwg_native_n4.evidence import reconcile

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.slot=slots()[0];self.out=self.base/self.slot['run_id'];self.out.mkdir()
        self.plan={'delegated_root':str(self.base/'fakegroup'),'host':{'affinity':sorted(os.sched_getaffinity(0))},'binaries':{'launcher':{'path':'mock-launcher'},'calibration':{'path':'mock-calibration'}}}
        self.fs=FakeFS();target=self.base/'entry';target.write_text('')
        self.fs.child_entry_fd=lambda _:os.open(target,os.O_WRONLY)
    def run_case(self,fail_archive=False,fail_spawn=False):
        owner=self
        class Proc:
            pid=os.getpid();returncode=0
            def poll(self):return 0
            def wait(self,timeout=None):return 0
        def spawn(args,**kw):
            owner.assertNotIn('preexec_fn',kw)
            if fail_spawn:raise OSError('MOCK_SPAWN_FAILED')
            kw['stdout'].write(json.dumps({'mode':owner.slot['mode'],'batch':owner.slot['batch'],'wall_ns':1000000,'process_cpu_ns':900000}).encode());return Proc()
        with patch('rcwg_native_n4.approval.validate',return_value=(self.plan,{}, {'slots':[self.slot]})),patch('rcwg_native_n4.runtime.LinuxFS',return_value=self.fs),patch('rcwg_native_n4.runtime.context_snapshot',return_value={'scope':'SIMULATED'}),patch('rcwg_native_n4.runtime.subprocess.Popen',side_effect=spawn),patch('rcwg_native_n4.runtime.os.read',return_value=str(os.getpid()).encode()),patch('rcwg_native_n4.runtime.verify_membership',return_value={'membership':'SIMULATED','affinity':self.plan['host']['affinity'][:1]}):
            return one(self.slot,self.plan,self.out,('mockplan','mockreceipt'))
    def test_full_mock_controller_archives_before_cleanup(self):
        r=self.run_case();self.assertEqual(r['terminal_status'],'COMPLETED');self.assertEqual(r['measurements']['evidence_kind'],'SIMULATED')
        self.assertEqual(reconcile({'slots':[self.slot]},self.base)['slots'][0]['status'],'COMPLETED')
    def test_spawn_failure_retains_baseline_and_final(self):
        r=self.run_case(fail_spawn=True);self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertIsNotNone(r['measurements']['baseline']);self.assertIsNotNone(r['measurements']['final'])
    def test_remove_failure_retains_counter_journal(self):
        self.fs.fail='remove';r=self.run_case();self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertIsNotNone(r['measurements']['cpu_usage_usec']);self.assertTrue((self.out/'journal').exists())
    def test_collection_fault_has_partial_original_snapshots(self):
        self.slot['fault']='collection';r=self.run_case();self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertIsNotNone(r['measurements']['baseline']['raw']['cpu.stat']);self.assertTrue(r['measurements']['final']['missing'])
    def test_seal_failure_preserves_independent_terminal(self):
        self.slot['fault']='seal'
        with self.assertRaisesRegex(RuntimeError,'ARCHIVE_FAILED'):self.run_case()
        self.assertTrue((self.out/'terminal.json').exists());self.assertEqual(reconcile({'slots':[self.slot]},self.base)['slots'][0]['status'],'INFRA_FAILURE')
    def test_tampered_journal_not_reported_as_complete(self):
        self.run_case();(self.out/'journal/000000.json').write_text('{}')
        self.assertEqual(reconcile({'slots':[self.slot]},self.base)['slots'][0]['status'],'UNKNOWN')
    def test_tampered_terminal_not_reported_as_complete(self):
        self.run_case();r=read(self.out/'terminal.json');r['verification']='FAIL';(self.out/'terminal.json').write_text(json.dumps(r))
        self.assertEqual(reconcile({'slots':[self.slot]},self.base)['slots'][0]['status'],'UNKNOWN')
    def test_output_failure_retains_external_claim(self):
        write(self.out/'CLAIM.json',self.slot)
        with patch('rcwg_native_n4.runtime.Journal',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.run_case()
        r=reconcile({'slots':[self.slot]},self.base);self.assertEqual(r['expected'],1);self.assertEqual(r['slots'][0]['status'],'UNKNOWN')
