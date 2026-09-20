"""Typed kernel differential cases, separate from full WorkIR admission evidence."""
from pathlib import Path
from copy import deepcopy
import json
import os
import unittest
from rcwg_exec.kernels import RowFrame,evaluate,select_topk
from rcwg_native.evidence import canonical,sha,write,read
from rcwg_native.oracle import naive_top,compare
from rcwg_native.supervisor import execute

OUTPUT=None;BUILD=None;EVIDENCE=[]
SCHEMA={'id':{'kind':'Int64','nullable':False},'x':{'kind':'Float64','nullable':True},'s':{'kind':'Utf8','nullable':True},'b':{'kind':'Bool','nullable':True}}
ROWS=[{'id':2**63-1,'x':None,'s':'😀','b':None},{'id':-2**63,'x':1.1,'s':'中文','b':False},{'id':5,'x':1.1,'s':'a','b':True},{'id':5,'x':1.1,'s':'aa','b':True},{'id':0,'x':-0.0,'s':None,'b':None}]

class ValueTests(unittest.TestCase):
    def setUp(self):self.base=OUTPUT/self._testMethodName;self.base.mkdir(mode=0o700);self.calls=0
    def run_case(self,*,rows=None,schema=None,predicate=None,keys=None,k=10,raw=None,expected_code=None):
        rows=deepcopy(ROWS if rows is None else rows);schema=deepcopy(SCHEMA if schema is None else schema)
        predicate=predicate or {'literal':True};keys=keys or [{'field':'id','direction':'asc'}]
        payload=raw if raw is not None else b''.join(canonical(row)+b'\n' for row in rows)
        path=self.base/('data'+str(self.calls)+'.jsonl');write(path,payload)
        answers=[]
        for top,filt in [('full_sort','scalar'),('streaming_heap','vectorized')]:
            self.calls+=1
            nodes=[{'id':'scan','operator':'scan','implementation':'sequential','params':{'columns':list(schema)}},
                   {'id':'filter','operator':'filter','implementation':filt,'params':{'predicate':predicate},'batch_rows':2},
                   {'id':'top','operator':'top_k','implementation':top,'params':{'k':k,'keys':keys}},
                   {'id':'project','operator':'project','implementation':'copy','params':{'columns':list(schema)}},
                   {'id':'emit','operator':'emit','implementation':'json_artifact','params':{}}]
            req={'revision':'NATIVE001_REQUEST_V1','run_id':('v_'+self._testMethodName+'_'+str(self.calls))[-79:],'mode':'diagnostic','source':{'path':str(path),'schema':schema,'sha256':sha(payload),'row_count':len(rows)},'nodes':nodes,'max_materialized_rows':1000}
            expect=None
            if expected_code is None:
                expect=naive_top(rows,eligible=lambda r:evaluate(predicate,r) is True,k=k,keys=keys,fields=list(schema))
                reference=select_topk([RowFrame(r,i) for i,r in enumerate(rows) if evaluate(predicate,r) is True],k,keys,top,{},lambda:None)
                self.assertEqual(canonical(expect),canonical([dict(r.values) for r in reference]))
            out=self.base/('run'+str(self.calls))
            result=execute(req,build=BUILD,output=out,context={'case_id':self.id(),'scope':'TYPED_KERNEL_WIRE_DIFFERENTIAL','data_sha256':sha(payload),'expected_sha256':None if expect is None else sha(canonical(expect))},verify=None if expect is None else lambda d:compare(read(d/'result.json'),expect))
            EVIDENCE.append({'test_id':self.id(),'run_directory':str(out.relative_to(OUTPUT)),'result':result,'scope':'TYPED_KERNEL_WIRE_DIFFERENTIAL'})
            if expected_code is not None:self.assertEqual(result['failure']['code'],expected_code,result)
            else:
                self.assertEqual(result['terminal_status'],'COMPLETED',result);self.assertEqual(result['verification']['status'],'PASS',result);answers.append(read(out/'result.json'))
        if answers:self.assertEqual(canonical(answers[0]),canonical(answers[1]))
    def test_nullable_three_valued_logic(self):
        for op in ['and','or']:
            for literal in [None,True,False]:self.run_case(predicate={'op':op,'args':[{'field':'b'},{'literal':literal}]})
    def test_not_is_null_and_null_membership(self):
        for pred in [{'op':'not','arg':{'field':'b'}},{'op':'is_null','arg':{'field':'x'}},{'op':'in','left':{'field':'id'},'right':{'literal':[5,None]}},{'op':'in','left':{'field':'x'},'right':{'literal':[]}}]:self.run_case(predicate=pred)
    def test_utf8_count_is_codepoints(self):self.run_case(predicate={'op':'eq','left':{'op':'count','arg':{'field':'s'}},'right':{'literal':1}})
    def test_exact_int64_and_duplicate_ordinal_ties(self):self.run_case(keys=[{'field':'id','direction':'desc'}])
    def test_null_order_both_directions(self):
        for direction in ['asc','desc']:
            for nulls in ['first','last']:self.run_case(keys=[{'field':'x','direction':direction,'nulls':nulls}])
    def test_unicode_and_prefix_order(self):
        for direction in ['asc','desc']:self.run_case(keys=[{'field':'s','direction':direction,'nulls':'last'}])
    def test_null_filter_excludes_unknown(self):self.run_case(predicate={'op':'gt','left':{'field':'x'},'right':{'literal':0.0}})
    def test_all_filtered_still_drains(self):self.run_case(predicate={'literal':False},k=0)
    def test_int64_arithmetic_overflow(self):
        for op,value in [('add',1),('sub',-1),('mul',2)]:
            self.run_case(rows=[ROWS[0]],predicate={'op':'gt','left':{'op':op,'left':{'field':'id'},'right':{'literal':value}},'right':{'literal':0}},expected_code='ARITHMETIC_OVERFLOW')
    def test_min_int_negation_overflow(self):self.run_case(rows=[ROWS[1]],predicate={'op':'gt','left':{'op':'mul','left':{'field':'id'},'right':{'literal':-1}},'right':{'literal':0}},expected_code='ARITHMETIC_OVERFLOW')
    def test_large_int_division_explicit_profile_gap(self):self.run_case(rows=[ROWS[0]],predicate={'op':'gt','left':{'op':'div','left':{'field':'id'},'right':{'literal':3}},'right':{'literal':0}},expected_code='UNSUPPORTED_IMPLEMENTATION')
    def test_no_short_circuit_suppresses_arithmetic_error(self):
        for op,first in [('and',False),('or',True)]:self.run_case(rows=[ROWS[2]],predicate={'op':op,'args':[{'literal':first},{'op':'gt','left':{'op':'div','left':{'literal':1},'right':{'literal':0}},'right':{'literal':0}}]},expected_code='DIVISION_BY_ZERO')
    def test_finite_float_overflow(self):self.run_case(predicate={'op':'gt','left':{'op':'mul','left':{'literal':1e308},'right':{'literal':1e308}},'right':{'literal':0.0}},expected_code='ARITHMETIC_OVERFLOW')
    def test_bad_utf8_duplicate_key_nonfinite_and_type(self):
        for raw,code in [(b'{"a":1,"a":2}\n','DATA_DUPLICATE_KEY'),(b'"\xff"\n','DATA_UTF8_INVALID'),(b'1e999\n','DATA_NONFINITE'),(b'{"id":true,"x":1.0,"s":"a","b":true}\n','DATA_TYPE_MISMATCH')]:self.run_case(rows=[ROWS[0]],raw=raw,expected_code=code)
    def test_projection_ownership_real_buffer_witness(self):
        self.run_case(rows=[ROWS[2]])
        result=EVIDENCE[-1]['result'];w=result['worker']['ownership_witness']
        scan=[v for v in w if v['node_id']=='scan'];copy=[v for v in w if v['node_id']=='project']
        self.assertTrue(scan);self.assertTrue(copy);self.assertEqual(scan[0]['source_buffer_id'],scan[0]['result_buffer_id']);self.assertNotEqual(copy[0]['source_buffer_id'],copy[0]['result_buffer_id'])
