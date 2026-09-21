"""Calendar and offset invariants are calculated independently with datetime."""
import json
import os
import unittest
from datetime import date,datetime,timezone
from rcwg_full.evidence import canonical
from rcwg_full.runtime.native import Native
from rcwg_full.runtime.values import arrow_rows,arrow_schema,native_temporal,temporal_json,validate
from test_native import expr,literal
import test_runtime as runtime_tests
node=runtime_tests.node


class TemporalValues(unittest.TestCase):
    def test_native_scalars_preserve_declared_type_and_timezone_equivalence(self):
        for value in ['1969-12-31T19:00:00-05:00','1970-01-01T08:00:00+08:00','1970-01-01T00:00:00Z']:
            self.assertEqual(native_temporal(value,'Timestamp'),{'$timestamp_us':0})
        self.assertEqual(native_temporal(date(1969,12,31),'Date'),{'$date32':-1})
        self.assertEqual(native_temporal('1970-01-01','Utf8'),'1970-01-01')
        self.assertEqual(temporal_json({'a':[{'$date32':-1},{'$timestamp_us':-1}]}),{'a':['1969-12-31','1969-12-31T23:59:59.999999Z']})
        with self.assertRaisesRegex(ValueError,'TIMESTAMP_TIMEZONE'):native_temporal('2020-01-01T00:00:00','Timestamp')

    def test_canonical_is_json_and_rejects_naive_datetimes(self):
        self.assertEqual(json.loads(canonical({'d':date(2000,2,29),'t':datetime(1970,1,1,tzinfo=timezone.utc)})),{'d':'2000-02-29','t':'1970-01-01T00:00:00.000000Z'})
        with self.assertRaisesRegex(ValueError,'TIMESTAMP_TIMEZONE'):canonical(datetime(2000,1,1))
        validate('2000-02-29','Date',None)


class TemporalNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        cls.pa=pa;cls.native=Native(os.environ['RCWG_FULL_BUILD'],'diagnostic')

    def typed_table(self,rows,schema):
        typ={'kind':'Table','schema':schema}
        return self.pa.Table.from_pylist(arrow_rows(rows,typ),schema=arrow_schema(typ))

    def test_filter_both_algorithms_calendar_and_offset_literal(self):
        rows=[{'id':0,'d':'1999-12-31','t':'2000-01-01T01:00:00+02:00'},
              {'id':1,'d':'2000-02-29','t':'1999-12-31T23:00:00Z'},
              {'id':2,'d':None,'t':None},
              {'id':3,'d':'2000-03-01','t':'2000-01-01T00:00:00Z'}]
        schema={'id':'Int64','d':{'kind':'Nullable','item':{'kind':'Date'}},'t':{'kind':'Nullable','item':{'kind':'Timestamp'}}}
        table=self.typed_table(rows,schema)
        for impl in ['scalar','vectorized']:
            out,_=self.native.relational('filter',impl,table,{'predicate':expr('eq',{'field':'t'},literal('2000-01-01T07:00:00+08:00'))})
            self.assertEqual(out.column('id').to_pylist(),[0,1])
            out,_=self.native.relational('filter',impl,table,{'predicate':expr('le',{'field':'d'},literal('2000-02-29'))})
            self.assertEqual(out.column('id').to_pylist(),[0,1])

    def test_expression_temporal_context_does_not_coerce_utf8(self):
        ast=expr('eq',{'field':'t'},literal('2000-01-01T08:00:00+08:00'))
        self.assertTrue(self.native.expression(ast,{'t':'2000-01-01T00:00:00Z'},{'t':'Timestamp'}))
        self.assertFalse(self.native.expression(ast,{'t':'2000-01-01T00:00:00Z'},{'t':'Utf8'}))
        self.assertIsNone(self.native.expression(ast,{'t':None},{'t':{'kind':'Nullable','item':{'kind':'Timestamp'}}}))
        self.assertTrue(self.native.expression(expr('in',{'field':'d'},literal(['2000-01-01','2000-02-29',None])),{'d':'2000-02-29'},{'d':'Date'}))

    def test_join_date_and_timestamp_all_algorithms_preserve_values(self):
        left=self.typed_table([{'lid':1,'d':'2000-02-29','t':'2000-01-01T08:00:00+08:00'}],{'lid':'Int64','d':'Date','t':'Timestamp'})
        right=self.typed_table([{'rid':2,'d':'2000-02-29','t':'1999-12-31T19:00:00-05:00'}],{'rid':'Int64','d':'Date','t':'Timestamp'})
        for impl in ['hash','sort_merge','block_nested']:
            out,_=self.native.relational('join',impl,left,{'join_type':'inner','build_side':'right','keys':[{'left':'d','right':'d'},{'left':'t','right':'t'}]},right)
            self.assertEqual(out.num_rows,1);self.assertEqual(out.column('left.d').to_pylist(),[date(2000,2,29)])
            self.assertEqual(out.column('right.t').to_pylist(),[datetime(2000,1,1,tzinfo=timezone.utc)])

    def test_minmax_sort_topk_and_incremental_state(self):
        rows=[{'d':d,'t':t} for d,t in [('2000-02-29','2000-01-01T00:00:00Z'),('1969-12-31','1969-12-31T23:59:59.999999Z'),('2100-03-01','2000-01-01T08:00:00+08:00')]]
        table=self.typed_table(rows,{'d':'Date','t':'Timestamp'});spec={'group_by':[],'aggregates':[{'function':'min','field':'d','as':'d'},{'function':'max','field':'t','as':'t'}]}
        expected=[{'d':date(1969,12,31),'t':datetime(2000,1,1,tzinfo=timezone.utc)}]
        for impl in ['hash_group','sorted_group']:
            out,_=self.native.relational('aggregate',impl,table,spec);self.assertEqual(out.to_pylist(),expected)
        state=self.native.aggregate_begin(table.schema,spec)
        for batch in table.to_batches(max_chunksize=1):self.native.aggregate_consume(state,self.pa.Table.from_batches([batch]))
        out,_=self.native.aggregate_finish(state);self.assertEqual(out.to_pylist(),expected)
        for impl in ['full_sort','streaming_heap']:
            out,_=self.native.relational('top_k',impl,table,{'k':2,'keys':[{'field':'t','direction':'asc'}]})
            self.assertEqual(out.column('d').to_pylist(),[date(1969,12,31),date(2000,2,29)])

    def test_projection_nested_temporals_and_sets(self):
        nested={'kind':'List','max_length':4,'item':{'kind':'Record','schema':{'d':{'kind':'Date'},'t':{'kind':'Timestamp'}}}}
        table=self.typed_table([{'values':[{'d':'2000-02-29','t':'2000-01-01T08:00:00+08:00'}]}],{'values':nested})
        for impl in ['copy','column_view']:
            out,_=self.native.relational('project',impl,table,{'expressions':{'copy':{'field':'values'}},'_field_types':{'copy':nested}})
            self.assertEqual(out.column('copy').to_pylist(),table.column('values').to_pylist())
        for impl in ['hash','sorted_merge']:
            out,_=self.native.set_op(['2000-01-01T08:00:00+08:00'],['2000-01-01T00:00:00Z'],'intersection',impl,'Timestamp')
            self.assertEqual(out,['2000-01-01T00:00:00.000000Z'])


