"""Every F1 template / base / condition executes its typed plan on actual Arrow/C++."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import unittest
from rcwg_full.data.templates import build,f1
from rcwg_full.evidence import write,digest
from rcwg_full.compiler import FullCompiler
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.backend import Backend
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.events import Journal,verify_journal
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.scheduler import Scheduler
from rcwg_full.verification.compare import check_output
from support import EvidenceDirectory


class F1Templates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['RCWG_FULL_BUILD'])
    def run_case(self,template,base,condition):
        evidence=EvidenceDirectory(self.id());directory=Path(evidence.name)
        try:
            built=build(template,base,condition,directory/'data');self.assertEqual(built['proof']['status'],'IR_VALIDATED',built['proof'])
            compiled=FullCompiler().compile(built['task'],built['plan']);catalog=DataCatalog(built['manifest_path'])
            journal=Journal(directory/'events.jsonl',self.id());journal.append('run_started',{'mode':'ENGINEERING_NATIVE'},status='RUNNING')
            store=ArtifactStore(directory/'artifacts',self.id(),journal);backend=Backend(self.native,store,built['task'])
            external={alias:store.register(catalog.resolve(meta['source_id']) if meta['type']['kind']=='DatasetRef' else catalog.resolve(meta['source_id']).value(),meta['type'],'source:'+alias) for alias,meta in compiled['typed_graph']['input_bindings'].items()}
            scheduler=Scheduler(compiled,built['task'],external,backend,journal)
            try:
                actual=asyncio.run(asyncio.wait_for(scheduler.run(),20));write(directory/'actual.json',actual)
                result=check_output(actual,built['recipe']['expected'],built['recipe']);write(directory/'independent-verification.json',result)
                self.assertEqual(result['status'],'PASS',(template,base,condition,actual,built['recipe']['expected']))
                journal.append('run_finished',{'verification':result},status='COMPLETED');journal.seal(directory/'journal-seal.json')
                events=verify_journal(journal.path)
                dispatches=[e['payload'].get('operator')+':'+e['payload'].get('implementation') for e in events if e['event_kind']=='node_started']
                write(directory/'coverage.json',{'template':template,'base':base,'condition':condition,'dispatches':dispatches,
                    'source_mode':'ACTUAL_ARROW_CPP20_ENGINEERING_NATIVE','formal_ready':False,'calibrated':False})
            finally:journal.close()
        finally:evidence.cleanup()


def case(template,base,condition):
    def execute(self):self.run_case(template,base,condition)
    return execute


for number in range(1,13):
    for base in range(5):
        for condition in ['C0','C1','C2','C3']:
            setattr(F1Templates,f'test_F1_{number:02d}_b{base}_{condition}',case(f'F1-{number:02d}',base,condition))


class F1ConditionDefinitions(unittest.TestCase):
    def test_five_distinct_seeds_and_real_data(self):
        for number in range(1,13):
            cases=[f1(f'F1-{number:02d}',base,'C0') for base in range(5)]
            self.assertEqual(len({r['seed'] for r in cases}),5)
            self.assertEqual(len({digest(r['rows']) for r in cases}),5)
    def test_c2_only_ram_c3_same_logical_data_c1_single_axis(self):
        for number in range(1,13):
            for base in range(5):
                c0=f1(f'F1-{number:02d}',base,'C0');c1=f1(f'F1-{number:02d}',base,'C1');c2=f1(f'F1-{number:02d}',base,'C2');c3=f1(f'F1-{number:02d}',base,'C3')
                self.assertEqual(c0['rows'],c2['rows']);self.assertEqual(c0['rows'],c3['rows'])
                a,b=deepcopy(c0['task']),deepcopy(c2['task']);a.pop('task_id');b.pop('task_id')
                self.assertNotEqual(a['resources']['worker_memory_limit_bytes'],b['resources']['worker_memory_limit_bytes'])
                b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes'];self.assertEqual(a,b)
                if number in {2,10}:
                    self.assertEqual(len(c0['rows']['records']),len(c1['rows']['records']))
                    self.assertTrue(any(x['eligible']!=y['eligible'] for x,y in zip(c0['rows']['records'],c1['rows']['records'])))
                    self.assertEqual([{k:v for k,v in r.items() if k!='eligible'} for r in c0['rows']['records']],
                                     [{k:v for k,v in r.items() if k!='eligible'} for r in c1['rows']['records']])
                else:self.assertEqual((len(c0['rows']['records']),len(c1['rows']['records'])),(37,113))
