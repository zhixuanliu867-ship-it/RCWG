"""Independent streaming checks: bounded batches, no retained input, source closure."""
import asyncio
from copy import deepcopy
import gc
import json
import os
from pathlib import Path
import unittest
import weakref
from unittest.mock import patch
from rcwg_full.data.prepare import prepare
from rcwg_full.data.templates import task_shell,descriptor,Plan
from rcwg_full.compiler import FullCompiler
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.values import arrow_schema
from rcwg_full.runtime.artifacts import ArtifactStore
from rcwg_full.runtime.events import Journal,verify_journal
from rcwg_full.runtime.backend import Backend
from rcwg_full.runtime.scheduler import Scheduler
from support import EvidenceDirectory


class StreamingNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        cls.pa=pa;cls.native=Native(os.environ['RCWG_FULL_BUILD'],'diagnostic')

    def test_incremental_group_state_releases_all_input_buffers(self):
        schema=self.pa.schema([('g',self.pa.int64()),('v',self.pa.int64())])
        params={'group_by':['g'],'aggregates':[{'function':fn,'field':'v','as':fn} for fn in ['sum','min','max','count','mean']]}
        state=self.native.aggregate_begin(schema,params);expected={i:[] for i in range(7)}
        baseline=self.pa.total_allocated_bytes()
        for base in range(53):
            rows=[{'g':i%7,'v':None if i%13==0 else i-1000} for i in range(base*173,(base+1)*173)]
            for row in rows:
                if row['v'] is not None:expected[row['g']].append(row['v'])
            batch=self.pa.Table.from_pylist(rows,schema=schema);reference=weakref.ref(batch)
            self.native.aggregate_consume(state,batch);del batch;gc.collect()
            self.assertIsNone(reference());self.assertEqual(self.pa.total_allocated_bytes(),baseline)
        result,counts=self.native.aggregate_finish(state)
        want=[{'g':g,'sum':sum(v),'min':min(v),'max':max(v),'count':len(v),'mean':sum(v)/len(v)} for g,v in expected.items()]
        self.assertEqual(result.to_pylist(),want);self.assertEqual(counts['rows_in'],53*173)
        self.assertEqual(counts['peak_group_states'],7);self.assertEqual(counts['peak_input_batch_rows'],173)
        with self.assertRaisesRegex(Exception,'AGGREGATE_STATE_CLOSED'):self.native.aggregate_finish(state)

    def test_empty_nulls_and_poisoned_overflow(self):
        schema=self.pa.schema([('v',self.pa.int64())]);params={'group_by':[],'aggregates':[{'function':'sum','field':'v','as':'s'},{'function':'count','field':None,'as':'n'}]}
        for rows,expected in [([],[{'s':None,'n':0}]),([{'v':None}]*7,[{'s':None,'n':7}])]:
            state=self.native.aggregate_begin(schema,params);self.native.aggregate_consume(state,self.pa.Table.from_pylist(rows,schema=schema))
            self.assertEqual(self.native.aggregate_finish(state)[0].to_pylist(),expected)
        state=self.native.aggregate_begin(schema,params)
        with self.assertRaisesRegex(Exception,'ARITHMETIC_OVERFLOW'):self.native.aggregate_consume(state,self.pa.Table.from_pylist([{'v':2**63-1},{'v':1}],schema=schema))
        with self.assertRaisesRegex(Exception,'AGGREGATE_STATE_CLOSED'):self.native.aggregate_finish(state)

    def test_signed_zero_keys_are_equal_in_all_relational_algorithms(self):
        rows=self.pa.Table.from_pylist([{'k':-0.0,'v':1},{'k':0.0,'v':2}]);params={'group_by':['k'],'aggregates':[{'function':'sum','field':'v','as':'s'}]}
        state=self.native.aggregate_begin(rows.schema,params);self.native.aggregate_consume(state,rows)
        self.assertEqual(self.native.aggregate_finish(state)[0].to_pylist(),[{'k':0.,'s':3}])
        for implementation in ['hash','sort_unique']:
            self.assertEqual(self.native.relational('deduplicate',implementation,rows,{'keys':['k'],'keep':'first'})[0].num_rows,1)
        for implementation in ['hash','sort_merge','block_nested']:
            self.assertEqual(self.native.relational('join',implementation,rows.slice(0,1),{'keys':[{'left':'k','right':'k'}],'join_type':'inner','build_side':'left'},rows.slice(1))[0].num_rows,1)


