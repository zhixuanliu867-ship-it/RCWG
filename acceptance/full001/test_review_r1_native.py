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
        import pyarrow as pa
        from rcwg_full.data.stream_templates import f4
        from rcwg_full.compiler import FullCompiler
        case=f4('F4-08',0,'C0');task,plan=case['task'],case['plan']
        plan['limits']['max_node_instances']=len(plan['nodes'])+1
        self.assertEqual(FullCompiler().compile(task,plan)['status'],'IR_VALIDATED')
        sources={'dataset:'+k:pa.Table.from_pylist(v) for k,v in case['rows'].items()}
        result=self.worker(task,plan,sources)
        self.assertEqual(result['terminal_status'],'MODEL_FAILURE',result['failure'])
        self.assertEqual(result['failure']['code'],'DYNAMIC_INSTANCE_LIMIT')

    def test_real_worker_plan_failures_do_not_pause_campaign(self):
        from rcwg_full.campaign.runner import PreparedNativeExecutor,CampaignRunner
        from rcwg_full.evidence import write,digest
        task,plan,sources=self.relational()
        plan['nodes'][1]['params']['predicate']={'op':'gt','left':{'op':'div','left':{'field':'score'},'right':{'literal':0.0}},'right':{'literal':1.0}}
        task,manifest,path=prepare(task,sources,self.root/'data')
        private=self.root/'private.json';write(private,{'expected':[],'comparison':'bag'})
        item={'task_path':str(path.parent/'task_public.json'),'data_manifest':str(path),'private_verifier':str(private)}
        for name in list(item):item['task_sha256' if name=='task_path' else name+'_sha256']=sha(read(item[name]))
        base={'task_id':task['task_id'],'condition':'C0','family':'F1','protocol':'P0','ledger_role':'PRIMARY'}
        slots=[{**base,'slot_id':'g','slot_kind':'generation','expected_dependencies':[]},
               *[{**base,'slot_id':f'e{i}','slot_kind':'execution','execution_repeat':i,'generation_slot_id':'g','expected_dependencies':['g']} for i in range(2)]]
        executor=PreparedNativeExecutor({task['task_id']:item},self.build,'ENGINEERING_NATIVE')
        runner=CampaignRunner(self.root/'campaign',slots,manifest_hash='a'*64,spec_hash='b'*64,mode='ENGINEERING_NATIVE',
            generate=lambda *a:{'status':'COMPLETED','plan':plan,'plan_hash':digest(plan),'model_snapshot_hash':'c'*64},execute=executor)
        try:
            result=runner.run();observations=runner.store.observations('ENGINEERING_NATIVE')
        finally:runner.close()
        self.assertEqual(result['status'],'TERMINAL',result)
        attempts=[r for r in observations if r['slot_kind']=='execution']
        self.assertEqual(len(attempts),2)
        self.assertTrue(all(r['status']=='MODEL_FAILURE' and r['failure_class']=='CONFIRMED_PLAN' for r in attempts))
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

    def sorted_file(self,rows,fields,directory):
        directory.mkdir();table=self.pa.Table.from_pylist(rows)
        state=self.native.sort_begin(table.schema,{'keys':[{'field':k,'direction':'asc','nulls':'last'} for k in fields]},directory)
        for batch in table.to_batches(max_chunksize=3):self.native.aggregate_consume(state,self.pa.Table.from_batches([batch]))
        return self.native.sort_finish(state)[0]

    def test_sorted_group_keeps_one_group_and_global_empty_count(self):
        rows=[{'g':i%13,'v':None if i%7==0 else i} for i in range(131)]
        path=self.sorted_file(rows,['g'],self.root/'sort');out=self.root/'out';out.mkdir()
        params={'group_by':['g'],'aggregates':[{'function':'sum','field':'v','as':'sum'},{'function':'count','field':None,'as':'n'}]}
        file,n,counts=self.native.sorted_group(path,params,out)
        actual=[r for b in SpilledTable(file).batches() for r in b.to_pylist()]
        expected=[{'g':g,'sum':sum(r['v'] for r in rows if r['g']==g and r['v'] is not None),'n':sum(r['g']==g for r in rows)} for g in range(13)]
        self.assertEqual(actual,expected);self.assertEqual(counts['peak_group_states'],1)
        empty=self.root/'empty';empty.mkdir();schema=self.pa.schema([('v',self.pa.int64())])
        state=self.native.sort_begin(schema,{'keys':[]},empty);path,_,_=self.native.sort_finish(state)
        file,n,_=self.native.sorted_group(path,{'group_by':[],'aggregates':[{'function':'count','field':None,'as':'n'}]},empty)
        self.assertEqual([r for b in SpilledTable(file).batches() for r in b.to_pylist()],[{'n':0}])

    def test_sorted_join_spills_duplicate_groups_and_preserves_all_join_modes(self):
        from collections import Counter
        left=[{'id':i,'k':k} for i,k in enumerate([1,1,10,2,None,-3])]
        right=[{'rid':i,'k':k} for i,k in enumerate([1,1,1,3,None,-3])]
        lpath=self.sorted_file(left,['k'],self.root/'left');rpath=self.sorted_file(right,['k'],self.root/'right')
        matches=[(l,r) for l in left for r in right if l['k'] is not None and l['k']==r['k']]
        ml={l['id'] for l,r in matches};mr={r['rid'] for l,r in matches}
        for mode in ['inner','left','right','full','semi','anti']:
            directory=self.root/mode;directory.mkdir()
            file,n,counts=self.native.sorted_join(lpath,rpath,{'keys':[{'left':'k','right':'k'}],'join_type':mode},directory)
            actual=[r for b in SpilledTable(file).batches() for r in b.to_pylist()]
            if mode in {'semi','anti'}:expected=[l for l in left if (l['id'] in ml)==(mode=='semi')]
            else:
                pairs=list(matches)
                if mode in {'left','full'}:pairs.extend((l,{'rid':None,'k':None}) for l in left if l['id'] not in ml)
                if mode in {'right','full'}:pairs.extend(({'id':None,'k':None},r) for r in right if r['rid'] not in mr)
                expected=[{'id':l['id'],'left.k':l['k'],'rid':r['rid'],'right.k':r['k']} for l,r in pairs]
            self.assertEqual(Counter(tuple(sorted(r.items())) for r in actual),Counter(tuple(sorted(r.items())) for r in expected))
            self.assertEqual(counts['peak_join_cursors'],3)
            self.assertFalse(list(directory.glob('join-group-*')))
