"""Actual candidate variants use the same runtime and independent result verifier."""
import asyncio,json,os
from pathlib import Path
import unittest
from rcwg_full.data.templates import build
from rcwg_full.compiler import FullCompiler
from rcwg_full.evidence import write
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.backend import Backend
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.events import Journal
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.scheduler import Scheduler
from rcwg_full.verification.compare import check_output
from support import EvidenceDirectory


class CandidateRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['RCWG_FULL_BUILD'])
    def run_variants(self,template):
        evidence=EvidenceDirectory(self.id());root=Path(evidence.name)
        try:
            built=build(template,0,'C0',root/'data');definitions=json.loads((root/'data/candidate_definitions.json').read_text('utf8'))
            catalog=DataCatalog(built['manifest_path']);outcomes=[]
            for index,candidate in enumerate(definitions['candidates'][:8]):
                directory=root/f'c{index}';directory.mkdir();report=FullCompiler().compile(built['task'],candidate['plan'])
                self.assertEqual(report['status'],'IR_VALIDATED');journal=Journal(directory/'events.jsonl',f'candidate-{index}')
                store=ArtifactStore(directory/'artifacts',f'candidate-{index}',journal);backend=Backend(self.native,store,built['task'])
                external={alias:store.register(catalog.resolve(meta['source_id']),meta['type'],'source:'+alias) for alias,meta in report['typed_graph']['input_bindings'].items()}
                try:
                    scheduler=Scheduler(report,built['task'],external,backend,journal);actual=asyncio.run(asyncio.wait_for(scheduler.run(),20))
                    verified=check_output(actual,built['recipe']['expected'],built['recipe'])
                    write(directory/'actual.json',actual);write(directory/'verification.json',verified);write(directory/'plan.json',candidate['plan'])
                    self.assertEqual(verified['status'],'PASS',(template,candidate['decisions'],actual))
                    outcomes.append({'candidate_id':candidate['candidate_id'],'decisions':candidate['decisions'],'verification':verified,'formal_budget_within':None})
                finally:journal.close()
            self.assertEqual(len(outcomes),8);write(root/'ACTUAL_CANDIDATE_COVERAGE.json',outcomes)
        finally:evidence.cleanup()


def case(template):
    def execute(self):self.run_variants(template)
    return execute
for family in ['F1','F2']:
    for number in range(1,13):setattr(CandidateRuntime,f'test_{family}_{number:02d}_eight_candidates',case(f'{family}-{number:02d}'))
