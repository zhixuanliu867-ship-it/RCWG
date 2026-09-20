"""Actual native executions; collected only by the dedicated NATIVE gate."""
from copy import deepcopy
from pathlib import Path
import itertools
import json
import os
import random
import shutil
import subprocess
import unittest
from rcwg_exec.demo import prepare_fixture
from rcwg_exec.kernels import RowFrame,filter_rows,filter_batch_rows,project_rows,select_topk
from rcwg_native.adapter import lower
from rcwg_native.evidence import canonical,sha,write,read,reread
from rcwg_native.oracle import naive_top,compare
from rcwg_native.supervisor import execute,audit_worker,binary_binding

OUTPUT=None;BUILD=None
EVIDENCE=[]

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.base=OUTPUT/self._testMethodName;self.base.mkdir(mode=0o700)
        self.calls=0
    def fixture(self,n=129,k=7,seed=17,rows=None):
        return prepare_fixture(self.base/'fixture',n=n,k=k,seed=seed,rows=rows)
    def call(self,task,plan,data,recipe=None,**kwargs):
        self.calls+=1;ident=self._testMethodName+'_'+str(self.calls)
        ident=ident[-79:]
        ready=lower(task,plan,locations={task['datasets'][0]['id']:data},allowed_root=self.base,ident=ident,mode=kwargs.pop('mode','diagnostic'),max_rows=kwargs.pop('max_rows',100000))
        self.assertEqual(ready['status'],'NATIVE_PROFILE_READY',ready)
        rows=[json.loads(s) for s in data.read_bytes().splitlines()]
        expected=naive_top(rows,eligible=lambda row:row['eligible'] is True,k=task['output_contract']['k'],keys=[{'field':'score','direction':'desc'},{'field':'id','direction':'asc'}],fields=['id','score'])
        out=self.base/('run-'+str(self.calls))
        result=execute(ready['request'],build=BUILD,output=out,context={'case_id':self.id(),'task_sha256':sha(canonical(task)),'plan_sha256':sha(canonical(plan)),'data_sha256':task['datasets'][0]['data_sha256'],'recipe':recipe},verify=lambda d:compare(read(d/'result.json'),expected),**kwargs)
        EVIDENCE.append({'test_id':self.id(),'run_directory':str(out.relative_to(OUTPUT)), 'result':result})
        return result,out,ready
    def assert_success(self,result,out):
        self.assertEqual(result['terminal_status'],'COMPLETED',result)
        self.assertEqual(result['verification']['status'],'PASS',result)
        self.assertIsNone(result['budget_within']);self.assertFalse(result['formal_ready'])
        reread(out,result['seal_sha256'])
    def test_all_eight_branches(self):
        task,plans,recipe,data=self.fixture()
        seen=set();answers=set()
        for top,filt,proj in itertools.product(['full_sort','streaming_heap'],['scalar','vectorized'],['column_view','copy']):
            p=deepcopy(plans[top]);p['nodes'][1]['implementation']=filt;p['nodes'][3]['implementation']=proj
            if proj=='copy':p['nodes'][3]['storage']='memory'
            r,out,_=self.call(task,p,data,recipe);self.assert_success(r,out)
            seen.update((n['operator'],n['implementation']) for n in r['actual_dispatch']);answers.add(sha(canonical(read(out/'result.json'))))
            c=r['worker']['node_counters'];self.assertEqual(c['best']['output_rows'],7)
            if top=='streaming_heap':self.assertLessEqual(c['best']['candidate_frames_peak'],7);self.assertEqual(c['best']['heap_selection_calls'],1)
            else:self.assertGreater(c['best']['candidate_frames_peak'],7);self.assertEqual(c['best']['full_sort_calls'],1)
            if filt=='vectorized':self.assertLessEqual(c['keep']['batch_frames_peak'],128);self.assertGreater(c['keep']['vector_batches'],0)
            if proj=='copy':self.assertGreater(c['fields']['application_copy_bytes'],0);self.assertEqual(c['fields']['row_buffers_copied'],7)
            else:self.assertEqual(c['fields']['row_views_created'],7);self.assertNotIn('application_copy_bytes',c['fields'])
        self.assertEqual(len(seen),8);self.assertEqual(len(answers),1)
    def test_performance_has_same_answer_without_diagnostic_counters(self):
        t,p,r,d=self.fixture();result,out,_=self.call(t,p['streaming_heap'],d,r,mode='performance');self.assert_success(result,out)
        self.assertIsNone(result['worker']['node_counters']);self.assertIsNone(result['worker']['ownership_witness']);self.assertFalse(result['worker']['diagnostic_instrumentation'])
    def test_wrong_valid_plan_executes_and_fails_answer(self):
        t,p,r,d=self.fixture();result,out,ready=self.call(t,p['omitted_filter'],d,r)
        self.assertEqual(ready['compiler']['status'],'IR_VALIDATED');self.assertEqual(result['terminal_status'],'COMPLETED');self.assertEqual(result['verification']['status'],'FAIL')
    def test_node_rename_preserves_answer(self):
        t,p,r,d=self.fixture();p=deepcopy(p['streaming_heap']);names={n['id']:'renamed'+str(i) for i,n in enumerate(p['nodes'])}
        for n in p['nodes']:
            n['id']=names[n['id']]
            n['inputs']={port:('.'.join([names[ref.split('.')[0]],ref.split('.')[1]]) if not ref.startswith('$') else ref) for port,ref in n['inputs'].items()}
        n,port=p['result'].split('.');p['result']=names[n]+'.'+port
        result,out,_=self.call(t,p,d,r);self.assert_success(result,out)
    def test_valid_unsupported_after_is_facility_gap(self):
        t,p,r,d=self.fixture();p=deepcopy(p['streaming_heap']);p['nodes'][2]['after']=['read']
        ready=lower(t,p,locations={t['datasets'][0]['id']:d},allowed_root=self.base,ident='unsupported')
        self.assertEqual(ready['status'],'UNSUPPORTED_IMPLEMENTATION');self.assertEqual(ready['attribution'],'facility');self.assertFalse(ready['execution_started'])
    def test_materialization_cap_is_facility_not_oom(self):
        t,p,r,d=self.fixture(k=1);result,out,_=self.call(t,p['full_sort'],d,r,max_rows=4)
        self.assertEqual(result['terminal_status'],'INFRA_FAILURE');self.assertEqual(result['failure']['code'],'NATIVE_MATERIALIZATION_CAP');self.assertIsNone(result['measurements']['worker_peak_ram_bytes'])
    def test_division_zero_is_model_failure(self):
        t,p,r,d=self.fixture();p=deepcopy(p['streaming_heap']);p['nodes'][1]['params']['predicate']={'op':'gt','left':{'op':'div','left':{'field':'score'},'right':{'literal':0.0}},'right':{'literal':0.0}}
        result,_,_=self.call(t,p,d,r);self.assertEqual(result['terminal_status'],'MODEL_FAILURE');self.assertEqual(result['failure']['code'],'DIVISION_BY_ZERO')
    def test_source_hash_mismatch_inside_worker(self):
        t,p,r,d=self.fixture();t['datasets'][0]['data_sha256']='1'*64
        result,_,_=self.call(t,p['streaming_heap'],d,r);self.assertTrue(result['execution_started']);self.assertEqual(result['failure']['code'],'DATA_CHANGED_DURING_RUN')
    def test_exclusive_output_and_external_anchor(self):
        t,p,r,d=self.fixture();result,out,ready=self.call(t,p['streaming_heap'],d,r);self.assert_success(result,out)
        with self.assertRaises(FileExistsError):execute(ready['request'],build=BUILD,output=out,context={})
        with self.assertRaises(ValueError):reread(out,'0'*64)
    def test_truncated_events_rejected_by_independent_audit(self):
        t,p,r,d=self.fixture();result,out,_=self.call(t,p['streaming_heap'],d,r);self.assert_success(result,out)
        changed=self.base/'tampered';shutil.copytree(out,changed)
        path=changed/'worker.events.jsonl';path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(Exception,'TRUNCATED_EVENTS'):audit_worker(changed,read(changed/'expected_manifest.json'))
    def test_source_symlink_rejected_without_spawn(self):
        t,p,r,d=self.fixture();link=self.base/'alias.jsonl';link.symlink_to(d)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):lower(t,p['streaming_heap'],locations={t['datasets'][0]['id']:link},allowed_root=self.base,ident='link')
    def test_sha256_standard_vectors(self):
        binary,_=binary_binding(BUILD,'diagnostic')
        for raw in [b'',b'abc',b'a'*1000000,bytes(range(256))*17]:
            p=subprocess.run([str(binary),'--sha256'],input=raw,capture_output=True,timeout=10)
            self.assertEqual(p.returncode,0);self.assertEqual(p.stdout.decode().strip(),sha(raw))
    def test_json_utf8_numeric_roundtrip_and_invalid_inputs(self):
        binary,_=binary_binding(BUILD,'diagnostic')
        for obj in [None,True,False,-2**63,2**63-1,1.1,-0.0,1e300,'中文😀\x00\n',{'a':[None,False,1,1.0,'é']},'a'*65537]:
            p=subprocess.run([str(binary),'--json'],input=canonical(obj),capture_output=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(canonical(json.loads(p.stdout)),canonical(obj))
        for raw in [b'01',b'NaN',b'1e999',b'9223372036854775808',b'{"x":1,"x":2}',b'"\xff"',b'"\\ud800"',b'"\\udc00"',b'[1,]',b'1 2']:
            p=subprocess.run([str(binary),'--json'],input=raw,capture_output=True,timeout=10);self.assertNotEqual(p.returncode,0,raw)

def boundary_test(seed,n,k):
    def test(self):
        t,plans,recipe,data=self.fixture(n=n,k=k,seed=seed);outputs=[]
        for impl in ['full_sort','streaming_heap']:
            result,out,ready=self.call(t,plans[impl],data,recipe);self.assert_success(result,out);outputs.append(canonical(read(out/'result.json')))
            rows=[RowFrame(json.loads(line),i) for i,line in enumerate(data.read_bytes().splitlines())];c={};tick=lambda:None
            kept=filter_batch_rows(rows,plans[impl]['nodes'][1]['params']['predicate'],c,tick)
            selected=select_topk(kept,k,plans[impl]['nodes'][2]['params']['keys'],impl,c,tick)
            ref=list(project_rows(selected,['id','score'],'column_view',c,tick))
            self.assertEqual(outputs[-1],canonical([dict(row.values) for row in ref]))
        self.assertEqual(*outputs)
    return test

for seed,n,k in itertools.product([17,29,101],[0,1,7,129,257],[0,1,7,300]):
    setattr(NativeTests,f'test_boundary_seed{seed}_n{n}_k{k}',boundary_test(seed,n,k))
