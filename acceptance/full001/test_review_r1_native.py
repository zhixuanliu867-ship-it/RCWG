"""Actual source-bound native/worker regressions (never standalone Fault probes)."""
import asyncio
import copy
import json
import os
import unittest
from pathlib import Path
from rcwg_full.evidence import ROOT,read,sha
from rcwg_full.data.prepare import prepare
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.worker import execute
from rcwg_full.runtime.errors import ExecutionFault
from rcwg_full.runtime.spilled import SpilledTable
from support import EvidenceDirectory


class NativeFailuresR1(unittest.TestCase):
    def setUp(self):
        self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
        self.build=os.environ['RCWG_FULL_BUILD']
    def tearDown(self):self.tmp.cleanup()
    def worker(self,task,plan,sources):
        task,manifest,path=prepare(task,sources,self.root/'data')
        request={'run_id':'r1-fault','mode':'ENGINEERING_NATIVE','task':task,'plan':plan,
                 'data_manifest':str(path),'data_manifest_sha256':sha(read(path))}
        out=self.root/'worker';out.mkdir()
        asyncio.run(execute(request,self.build,out))
        return json.loads(read(out/'worker-report.json'))
    def relational(self):
        import pyarrow as pa
        task=json.loads(read(ROOT/'specs/reference_v1_0/examples/task_input.json'))
        plan=json.loads(read(ROOT/'specs/reference_v1_0/examples/workflow_topk.json'))
        task['datasets'][0]['stats']['row_count']=3
        table=pa.table({'id':[1,2,3],'score':[1.,2.,3.],'eligible':[True,True,True]})
        return task,plan,{'dataset:records:v1':table}
    def test_actual_arithmetic_failure_reaches_worker_as_plan(self):
        task,plan,sources=self.relational()
        plan['nodes'][1]['params']['predicate']={'op':'gt','left':{'op':'div','left':{'field':'score'},'right':{'literal':0.0}},'right':{'literal':1.0}}
        result=self.worker(task,plan,sources)
        self.assertEqual(result['terminal_status'],'MODEL_FAILURE',result['failure'])
        self.assertEqual(result['failure']['code'],'DIVISION_BY_ZERO');self.assertEqual(result['failure']['origin'],'native')
        self.assertTrue(result['failure']['node_instance']);self.assertEqual(result['failure']['attribution'],'plan')
    def test_actual_instance_budget_reaches_worker_as_plan(self):
        task,plan,sources=self.relational();plan['limits']['max_node_instances']=1
        result=self.worker(task,plan,sources)
        self.assertEqual(result['terminal_status'],'MODEL_FAILURE',result['failure'])
        self.assertEqual(result['failure']['code'],'DYNAMIC_INSTANCE_LIMIT')
    def test_actual_dynamic_graph_target_reaches_worker_as_plan(self):
        from rcwg_full.data.graph_templates import f3
        case=f3('F3-03',0,'C0');plan=case['plan']
        for node in plan['nodes']:
            if node['operator']=='graph_shortest_path':node['params']['target']=[999999]
        result=self.worker(case['task'],plan,{'dataset:'+k:v for k,v in case['rows'].items()})
        self.assertEqual(result['terminal_status'],'MODEL_FAILURE',result['failure'])
        self.assertEqual(result['failure']['code'],'UNKNOWN_SEED');self.assertEqual(result['failure']['origin'],'native')
    def test_native_facility_fault_stays_facility(self):
        native=Native(self.build)
        with self.assertRaises(ExecutionFault) as error:native.module.expression('{','{}')
        self.assertEqual(error.exception.attribution,'facility');self.assertEqual(error.exception.origin,'native')


class BoundedNativeR1(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        self.pa=pa;self.native=Native(os.environ['RCWG_FULL_BUILD'],'diagnostic')
        self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_grouped_topk_retains_k_rows_per_group_across_batches(self):
        rows=[{'id':i,'g':i%3,'score':float((i*37)%71)} for i in range(8209)]
        table=self.pa.Table.from_pylist(rows);params={'k':5,'partition_by':['g'],'keys':[{'field':'score','direction':'desc'}]}
        state=self.native.topk_begin(table.schema,params)
        for batch in table.to_batches(max_chunksize=127):self.native.aggregate_consume(state,self.pa.Table.from_batches([batch]))
        actual,counts=self.native.aggregate_finish(state)
        expected=[r for g in range(3) for r in sorted((r for r in rows if r['g']==g),key=lambda r:(-r['score'],r['id']))[:5]]
        self.assertEqual(actual.to_pylist(),expected)
        self.assertEqual(counts['peak_retained_rows'],15);self.assertLessEqual(counts['peak_input_batch_rows'],127)
        self.assertEqual(counts['retained_input_buffers'],0)
    def test_external_sort_returns_bounded_disk_reader_after_multiple_merge_levels(self):
        rows=[{'id':i,'score':float((i*37)%71)} for i in range(8209)]
        table=self.pa.Table.from_pylist(rows);params={'keys':[{'field':'score','direction':'desc'}]}
        state=self.native.sort_begin(table.schema,params,self.root)
        for batch in table.to_batches(max_chunksize=127):self.native.aggregate_consume(state,self.pa.Table.from_batches([batch]))
        path,count,counts=self.native.sort_finish(state)
        batches=list(SpilledTable(path).batches())
        self.assertEqual(count,8209);self.assertLessEqual(max(b.num_rows for b in batches),1024)
        self.assertEqual([r for b in batches for r in b.to_pylist()],sorted(rows,key=lambda r:(-r['score'],r['id'])))
        self.assertLessEqual(counts['peak_merge_readers'],8);self.assertGreater(counts['merge_passes'],2)
        self.assertEqual([p for p in self.root.glob('*.arrowstream')],[Path(path)])
