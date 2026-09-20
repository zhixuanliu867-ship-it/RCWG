"""Independent process proof parser and unavailable host event regressions."""
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from unittest.mock import patch
from rcwg_native_n4.runtime import process_evidence,host_event_evidence
from rcwg_native_n4.assess import assess

class MembershipTests(unittest.TestCase):
    def fixture(self,path,pid,parent,group='0::/system.slice/n4.service/test'):
        (path/f'process-{pid}.txt').write_text(f'{pid}\n{parent}\n{group}\n0,\n')
    def test_parent_and_both_children_bound(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            for pid,parent in [(10,1),(11,10),(12,10)]:self.fixture(p,pid,parent)
            r=process_evidence(p,'/sys/fs/cgroup/system.slice/n4.service/test',(0,),10,2)
            self.assertEqual(r['status'],'PASS');self.assertEqual(len(r['records']),3)
    def test_child_wrong_group_not_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p,10,1);self.fixture(p,11,10,group='0::/wrong')
            self.assertEqual(process_evidence(p,'/sys/fs/cgroup/system.slice/n4.service/test',(0,),10,1)['status'],'INCONCLUSIVE')
    def test_missing_child_not_inferred_from_peak(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p,10,1)
            self.assertEqual(process_evidence(p,'/sys/fs/cgroup/system.slice/n4.service/test',(0,),10,2)['status'],'INCONCLUSIVE')
    def test_c04_requires_process_proof_even_with_large_peak(self):
        manifest={'slots':[{'run_id':'test','case':'C04','category':'calibration'}]}
        record={'slots':[{'run_id':'test','status':'COMPLETED','result':{'terminal_status':'COMPLETED','cleanup':{'status':'REMOVED'},'measurements':{'status':'COUNTERS_OBSERVED','worker_peak_ram_bytes':100000000}}}]}
        self.assertEqual(assess(manifest,record)['cases']['C04']['status'],'INCONCLUSIVE')
    def test_unprivileged_host_log_denial_preserved(self):
        denied=SimpleNamespace(returncode=1,stdout=b'',stderr=b'permission denied')
        with patch('rcwg_native_n4.runtime.subprocess.run',return_value=denied),patch.object(Path,'read_text',side_effect=PermissionError('denied')):
            r=host_event_evidence('n4.service')
        self.assertEqual(r['kernel_oom']['exit_code'],1);self.assertFalse(r['kernel_oom']['privilege_escalation']);self.assertEqual(r['/proc/vmstat']['missing'],'PermissionError')
