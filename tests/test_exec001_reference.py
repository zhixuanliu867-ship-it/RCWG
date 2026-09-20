"""Reference-runtime tests. Timing observations here are not benchmark results."""
from copy import deepcopy
from functools import cmp_to_key
import hashlib
import json
import math
import os
from pathlib import Path
import random
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch

from rcwg_spec.common import canonical,digest
from rcwg_spec.compiler import validate_workflow
from rcwg_spec.binding import ExpectedManifest, validate_evidence
from rcwg_exec.kernels import (RowFrame,ProjectedRow,evaluate,filter_rows,filter_batch_rows,
                              project_rows,select_topk,Ordering)
from rcwg_exec.datasets import FileRegistry,parse_line
from rcwg_exec.errors import ExecFault
from rcwg_exec.store import PrivateStore
from rcwg_exec.demo import prepare_fixture,run_demo
from rcwg_exec.runner import preflight,run_f1_reference
from rcwg_exec.verifier import verify_f1

KEYS=[{'field':'score','direction':'desc'},{'field':'id','direction':'asc'}]
ELIGIBLE={'op':'eq','left':{'field':'eligible'},'right':{'literal':True}}
def frame(i,s,eligible=True):return RowFrame(MappingProxyType({'id':i,'score':float(s),'eligible':eligible}),i)
def lit(x):return {'literal':x}
def binary(op,a,b):return {'op':op,'left':lit(a),'right':lit(b)}
def material(rows):return [dict(f.values) for f in rows]
def noop():pass

