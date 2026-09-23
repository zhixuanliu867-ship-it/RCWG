"""F4 formal builder fixture -> actual worker -> independent prepared oracle."""
import asyncio,json,os
from pathlib import Path
import unittest
from rcwg_full.data.formal_stream import build_fixture
from rcwg_full.runtime.worker import execute
from rcwg_full.evidence import read,sha
from rcwg_full.verification.compare import check_output
from support import EvidenceDirectory


class FormalStreamNative(unittest.TestCase):
    def test_all_formal_reference_shapes_execute_with_bounded_fixture_objects(self):
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        for number in range(1,13):
            with self.subTest(template=number):
                case=build_fixture(f'F4-{number:02d}',1,'C1',root/f'data-{number}')
                out=root/f'worker-{number}';out.mkdir()
                request={'run_id':f'formal-fixture-{number}','mode':'ENGINEERING_NATIVE','task':case['task'],
                    'plan':case['plan'],'data_manifest':str(case['manifest_path']),
                    'data_manifest_sha256':sha(read(case['manifest_path']))}
                asyncio.run(execute(request,os.environ['RCWG_FULL_BUILD'],out))
                report=json.loads(read(out/'worker-report.json'))
                self.assertEqual(report['terminal_status'],'COMPLETED',report['failure'])
                private=json.loads(read(case['private_verifier']))
                self.assertEqual(check_output(json.loads(read(out/'result.json')),private['expected'],private)['status'],'PASS')
