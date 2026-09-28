"""All F5 source fixtures execute against Arrow/C++ and a labeled exact replay."""
import asyncio,json,os
from copy import deepcopy
from pathlib import Path
import unittest
from rcwg_full.data.templates import build
from rcwg_full.data.document_templates import f5
from rcwg_full.compiler import FullCompiler
from rcwg_full.evidence import write,digest
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.backend import Backend
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.document_registry import DocumentRegistry
from rcwg_full.runtime.documents import ReplaySemantic
from rcwg_full.runtime.events import Journal,verify_journal
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.scheduler import Scheduler
from rcwg_full.verification.document_oracle import f5_expected,verify_document_result,verify_rows
from rcwg_full.verification.mixed_oracle import verify_mixed_result
from support import EvidenceDirectory


class F5Templates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['RCWG_FULL_BUILD'])
    def execute_plan(self,built,plan,directory):
        compiled=FullCompiler().compile(built['task'],plan);self.assertEqual(compiled['status'],'IR_VALIDATED',compiled)
        catalog=DataCatalog(built['manifest_path']).bind(built['task']);directory.mkdir()
        journal=Journal(directory/'events.jsonl',self.id());store=ArtifactStore(directory/'artifacts',self.id(),journal)
        replay=ReplaySemantic(built['replay']['responses'],mode='ENGINEERING_REPLAY')
        documents=DocumentRegistry(catalog,native=self.native,event=lambda kind,payload:journal.append(kind,payload))
        backend=Backend(self.native,store,built['task'],documents=documents,semantic=replay)
        external={alias:store.register(catalog.resolve(meta['source_id']) if meta['type']['kind']=='DatasetRef' else catalog.resolve(meta['source_id']).value(),meta['type'],'source:'+alias) for alias,meta in compiled['typed_graph']['input_bindings'].items()}
        try:
            scheduler=Scheduler(compiled,built['task'],external,backend,journal)
            actual=asyncio.run(asyncio.wait_for(scheduler.run(),20));write(directory/'actual.json',actual)
            journal.seal(directory/'journal-seal.json');events=verify_journal(journal.path)
            verifier=verify_mixed_result if built['template_id'].startswith('F6-') else verify_document_result
            verified=verifier(actual,built['recipe']['expected'],built['rows']['documents'],events=events)
            write(directory/'verification.json',verified);write(directory/'service_calls.json',replay.calls)
            self.assertEqual(verified['status'],'PASS',(built['template_id'],verified,actual))
            self.assertTrue(replay.calls);self.assertTrue(all(c['paid_calls']==0 for c in replay.calls))
            if built['template_id']=='F5-12':
                requests=[e['payload']['context_tokens'] for e in events if e['event_kind']=='semantic_request']
                from rcwg_full.runtime.documents import tokens
                self.assertLess(sum(requests),sum(len(tokens(d['canonical_text'])) for d in built['rows']['documents']))
            return verified
        finally:journal.close()
    def run_case(self,template,base,condition):
        evidence=EvidenceDirectory(self.id());root=Path(evidence.name)
        try:
            built=build(template,base,condition,root/'data');self.assertEqual(built['proof']['status'],'IR_VALIDATED',built['proof'])
            self.execute_plan(built,built['plan'],root/'execution')
        finally:evidence.cleanup()


def case(template,base,condition):
    def execute(self):self.run_case(template,base,condition)
    return execute


for number in range(1,13):
    for base in range(5):
        for condition in ['C0','C1','C2','C3']:
            setattr(F5Templates,f'test_F5_{number:02d}_b{base}_{condition}',case(f'F5-{number:02d}',base,condition))


class F5Definitions(unittest.TestCase):
    def test_distinct_seeds_and_c1_only_neutral_text(self):
        for number in range(1,13):
            cases=[f5(f'F5-{number:02d}',base,'C0') for base in range(5)]
            self.assertEqual(len({r['seed'] for r in cases}),5);self.assertEqual(len({digest(r['rows']) for r in cases}),5)
            for base,small in enumerate(cases):
                large=f5(f'F5-{number:02d}',base,'C1')
                self.assertEqual(f5_expected(small['expected_args']),f5_expected(large['expected_args']))
                for a,b in zip(small['rows']['documents'],large['rows']['documents']):
                    self.assertEqual(a['sections'][:-1],b['sections'][:-1]);self.assertGreater(len(b['canonical_text']),len(a['canonical_text']))
    def test_c2_only_ram_c3_canonical_identity(self):
        for number in range(1,13):
            for base in range(5):
                cases={c:f5(f'F5-{number:02d}',base,c) for c in ['C0','C2','C3']}
                for c in ['C2','C3']:self.assertEqual(cases['C0']['rows'],cases[c]['rows'])
                a,b=deepcopy(cases['C0']['task']),deepcopy(cases['C2']['task']);a.pop('task_id');b.pop('task_id')
                self.assertNotEqual(a['resources']['worker_memory_limit_bytes'],b['resources']['worker_memory_limit_bytes'])
                b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes'];self.assertEqual(a,b)
    def test_oracle_rejects_wrong_values_spans_and_missing_stages(self):
        for number in range(1,13):
            built=f5(f'F5-{number:02d}',2,'C0');gold=f5_expected(built['expected_args']);docs=built['rows']['documents']
            self.assertEqual(verify_document_result(gold['result'],gold,docs)['status'],'PASS')
            self.assertEqual(verify_document_result(gold['result'],gold,docs,events=[])['status'],'FAIL')
            for rows in gold['stages'].values():
                changed=deepcopy(rows);changed[0]['entity_id']='wrong-entity'
                self.assertEqual(verify_rows(changed,rows,docs)['status'],'FAIL')
                changed=deepcopy(rows)
                target=next(r for r in changed if r['evidence']);target['evidence'][0]['quote']='wrong quote'
                self.assertEqual(verify_rows(changed,rows,docs)['status'],'FAIL')
                self.assertEqual(verify_rows(list(reversed(rows)),rows,docs)['status'],'PASS')
