"""Real native worker integration, small BOOT_ONLY data, no service calls."""
import os
import json
import unittest
from rcwg_full.runtime.supervisor import execute
from rcwg_full.runtime.observation import PROFILE
from rcwg_full.runtime.events import journal_summary
import test_supervision


class Observation2Native(unittest.TestCase):
    setUp=test_supervision.Supervision.setUp
    tearDown=test_supervision.Supervision.tearDown

    def test_native_worker_seals_compact_observation_and_binds_profile(self):
        report=execute(self.task,self.plan,self.manifest_path,build=os.environ['RCWG_FULL_BUILD'],
                       output=self.root/'compact',observation_profile=PROFILE)
        self.assertEqual(report['terminal_status'],'COMPLETED',report.get('failure'))
        self.assertEqual(report['worker']['journal_status'],'SEALED')
        self.assertEqual(report['measurement_profile']['identity']['observation_profile'],PROFILE)
        self.assertEqual(report['worker']['buffer_metrics']['registered_python_heap']['status'],'NOT_MEASURED')
        summary=journal_summary(self.root/'compact/worker/events.jsonl')
        self.assertEqual(summary['first']['event_kind'],'run_started');self.assertEqual(summary['last']['event_kind'],'run_finished')
        self.assertEqual(report['exec_elapsed_scope'],'CONTROLLER_GO_TO_COMMITTED_RESULT_RECEIPT')
        self.assertFalse(report['formal_ready'])

    def test_worker_primary_input_fault_remains_independently_reported(self):
        manifest=json.loads(self.manifest_path.read_text())
        path=self.manifest_path.parent/manifest['sources'][0]['physical_files'][0]['path']
        with path.open('ab') as file:file.write(b'tamper')
        report=execute(self.task,self.plan,self.manifest_path,build=os.environ['RCWG_FULL_BUILD'],
                       output=self.root/'tamper-compact',observation_profile=PROFILE)
        self.assertEqual(report['terminal_status'],'INFRA_FAILURE')
        self.assertIsNotNone(report['failure']);self.assertTrue((self.root/'tamper-compact/worker/worker-report.json').exists())