class TemporalRuntime(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(runtime_tests.Runtime.setUpClass.__func__)
    setUp=runtime_tests.Runtime.setUp
    tearDown=runtime_tests.Runtime.tearDown
    execute=runtime_tests.Runtime.execute

    async def test_scan_map_disk_roundtrip_and_json_output(self):
        import pyarrow as pa
        schema={'d':'Date','t':'Timestamp'};rows=[{'d':'2000-02-29','t':'2000-01-01T08:00:00+08:00'}]
        typ={'kind':'Table','schema':schema}
        self.task['datasets']=[{'id':'dataset:time','kind':'table','revision':'tiny-1','schema_source':'engineering','schema':schema,'stats':{'row_count':1}}]
        self.task['output_contract']={'id':'result','type':'records','mode':'exact','fields':['d','t'],'schema':schema}
        scan=node('scan','scan','sequential',{'source':'$input.rows'},{'columns':['d','t']},{'rows':'Stream[Record]'})
        step=node('step','project','column_view',{'rows':'$bound.row'},{'representation':'record','expressions':{'d':{'field':'d'},'t':{'field':'t'}}},{'rows':'Record'})
        mapper=node('map','map','bounded_map',{'rows':'scan.rows'},{},{'rows':'Stream[Record]'},regions={'body':{'bindings':{'row':'$item'},'nodes':[step],'yield':{'rows':'step.rows'}}})
        disk=node('disk','materialize','disk',{'rows':'map.rows'},{'format':'arrow_ipc'},{'rows':'Table'},storage='disk')
        plan={'ir_version':'1.0','task_id':self.task['task_id'],'external_inputs':{'rows':'dataset:time'},'nodes':[scan,mapper,disk],'result':'disk.rows'}
        result=await self.execute(plan,{'dataset:time':pa.Table.from_pylist(arrow_rows(rows,typ),schema=arrow_schema(typ))})
        self.assertEqual(result,[{'d':'2000-02-29','t':'2000-01-01T00:00:00.000000Z'}])
