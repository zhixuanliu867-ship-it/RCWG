import asyncio
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from rcwg_full.evidence import ROOT
from rcwg_full.compiler import FullCompiler
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.events import Journal,verify_journal
from rcwg_full.runtime.backend import Backend
from rcwg_full.runtime.scheduler import Scheduler,ExecutionFault


def node(name,op,impl,inputs,params,outputs,**extra):
    return dict(id=name,operator=op,implementation=impl,inputs=inputs,params=params,outputs=outputs,**extra)


class Runtime(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['RCWG_FULL_BUILD'])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.directory=Path(self.tmp.name)
        self.journal=Journal(self.directory/'events.jsonl','runtime-test');self.store=ArtifactStore(self.directory/'artifacts','runtime-test',self.journal)
        self.task=json.loads((ROOT/'specs/reference_v1_0/examples/task_input.json').read_text('utf-8'))
        self.task['resources'].update(cpu_slots=2,worker_memory_limit_bytes=64*1024*1024,wall_timeout_s=10)
        self.scheduler=None
    def tearDown(self):self.journal.close();self.tmp.cleanup()

    async def execute(self,plan,sources):
        report=FullCompiler().compile(self.task,plan);self.assertEqual(report['status'],'IR_VALIDATED',report)
        backend=Backend(self.native,self.store,self.task)
        external={alias:self.store.register(sources[meta['source_id']],meta['type'],'external:'+alias) for alias,meta in report['typed_graph']['input_bindings'].items()}
        self.scheduler=Scheduler(report,self.task,external,backend,self.journal)
        return await asyncio.wait_for(self.scheduler.run(),10)

    async def test_forward_reference_native_stream_pipeline(self):
        import pyarrow as pa
        plan=json.loads((ROOT/'specs/reference_v1_0/examples/workflow_topk.json').read_text('utf-8'))
        plan['nodes'].reverse()
        rows=[{'id':i,'score':float((i*17)%29),'eligible':i%3!=0} for i in range(2111)]
        result=await self.execute(plan,{'dataset:records:v1':pa.Table.from_pylist(rows)})
        expected=[{'id':r['id'],'score':r['score']} for r in sorted([r for r in rows if r['eligible']],key=lambda r:(-r['score'],r['id']))[:20]]
        self.assertEqual(result,expected);self.assertEqual(self.scheduler.admission.instances,5)
        events=verify_journal(self.journal.path)
        started=[e['payload']['operator'] for e in events if e['event_kind']=='node_started']
        self.assertEqual(started,['scan','filter','top_k','project','emit'])
        self.assertLessEqual(self.scheduler.admission.peak_in_use,2)

    def control_task(self):
        self.task['datasets']=[{'id':'dataset:state','kind':'record','revision':'tiny-1','schema_source':'engineering','schema':{'n':'Int64'}}]
        self.task['output_contract']={'id':'result','type':'record','mode':'exact','fields':['n'],'schema':{'n':'Int64'}}
    def loop_plan(self,limit,cap=3):
        step=node('step','project','column_view',{'rows':'$bound.state'},{'representation':'record','expressions':{'n':{'op':'add','left':{'field':'n'},'right':{'literal':1}}}},{'rows':'Record'})
        loop=node('repeat','loop','bounded_loop',{'state':'$input.state'},{'condition':{'op':'lt','left':{'field':'n'},'right':{'literal':limit}},'max_iterations':cap},{'state':'Record'},regions={'body':{'bindings':{'state':'$state'},'nodes':[step],'yield':{'state':'step.rows'}}})
        return {'ir_version':'1.0','task_id':self.task['task_id'],'external_inputs':{'state':'dataset:state'},'nodes':[loop],'result':'repeat.state'}

    async def test_loop_checks_initial_and_exact_limit(self):
        self.control_task();result=await self.execute(self.loop_plan(3),{'dataset:state':{'n':0}})
        self.assertEqual(result,{'n':3});self.assertEqual(self.scheduler.admission.instances,4)

    async def test_loop_false_initial_does_not_instantiate_body(self):
        self.control_task();result=await self.execute(self.loop_plan(0),{'dataset:state':{'n':0}})
        self.assertEqual(result,{'n':0});self.assertEqual(self.scheduler.admission.instances,1)

    async def test_loop_true_at_limit_is_failure(self):
        self.control_task()
        with self.assertRaisesRegex(ExecutionFault,'LOOP_LIMIT_REACHED'):await self.execute(self.loop_plan(4),{'dataset:state':{'n':0}})
        self.assertEqual(self.scheduler.admission.instances,4)

    async def test_map_order_and_shared_instance_budget(self):
        import pyarrow as pa
        self.task['datasets']=[{'id':'dataset:rows','kind':'table','revision':'tiny-1','schema_source':'engineering','schema':{'n':'Int64'},'stats':{'row_count':11}}]
        self.task['output_contract']={'id':'result','type':'records','mode':'exact','fields':['n'],'schema':{'n':'Int64'}}
        scan=node('scan','scan','sequential',{'source':'$input.rows'},{'columns':['n']},{'rows':'Stream[Record]'})
        step=node('step','project','column_view',{'rows':'$bound.row'},{'representation':'record','expressions':{'n':{'op':'mul','left':{'field':'n'},'right':{'literal':2}}}},{'rows':'Record'})
        mapper=node('map','map','bounded_map',{'rows':'scan.rows'},{},{'rows':'Stream[Record]'},regions={'body':{'bindings':{'row':'$item'},'nodes':[step],'yield':{'rows':'step.rows'}}},resources={'max_parallelism':2})
        collect=node('collect','collect','bounded_collect',{'rows':'map.rows'},{'limit':11},{'rows':'Table'})
        plan={'ir_version':'1.0','task_id':self.task['task_id'],'external_inputs':{'rows':'dataset:rows'},'nodes':[scan,mapper,collect],'result':'collect.rows'}
        result=await self.execute(plan,{'dataset:rows':pa.table({'n':list(range(11))})})
        self.assertEqual(result,[{'n':i*2} for i in range(11)]);self.assertEqual(self.scheduler.admission.instances,14)

    async def test_dynamic_parameter_range_rechecked(self):
        import pyarrow as pa
        plan=json.loads((ROOT/'specs/reference_v1_0/examples/workflow_topk.json').read_text('utf-8'))
        self.task['datasets'].append({'id':'dataset:k','kind':'scalar','revision':'v1','schema_source':'engineering','type':'Int64'})
        plan['external_inputs']['k']='dataset:k'
        top=next(n for n in plan['nodes'] if n['operator']=='top_k');top['params'].pop('k');top['param_bindings']=[{'parameter':'k','ref':'$input.k'}]
        with self.assertRaisesRegex(ExecutionFault,'PARAMETER_RANGE'):
            await self.execute(plan,{'dataset:records:v1':pa.table({'id':[1],'score':[1.0],'eligible':[True]}),'dataset:k':-1})