class StreamingSources(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        self.pa=pa;self.evidence=EvidenceDirectory(self.id());self.root=Path(self.evidence.name)
        self.schema={'g':'Int64','v':'Int64','wide':'Utf8'}
        self.rows=[{'g':i%7,'v':i-100,'wide':('中文🙂'+str(i))*90} for i in range(4097)]
        output={'id':'result','type':'records','mode':'exact','fields':['g','total'],'schema':{'g':'Int64','total':'Int64'}}
        self.task=task_shell('F4-03',0,'C0','按 g 求 sum(v)。',output);self.task['datasets']=[descriptor('records',self.schema,self.rows)]
        table=pa.Table.from_pylist(self.rows,schema=arrow_schema({'kind':'Table','schema':self.schema}))
        self.task,self.manifest,self.path=prepare(self.task,{'dataset:records':table},self.root/'data')
    def tearDown(self):self.evidence.cleanup()

    def test_incremental_source_projection_and_integrity_io_are_observed(self):
        source=DataCatalog(self.path).bind(self.task).resolve('dataset:records');events=[]
        with patch.object(source,'file',side_effect=AssertionError('WHOLE_FILE_BUFFER_FORBIDDEN')):
            batches=list(source.batches(['g','v'],on_event=lambda k,v:events.append((k,v))))
        self.assertEqual(sum(b.num_rows for b in batches),4097);self.assertLessEqual(max(b.num_rows for b in batches),1024)
        self.assertTrue(all(b.schema.names==['g','v'] for b in batches))
        self.assertEqual(sum(v['bytes'] for k,v in events if k=='source_integrity_read'),sum(f['bytes'] for f in self.manifest['sources'][0]['physical_files']))
        self.assertLess(sum(b.nbytes for b in batches),sum(f['bytes'] for f in self.manifest['sources'][0]['physical_files'])//10)

    def test_schema_data_and_public_binding_faults(self):
        for mutation in ['revision','schema_hash','content_sha256']:
            catalog=DataCatalog(self.path);catalog.sources['dataset:records'].entry[mutation]='wrong'
            with self.assertRaisesRegex(ValueError,'DATA_PUBLIC_BINDING'):catalog.bind(self.task)
        bad=self.pa.Table.from_pylist([{'g':True,'v':1,'wide':'x'}])
        with self.assertRaisesRegex(ValueError,'DATA_SCHEMA_TYPE'):prepare(self.task,{'dataset:records':bad},self.root/'wrong-type')
        bad=self.pa.Table.from_pylist([{'g':None,'v':1,'wide':'x'}],schema=arrow_schema({'kind':'Table','schema':self.schema}))
        with self.assertRaisesRegex(ValueError,'DATA_NON_NULLABLE'):prepare(self.task,{'dataset:records':bad},self.root/'wrong-null')

    def test_pipeline_never_collects_source_or_aggregate_input(self):
        native=Native(os.environ['RCWG_FULL_BUILD'],'diagnostic');catalog=DataCatalog(self.path).bind(self.task)
        source=catalog.resolve('dataset:records');plan=Plan(self.task['task_id']);rows=plan.scan('records',{'g':'Int64','v':'Int64'})
        rows=plan.aggregate('group',rows,['g'],'sum','v','total');plan=plan.end(rows)
        compiled=FullCompiler().compile(self.task,plan);self.assertEqual(compiled['status'],'IR_VALIDATED',compiled)
        journal=Journal(self.root/'events.jsonl',self.id());store=ArtifactStore(self.root/'artifacts',self.id(),journal);backend=Backend(native,store,self.task)
        externals={alias:store.register(source,meta['type'],'source') for alias,meta in compiled['typed_graph']['input_bindings'].items()}
        scheduler=Scheduler(compiled,self.task,externals,backend,journal)
        try:
            with patch.object(source,'table',side_effect=AssertionError('SOURCE_COLLECT_FORBIDDEN')),patch.object(backend,'table',side_effect=AssertionError('AGGREGATE_COLLECT_FORBIDDEN')):
                actual=asyncio.run(asyncio.wait_for(scheduler.run(),20))
            expected=[{'g':g,'total':sum(r['v'] for r in self.rows if r['g']==g)} for g in range(7)]
            self.assertEqual(actual,expected)
            self.assertTrue(all(s.peak_batches<=2 for s in scheduler.live_streams))
            events=verify_journal(journal.path);consumed=[e for e in events if e['event_kind']=='aggregate_batch_consumed']
            self.assertEqual(sum(e['payload']['rows'] for e in consumed),4097);self.assertGreater(len(consumed),1)
        finally:journal.close()

    def test_disk_sink_writes_each_batch_without_retaining_payload(self):
        from rcwg_full.runtime.disk_sink import DiskSink
        schema=arrow_schema({'kind':'Table','schema':self.schema})
        for format in ['arrow_ipc','parquet']:
            journal=Journal(self.root/(format+'-events.jsonl'),format);store=ArtifactStore(self.root/(format+'-artifacts'),format,journal)
            try:
                sink=DiskSink(store,{'kind':'Table','schema':self.schema},schema,'disk',format)
                for batch in DataCatalog(self.path).bind(self.task).resolve('dataset:records').batches():sink.append(batch)
                item=sink.finish();self.assertIsNone(item.value)
                self.assertTrue(all(store.buffers[k]['storage_kind']=='disk' for k in item.buffer_ids))
                self.assertEqual(store.load(item).to_pylist(),self.rows)
                self.assertEqual(item.logical_rows,len(self.rows))
                with self.assertRaisesRegex(ValueError,'DISK_SINK_CLOSED'):sink.finish()
            finally:journal.close()

    def test_four_mib_target_single_row_oversize_and_object_cap(self):
        from rcwg_full.runtime.batching import arrow_batches
        table=self.pa.Table.from_pylist([{'v':'a'*(2*1024*1024)},{'v':'b'*(3*1024*1024)},{'v':'c'*(5*1024*1024)},{'v':'d'}])
        batches=list(arrow_batches(table));self.assertEqual(sum(b.num_rows for b in batches),4)
        self.assertTrue(all(b.nbytes<=4*1024**2 or b.num_rows==1 for b in batches))
        self.assertEqual(self.pa.Table.from_batches(batches).to_pylist(),table.to_pylist())
        with self.assertRaisesRegex(ValueError,'OBJECT_LIMIT_EXCEEDED'):list(arrow_batches(table,max_object_bytes=4*1024**2))