class KernelTests(unittest.TestCase):
    def test_full_sort_really_materializes(self):
        c={};out=select_topk([frame(2,1),frame(1,3),frame(3,2)],1,KEYS,'full_sort',c,noop)
        self.assertEqual(out[0].values['id'],1);self.assertEqual(c['candidate_frames_peak'],3);self.assertEqual(c['full_sort_calls'],1)
    def test_heap_bound_and_dispatch(self):
        c={};out=select_topk((frame(i,i) for i in range(100)),3,KEYS,'streaming_heap',c,noop)
        self.assertEqual([r.values['id'] for r in out],[99,98,97]);self.assertEqual(c['candidate_frames_peak'],3)
        self.assertEqual(c['heap_selection_calls'],1);self.assertNotIn('full_sort_calls',c)
    def test_empty(self):
        for impl in ['full_sort','streaming_heap']:
            self.assertEqual(select_topk([],20,KEYS,impl,{},noop),[])
    def test_k_zero_still_drains(self):
        for impl in ['full_sort','streaming_heap']:
            seen=[]
            def rows():
                for i in range(9):seen.append(i);yield frame(i,i)
            self.assertEqual(select_topk(rows(),0,KEYS,impl,{},noop),[]);self.assertEqual(len(seen),9)
    def test_fewer_than_k(self):
        for impl in ['full_sort','streaming_heap']:
            self.assertEqual([r.values['id'] for r in select_topk([frame(2,9),frame(1,8)],10,KEYS,impl,{},noop)],[2,1])
    def test_tie_id(self):
        for impl in ['full_sort','streaming_heap']:
            out=select_topk([frame(3,9),frame(1,9),frame(2,9)],2,KEYS,impl,{},noop)
            self.assertEqual([r.values['id'] for r in out],[1,2])
    def test_equal_all_keys_uses_ordinal(self):
        rows=[RowFrame({'id':1,'score':1.0},i) for i in [2,0,1]]
        for impl in ['full_sort','streaming_heap']:
            self.assertEqual([r.ordinal for r in select_topk(rows,2,KEYS,impl,{},noop)],[0,1])
    def test_order_asc(self):
        out=select_topk([frame(i,i) for i in range(5)],2,[{'field':'score','direction':'asc'}],'streaming_heap',{},noop)
        self.assertEqual([r.values['id'] for r in out],[0,1])
    def test_nulls_last_desc(self):
        rows=[RowFrame({'id':0,'score':None},0),frame(1,2),frame(2,3)]
        keys=[{'field':'score','direction':'desc','nulls':'last'}]
        self.assertEqual([r.values['id'] for r in select_topk(rows,3,keys,'streaming_heap',{},noop)],[2,1,0])
    def test_nulls_first_asc(self):
        rows=[RowFrame({'id':0,'score':None},0),frame(1,2),frame(2,3)]
        keys=[{'field':'score','direction':'asc','nulls':'first'}]
        self.assertEqual([r.values['id'] for r in select_topk(rows,3,keys,'full_sort',{},noop)],[0,1,2])
    def test_property_against_independent_key(self):
        for seed in range(30):
            rng=random.Random(seed);rows=[frame(i,rng.randrange(-3,4)) for i in rng.sample(range(31),31)]
            for k in [0,1,7,31,40]:
                want=sorted(material(rows),key=lambda r:(-r['score'],r['id']))[:k]
                for impl in ['full_sort','streaming_heap']:
                    with self.subTest(seed=seed,k=k,impl=impl):self.assertEqual(material(select_topk(iter(rows),k,KEYS,impl,{},noop)),want)
    def test_materialization_cap_not_oom(self):
        with self.assertRaises(ExecFault) as cm:select_topk([frame(i,i) for i in range(8)],3,KEYS,'full_sort',{},noop,max_materialized_rows=2)
        self.assertEqual(cm.exception.attribution,'facility');self.assertEqual(cm.exception.code,'REFERENCE_MATERIALIZATION_CAP')
    def test_unknown_dispatch(self):
        with self.assertRaises(ExecFault):select_topk([],1,KEYS,'auto',{},noop)
    def test_scalar_filter(self):
        self.assertEqual([r.values['id'] for r in filter_rows([frame(0,1,False),frame(1,2)],ELIGIBLE,{},noop)],[1])
    def test_bounded_batch_filter(self):
        c={};rows=[frame(i,i,bool(i%2)) for i in range(33)]
        out=list(filter_batch_rows(rows,ELIGIBLE,c,noop,batch_rows=7))
        self.assertEqual(len(out),16);self.assertEqual(c['vector_batches'],5);self.assertEqual(c['batch_frames_peak'],7)
    def test_projection_is_real_view(self):
        source=frame(1,9);c={};out=list(project_rows([source],['id'],'column_view',c,noop))[0]
        self.assertIs(out.values.base,source.values);self.assertEqual(list(out.values),['id'])
        with self.assertRaises(KeyError):out.values['score']
        with self.assertRaises(TypeError):out.values['id']=8
    def test_projection_copy_distinct(self):
        source=frame(1,9);out=list(project_rows([source],['id'],'copy',{},noop))[0]
        self.assertIsNot(out.values,source.values);self.assertEqual(dict(out.values),{'id':1})
    def test_and_unknown_false(self):self.assertIs(evaluate({'op':'and','args':[lit(None),lit(False)]},{}),False)
    def test_or_unknown_true(self):self.assertIs(evaluate({'op':'or','args':[lit(None),lit(True)]},{}),True)
    def test_and_true_unknown(self):self.assertIsNone(evaluate({'op':'and','args':[lit(None),lit(True)]},{}))
    def test_not_null(self):self.assertIsNone(evaluate({'op':'not','arg':lit(None)},{}))
    def test_null_equality_unknown(self):self.assertIsNone(evaluate(binary('eq',None,None),{}))
    def test_is_null(self):self.assertTrue(evaluate({'op':'is_null','arg':lit(None)},{}))
    def test_membership_null_and_empty(self):self.assertFalse(evaluate(binary('in',None,[]),{}))
    def test_membership_true_dominates_null(self):self.assertTrue(evaluate(binary('in',1,[None,1]),{}))
    def test_membership_absent_with_null(self):self.assertIsNone(evaluate(binary('in',1,[None,2]),{}))
    def test_numeric_arithmetic(self):
        for op,want in [('add',7),('sub',3),('mul',10),('div',2.5)]:self.assertEqual(evaluate(binary(op,5,2),{}),want)
    def test_integer_overflow(self):
        with self.assertRaises(ExecFault) as c:evaluate(binary('add',2**63-1,1),{})
        self.assertEqual(c.exception.attribution,'plan')
    def test_float_overflow(self):
        with self.assertRaises(ExecFault):evaluate(binary('mul',1e308,1e308),{})
    def test_zero_division(self):
        with self.assertRaises(ExecFault):evaluate(binary('div',1,0),{})
    def test_count(self):self.assertEqual(evaluate({'op':'count','arg':lit([1,2,3])},{}),3)
    def test_eager_junction_records_arithmetic_error(self):
        with self.assertRaises(ExecFault):evaluate({'op':'and','args':[lit(False),binary('div',1,0)]},{})

class SourceAndStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,self.data=prepare_fixture(self.root/'fixture',n=9,k=2)
    def tearDown(self):self.tmp.cleanup()
    def registry(self):return FileRegistry(self.task,{self.task['datasets'][0]['id']:self.data},allowed_root=self.root)
    def test_actual_file_hash_registration(self):self.assertEqual(self.registry().manifest()[0]['content_sha256'],hashlib.sha256(self.data.read_bytes()).hexdigest())
    def test_bad_file_hash(self):
        self.data.write_bytes(b'{}\n')
        with self.assertRaises(ExecFault):self.registry()
    def test_symlink_rejected(self):
        symlink=self.root/'link';symlink.symlink_to(self.data)
        with self.assertRaises(ExecFault):FileRegistry(self.task,{self.task['datasets'][0]['id']:symlink},allowed_root=self.root)
    def test_outside_root_rejected(self):
        with self.assertRaises(ExecFault):FileRegistry(self.task,{self.task['datasets'][0]['id']:self.data},allowed_root=self.root/'fixture'/'..'/'not-root')
    def test_private_store_exclusive(self):
        store=PrivateStore(self.root/'out');store.write_json('report.json',{'a':1})
        with self.assertRaises(FileExistsError):store.write_json('report.json',{'a':2})
    def test_private_modes(self):
        store=PrivateStore(self.root/'out');store.write_json('report.json',{})
        self.assertEqual((store.root.stat().st_mode & 0o777),0o700);self.assertEqual(((store.root/'report.json').stat().st_mode&0o777),0o600)
    def test_output_path_injection(self):
        store=PrivateStore(self.root/'out')
        with self.assertRaises(ExecFault):store.write_json('../secret.json',{})
    def test_duplicate_json_key(self):
        with self.assertRaises(ExecFault):parse_line(b'{"id":1,"id":2}')
    def test_nonfinite_json(self):
        for raw in [b'{"x":NaN}',b'{"x":1e400}']:
            with self.assertRaises(ExecFault):parse_line(raw)
    def test_registry_unknown_identity(self):
        with self.assertRaises(ExecFault):FileRegistry(self.task,{'dataset:other':self.data},allowed_root=self.root)
    def test_row_count_mismatch(self):
        self.task['datasets'][0]['stats']['row_count']=99;registry=self.registry()
        with self.assertRaises(ExecFault) as cm:list(registry.frames(self.task['datasets'][0]['id'],{},noop))
        self.assertEqual(cm.exception.code,'DATA_ROW_COUNT_MISMATCH')
    def test_bool_is_not_int(self):
        rows=[{'id':True,'score':1.0,'eligible':True}];raw=canonical(rows[0])+b'\n';self.data.write_bytes(raw)
        self.task['datasets'][0]['data_sha256']=hashlib.sha256(raw).hexdigest();self.task['datasets'][0]['stats']['row_count']=1
        with self.assertRaises(ExecFault) as cm:list(self.registry().frames(self.task['datasets'][0]['id'],{},noop))
        self.assertEqual(cm.exception.code,'DATA_TYPE_MISMATCH')
    def test_source_changed_after_registration(self):
        reg=self.registry();row={'id':99,'score':1.0,'eligible':True}
        with self.data.open('ab') as f:f.write(canonical(row)+b'\n')
        with self.assertRaises(ExecFault) as cm:list(reg.frames(self.task['datasets'][0]['id'],{},noop))
        self.assertEqual(cm.exception.code,'DATA_CHANGED_DURING_RUN')

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,self.data=prepare_fixture(self.root/'fixture',n=39,k=4)
        self.reg=FileRegistry(self.task,{self.task['datasets'][0]['id']:self.data},allowed_root=self.root);self.i=0
    def tearDown(self):self.tmp.cleanup()
    def run_plan(self,plan=None,**kwargs):
        self.i+=1;self.out=self.root/f'run-{self.i}'
        return run_f1_reference(self.task,plan or self.plans['streaming_heap'],registry=self.reg,recipe=self.recipe,output=self.out,**kwargs)
    def test_actual_workflow_and_sealed_artifact(self):
        r=self.run_plan();self.assertEqual(r['terminal_status'],'COMPLETED');self.assertEqual(r['verification']['status'],'PASS')
        self.assertEqual(r['artifact']['content_sha256'],hashlib.sha256((self.out/'result.json').read_bytes()).hexdigest())
        self.assertEqual(set(r['node_states'].values()),{'COMPLETED'})
    def test_both_algorithms_exact_same_bytes(self):
        a=self.run_plan(self.plans['streaming_heap']);b=self.run_plan(self.plans['full_sort'])
        self.assertEqual(a['artifact']['content_sha256'],b['artifact']['content_sha256'])
        self.assertLess(a['measurements']['node_counters']['best']['candidate_frames_peak'],b['measurements']['node_counters']['best']['candidate_frames_peak'])
    def test_wrong_but_static_valid_is_verifier_failure(self):
        r=self.run_plan(self.plans['omitted_filter']);self.assertEqual(r['static_status'],'IR_VALIDATED')
        self.assertEqual(r['terminal_status'],'COMPLETED');self.assertEqual(r['verification']['status'],'FAIL')
    def test_no_fake_budget_success(self):
        r=self.run_plan();self.assertIsNone(r['measurements']['budget_within']);self.assertIsNone(r['measurements']['worker_peak_ram_bytes'])
        self.assertFalse(r['formal_ready']);self.assertEqual(r['real_model_requests'],0)
    def test_no_fake_physical_copy_measurement(self):
        r=self.run_plan();self.assertIsNone(r['measurements']['physical_copy_bytes']);self.assertEqual(r['measurements']['physical_copy_reason'],'NOT_INSTRUMENTED')
    def test_reference_view_changes_actual_output_fields(self):
        r=self.run_plan();rows=json.loads((self.out/'result.json').read_bytes())
        self.assertTrue(all(set(row)=={'id','score'} for row in rows));self.assertEqual(r['measurements']['node_counters']['fields']['row_views_created'],4)
    def test_copy_project_actual_dispatch(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][3]['implementation']='copy';p['nodes'][3]['storage']='memory'
        r=self.run_plan(p);self.assertEqual(r['verification']['status'],'PASS');self.assertEqual(r['measurements']['node_counters']['fields']['row_mappings_copied'],4)
    def test_scalar_filter_actual_dispatch(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][1]['implementation']='scalar'
        r=self.run_plan(p);self.assertEqual(r['verification']['status'],'PASS');self.assertNotIn('vector_batches',r['measurements']['node_counters']['keep'])
    def test_vector_filter_declared_batch_rows(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][1]['resources']={'batch_rows':5}
        r=self.run_plan(p);self.assertEqual(r['measurements']['node_counters']['keep']['batch_frames_peak'],5)
    def test_plan_array_order_not_rewritten(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'].reverse();before=canonical(p);r=self.run_plan(p)
        self.assertEqual(r['verification']['status'],'PASS');self.assertEqual((self.out/'plan.json').read_bytes(),before);self.assertEqual(canonical(p),before)
    def test_native_result_not_implicit_projection(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes']=p['nodes'][:-1];p['result']='fields.rows'
        r=self.run_plan(p);self.assertEqual(r['verification']['status'],'PASS');self.assertNotIn('answer',r['node_states'])
    def test_wrong_order_is_not_repaired(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][2]['params']['keys'][0]['direction']='asc'
        r=self.run_plan(p);self.assertEqual(r['verification']['status'],'FAIL')
    def test_after_is_facility_gap_not_model_failure(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][2]['after']=['keep']
        r=self.run_plan(p);self.assertEqual(r['status'],'RUNTIME_IMPLEMENTATION_GAP');self.assertFalse(r['execution_started'])
    def test_dead_node_not_pruned(self):
        p=deepcopy(self.plans['streaming_heap']);extra=deepcopy(p['nodes'][3]);extra['id']='unused';p['nodes'].append(extra)
        r=self.run_plan(p);self.assertEqual(r['status'],'RUNTIME_IMPLEMENTATION_GAP')
    def test_unsupported_algorithm_no_fallback(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][0]['implementation']='index_range'
        self.assertNotEqual(self.run_plan(p).get('status'),'EXEC001_REFERENCE_COMPLETE')
    def test_explicit_multiple_cpu_no_false_honor(self):
        self.task['resources']['cpu_slots']=4;self.recipe['task_input_hash']=digest(self.task)
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][2]['resources']={'cpu_slots':2}
        r=self.run_plan(p);self.assertEqual(r['status'],'RUNTIME_IMPLEMENTATION_GAP')
    def test_full_sort_protective_cap_facility_failure(self):
        r=self.run_plan(self.plans['full_sort'],max_materialized_rows=5)
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['failure']['code'],'REFERENCE_MATERIALIZATION_CAP')
        self.assertIsNone(r['measurements']['completed_wall_ns'])
    def test_dynamic_arithmetic_model_failure(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][1]['params']['predicate']={'op':'gt','left':binary('div',1.0,0.0),'right':lit(1.0)}
        r=self.run_plan(p);self.assertEqual(r['terminal_status'],'MODEL_FAILURE');self.assertEqual(r['failure']['code'],'DIVISION_BY_ZERO')
    def test_task_timeout_not_completed_latency(self):
        self.task['resources']['wall_timeout_s']=1e-9;self.recipe['task_input_hash']=digest(self.task)
        r=self.run_plan();self.assertEqual(r['terminal_status'],'TIMEOUT');self.assertIsNone(r['measurements']['completed_wall_ns']);self.assertEqual(r['verification']['status'],'UNKNOWN')
    def test_input_mutation_is_facility_failure(self):
        with self.data.open('ab') as f:f.write(canonical({'id':99,'score':1.0,'eligible':True})+b'\n')
        r=self.run_plan();self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['failure']['attribution'],'facility')
    def test_event_ledger_roundtrip(self):
        r=self.run_plan();manifest=ExpectedManifest((self.out/'expected_manifest.json').read_bytes())
        sidecar=json.loads((self.out/'sidecar.json').read_bytes());events=json.loads((self.out/'events.json').read_bytes())
        bound=validate_evidence(manifest,[sidecar],{sidecar['record_id']:events})
        self.assertEqual(bound['status'],'EVIDENCE_BOUND');self.assertEqual(bound['model_denominator'],1)
        self.assertEqual(events[0]['event'],'run_started');self.assertEqual(events[-1]['event'],'run_finished')
    def test_tampered_event_not_bound(self):
        self.run_plan();manifest=ExpectedManifest((self.out/'expected_manifest.json').read_bytes())
        sidecar=json.loads((self.out/'sidecar.json').read_bytes());events=json.loads((self.out/'events.json').read_bytes());events[1]['payload']['forged']=True
        with self.assertRaises(ValueError):validate_evidence(manifest,[sidecar],{sidecar['record_id']:events})
    def test_artifact_tamper_not_pass(self):
        r=self.run_plan();(self.out/'result.json').write_bytes(b'[]')
        v=verify_f1(task=self.task,recipe=self.recipe,data_path=self.data,artifact_path=self.out/'result.json',artifact_meta=r['artifact'])
        self.assertEqual(v['status'],'UNKNOWN');self.assertEqual(v['reason'],'ARTIFACT_HASH_MISMATCH')
    def test_verifier_recipe_does_not_follow_plan(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][2]['params']['k']=1
        r=self.run_plan(p);self.assertEqual(r['verification']['status'],'FAIL');self.assertEqual(r['verification']['expected_rows'],4)
    def test_verifier_scope_unrecognized(self):
        self.recipe['revision']='other';r=self.run_plan();self.assertEqual(r['verification']['status'],'UNKNOWN')
    def test_verifier_bool_metadata_rejected(self):
        r=self.run_plan();meta=deepcopy(r['artifact']);meta['serialized_bytes']=True
        v=verify_f1(task=self.task,recipe=self.recipe,data_path=self.data,artifact_path=self.out/'result.json',artifact_meta=meta)
        self.assertEqual(v['status'],'UNKNOWN')
    def test_input_task_registry_binding(self):
        self.task['datasets'][0]['data_sha256']='0'*64
        with self.assertRaises(ExecFault):self.run_plan()
    def test_real_byte_count(self):
        r=self.run_plan();self.assertEqual(r['measurements']['node_counters']['read']['source_read_bytes'],self.data.stat().st_size)
        self.assertEqual(r['measurements']['node_counters']['read']['rows_scanned'],39)
    def test_demo_three_cases(self):
        r=run_demo(self.root/'demo');self.assertEqual(r['status'],'EXEC001_REFERENCE_DEMO_PASS');self.assertEqual(len(r['cases']),3)
    def test_no_eligible(self):
        task,plans,recipe,data=prepare_fixture(self.root/'empty-fixture',k=2,rows=[{'id':1,'score':1.0,'eligible':False}])
        reg=FileRegistry(task,{task['datasets'][0]['id']:data},allowed_root=self.root)
        r=run_f1_reference(task,plans['streaming_heap'],registry=reg,recipe=recipe,output=self.root/'empty-run')
        self.assertEqual(r['verification']['status'],'PASS');self.assertEqual(r['artifact']['rows'],0)
    def test_zero_row_dataset(self):
        task,plans,recipe,data=prepare_fixture(self.root/'zero-fixture',k=2,rows=[])
        reg=FileRegistry(task,{task['datasets'][0]['id']:data},allowed_root=self.root)
        r=run_f1_reference(task,plans['full_sort'],registry=reg,recipe=recipe,output=self.root/'zero-run')
        self.assertEqual(r['verification']['status'],'PASS');self.assertEqual(r['artifact']['rows'],0)
    def test_k_zero_result_valid(self):
        self.task['output_contract']['k']=0;self.recipe['k']=0;self.recipe['task_input_hash']=digest(self.task)
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][2]['params']['k']=0
        r=self.run_plan(p);self.assertEqual(r['verification']['status'],'PASS');self.assertEqual(r['measurements']['node_counters']['read']['rows_scanned'],39)

if __name__=='__main__':unittest.main()
