import json
from pathlib import Path
import unittest
import test_templates_f5 as fixture
from rcwg_full.data.templates import build
from rcwg_full.evidence import write
from support import EvidenceDirectory


class DocumentCandidates(unittest.TestCase):
    setUpClass=classmethod(fixture.F5Templates.setUpClass.__func__)
    execute_plan=fixture.F5Templates.execute_plan
    def run_variants(self,template):
        evidence=EvidenceDirectory(self.id());root=Path(evidence.name)
        try:
            built=build(template,0,'C0',root/'data')
            candidates=json.loads((root/'data/candidate_definitions.json').read_text('utf8'))['candidates'][:8]
            results=[]
            for i,candidate in enumerate(candidates):
                verified=self.execute_plan(built,candidate['plan'],root/f'candidate-{i}')
                results.append({'candidate_id':candidate['candidate_id'],'decisions':candidate['decisions'],'verification':verified,'formal_budget_within':None})
            self.assertEqual(len(results),8);write(root/'ACTUAL_CANDIDATE_COVERAGE.json',results)
        finally:evidence.cleanup()


def case(template):
    def execute(self):self.run_variants(template)
    return execute


for number in range(1,13):setattr(DocumentCandidates,f'test_F5_{number:02d}_eight_candidates',case(f'F5-{number:02d}'))
