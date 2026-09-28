"""Actual F3 formal-reference shapes checked by the independent disk oracle."""
import asyncio,json,os
from pathlib import Path
import unittest
from rcwg_full.data.formal_graph import build_fixture
from rcwg_full.runtime.worker import execute
from rcwg_full.evidence import read,sha
from rcwg_full.verification.prepared import check_prepared
from support import EvidenceDirectory


class FormalGraphNative(unittest.TestCase):
    def test_all_formal_graph_references_and_path_alternatives(self):
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        for number in range(1,13):
            with self.subTest(template=number):
                case=build_fixture(f'F3-{number:02d}',1,'C1',root/f'data-{number}')
                out=root/f'worker-{number}';out.mkdir()
                request={'run_id':f'formal-graph-fixture-{number}','mode':'ENGINEERING_NATIVE','task':case['task'],
                    'plan':case['plan'],'data_manifest':str(case['manifest_path']),'data_manifest_sha256':sha(read(case['manifest_path']))}
                asyncio.run(execute(request,os.environ['RCWG_FULL_BUILD'],out))
                report=json.loads(read(out/'worker-report.json'))
                self.assertEqual(report['terminal_status'],'COMPLETED',report['failure'])
                actual=json.loads(read(out/'result.json'))
                self.assertEqual(check_prepared(actual,case['private_verifier'])['status'],'PASS')
                if number in {2,3,5,12}:
                    paths=actual['paths'] if number==12 else actual
                    for p in paths:
                        if p['reachable']:p['distance']+=1;break
                    self.assertEqual(check_prepared(actual,case['private_verifier'])['status'],'FAIL')
