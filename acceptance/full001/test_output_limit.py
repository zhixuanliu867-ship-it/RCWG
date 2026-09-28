import json,os,unittest
from pathlib import Path
from rcwg_full.runtime.output_limit import OutputWatchdog
from rcwg_full.evidence import write,ROOT
from support import EvidenceDirectory


class OutputLimits(unittest.TestCase):
    def test_observed_bytes_include_multiple_files_and_record_overrun(self):
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)/'payload';root.mkdir()
        watchdog=OutputWatchdog(root,9);write(root/'one',b'12345');self.assertFalse(watchdog.sample())
        write(root/'two',b'12345');self.assertTrue(watchdog.sample())
        self.assertEqual(watchdog.snapshot()['observed_peak_bytes'],10)
        self.assertFalse(watchdog.snapshot()['hard_filesystem_quota'])
        for invalid in [True,0,-1,None,1.5]:
            with self.subTest(value=invalid),self.assertRaises(ValueError):OutputWatchdog(root,invalid)

    def test_actual_supervisor_output_limit_stops_drains_and_preserves_failure(self):
        from rcwg_full.data.templates import build
        from rcwg_full.runtime.supervisor import execute
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        built=build('F1-01',0,'C0',root/'data')
        report=execute(built['task'],built['plan'],built['manifest_path'],build=os.environ['RCWG_FULL_BUILD'],
            output=root/'run',engineering_output_limit_bytes=1)
        self.assertEqual(report['terminal_status'],'INFRA_FAILURE');self.assertEqual(report['failure']['code'],'OUTPUT_LIMIT_EXCEEDED')
        self.assertEqual(report['process_group_final']['live'],[]);self.assertEqual(report['cleanup_failures'],[])
        self.assertFalse(report['budget_failure_confirmed']);self.assertEqual(report['verification']['status'],'UNKNOWN')
        self.assertGreater(report['output_watchdog']['observed_peak_bytes'],report['output_watchdog']['limit_bytes'])
        self.assertTrue((root/'run/seal.json').is_file());self.assertFalse(report['formal_ready'])

    def test_formal_cannot_override_receipt_output_limit(self):
        from rcwg_full.runtime.supervisor import execute
        # The mode/admission boundary fails before creating any output path.
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        with self.assertRaises((PermissionError,ValueError)):
            execute({}, {}, root/'missing',build=root/'missing-build',output=root/'forbidden',mode='FORMAL',engineering_output_limit_bytes=1)
        self.assertFalse((root/'forbidden').exists())
