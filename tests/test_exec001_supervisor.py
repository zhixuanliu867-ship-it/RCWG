"""Real Linux worker and persisted-evidence regressions, never timing benchmarks."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from rcwg_spec.common import canonical,digest
from rcwg_spec.compiler import validate_workflow
from rcwg_spec.binding import ExpectedManifest
from rcwg_exec.context import source_closure
from rcwg_exec.datasets import FileRegistry
from rcwg_exec.demo import prepare_fixture
from rcwg_exec.errors import ExecFault
from rcwg_exec.journal import Journal,read_journal,read_json,validate_node_events
from rcwg_exec.sealing import reopen_run,validate_artifact,validate_measurements
from rcwg_exec.supervisor import run_f1_supervised
from rcwg_exec.store import PrivateStore


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.index=0
        self.task,self.plans,self.recipe,self.data=prepare_fixture(self.root/'fixture',n=51,k=7)
    def tearDown(self):self.tmp.cleanup()
    def run_case(self,plan=None,**kwargs):
        self.index+=1;self.out=self.root/('run'+str(self.index))
        self.recipe['task_input_hash']=digest(self.task)
        reg=FileRegistry(self.task,{self.task['datasets'][0]['id']:self.data},allowed_root=self.root)
        result=run_f1_supervised(self.task,plan or self.plans['streaming_heap'],registry=reg,
            recipe=self.recipe,output=self.out,record_id='run'+str(self.index),**kwargs)
        if (self.out/'expected_manifest.json').exists():self.manifest=ExpectedManifest((self.out/'expected_manifest.json').read_bytes())
        return result
    def events(self):
        e=self.manifest.as_dict()['expected_records'][0]
        return read_journal(self.out/'worker.journal.jsonl',execution_key=e['execution_key'],
            manifest_hash=self.manifest.manifest_hash,origin='worker',allow_partial=True)['events']
    def test_distinct_worker_process_and_fresh_repeat(self):
        a=self.run_case();b=self.run_case(repeat_id='r1')
        self.assertEqual(a['verification']['status'],'PASS');self.assertEqual(b['verification']['status'],'PASS')
        self.assertNotEqual(a['worker_pid'],os.getpid());self.assertNotEqual(a['worker_pid'],b['worker_pid'])
        self.assertNotEqual(a['execution_key'],b['execution_key'])
        for p in (a['worker_pid'],b['worker_pid']):self.assertFalse(Path('/proc',str(p)).exists())
    def test_worker_does_not_inherit_credentials(self):
        with patch.dict(os.environ,{'EXEC_TEST_SECRET_CANARY':'private-canary','GOOGLE_APPLICATION_CREDENTIALS':'private-path'}):
            self.run_case()
        keys=self.events()[0]['payload']['environment_keys']
        self.assertNotIn('EXEC_TEST_SECRET_CANARY',keys);self.assertNotIn('GOOGLE_APPLICATION_CREDENTIALS',keys)
        self.assertEqual(set(keys),{'PATH','LANG','LC_ALL','PYTHONHASHSEED'})
    def test_manifest_written_before_spawn_and_exact_request(self):
        r=self.run_case();request=read_json(self.out/'worker_request.json')
        e=self.manifest.as_dict()['expected_records'][0]
        self.assertEqual(digest(request['plan']),e['plan_hash']);self.assertEqual(digest(request['task']),e['input_hash'])
        self.assertEqual(request['expected_manifest'],self.manifest.as_dict())
        self.assertLessEqual((self.out/'expected_manifest.json').stat().st_mtime_ns,(self.out/'worker.journal.jsonl').stat().st_mtime_ns)
        self.assertEqual(self.events()[0]['payload']['ppid'],r['parent_pid'])
    def test_real_hard_deadline_interrupts_uncooperative_worker(self):
        self.task['resources']['wall_timeout_s']=.4
        start=time.monotonic();r=self.run_case(_fault='stall')
        self.assertEqual(r['terminal_status'],'TIMEOUT');self.assertLess(time.monotonic()-start,5)
        self.assertIsNone(r['measurements']['completed_wall_ns']);self.assertGreater(r['measurements']['elapsed_ns'],0)
        self.assertFalse(Path('/proc',str(r['worker_pid'])).exists())
    def test_owner_cancel_is_unknown_not_model_failure(self):
        event=threading.Event();timer=threading.Timer(.4,event.set);timer.start()
        try:r=self.run_case(_fault='stall',cancel_event=event)
        finally:timer.cancel()
        self.assertEqual(r['terminal_status'],'UNKNOWN');self.assertEqual(r['failure']['code'],'OWNER_CANCELLED')
        self.assertIsNone(r['measurements']['worker_peak_ram_bytes'])
    def test_timeout_cleans_descendant_process_group(self):
        self.task['resources']['wall_timeout_s']=1
        r=self.run_case(_fault='spawn_descendant')
        children=[e['payload']['child_pid'] for e in self.events() if e['event']=='child_spawned']
        self.assertEqual(len(children),1);self.assertEqual(r['terminal_status'],'TIMEOUT')
        for p in [r['worker_pid'],*children]:self.assertFalse(Path('/proc',str(p)).exists())
    def test_crash_and_nonzero_are_facility_failures(self):
        for fault in ('crash','nonzero'):
            r=self.run_case(_fault=fault)
            self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertNotEqual(r['worker_exit_code'],0)
            self.assertEqual(r['verification']['status'],'UNKNOWN');self.assertTrue(self.events())
            self.assertIsNone(r['measurements']['process_cpu_ns'])
    def test_missing_worker_report_cannot_pass(self):
        r=self.run_case(_fault='drop_report');self.assertEqual(r['terminal_status'],'INFRA_FAILURE')
    def test_interrupted_artifact_stays_private_and_unsealed(self):
        r=self.run_case(_fault='partial_artifact')
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertIsNone(r['artifact'])
        self.assertEqual((self.out/'worker/.result.json.incomplete.part').read_bytes(),b'[{')
        self.assertFalse((self.out/'worker/result.json').exists())
    def test_partial_journal_prefix_retained_after_crash(self):
        r=self.run_case(_fault='partial_journal')
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertTrue(r['worker_partial_journal'])
        self.assertEqual(len(self.events()),1);self.assertEqual(r['reread']['status'],'EXEC001_RUN_REOPENED')
    def test_corrupt_complete_journal_is_facility_error(self):
        r=self.run_case(_fault='corrupt_journal')
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertIsNotNone(r['journal_error'])
        self.assertTrue((self.out/'worker.journal.jsonl').read_bytes().endswith(b'{}\n'))
    def test_worker_artifact_metadata_fault_detected(self):
        r=self.run_case(_fault='artifact_metadata')
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['failure']['code'],'ARTIFACT_CONTENT_MISMATCH')
    def test_worker_artifact_binding_fault_detected(self):
        r=self.run_case(_fault='artifact_binding')
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['failure']['code'],'ARTIFACT_EXECUTION_BINDING')
    def test_eight_branches_actually_dispatch(self):
        dispatch=set();artifacts=[]
        for variant in ('streaming_heap','full_sort'):
            p=deepcopy(self.plans[variant])
            for n in p['nodes']:
                if n['operator']=='filter':n['implementation']='scalar' if variant=='streaming_heap' else 'vectorized'
                if n['operator']=='project':
                    n['implementation']='column_view' if variant=='streaming_heap' else 'copy'
                    n['storage']='shared_ref' if variant=='streaming_heap' else 'memory'
            r=self.run_case(p);self.assertEqual(r['verification']['status'],'PASS');artifacts.append(r['artifact']['content_sha256'])
            for e in self.events():
                if e['event']=='node_started':dispatch.add((e['payload']['operator'],e['payload']['implementation']))
            c=r['measurements']['node_counters']['best']
            if variant=='streaming_heap':self.assertLessEqual(c['candidate_frames_peak'],7);self.assertEqual(c['heap_selection_calls'],1)
            else:self.assertGreater(c['candidate_frames_peak'],7);self.assertEqual(c['full_sort_calls'],1)
        self.assertEqual(len(dispatch),8);self.assertEqual(len(set(artifacts)),1)
    def test_wrong_choices_execute_unchanged_and_fail_semantics(self):
        variants=[self.plans['omitted_filter']]
        for choice in ('k','keys','projection'):
            p=deepcopy(self.plans['streaming_heap'])
            if choice=='k':p['nodes'][2]['params']['k']=1
            elif choice=='keys':p['nodes'][2]['params']['keys'][0]['direction']='asc'
            else:p['nodes'][3]['params']['columns']=['id','score','eligible']
            variants.append(p)
        for p in variants:
            self.assertEqual(validate_workflow(self.task,p)['status'],'IR_VALIDATED')
            r=self.run_case(p);self.assertEqual(r['terminal_status'],'COMPLETED');self.assertEqual(r['verification']['status'],'FAIL')
            self.assertEqual(read_json(self.out/'plan.json'),p)
    def test_dynamic_division_by_zero_is_model_failure(self):
        p=deepcopy(self.plans['streaming_heap'])
        p['nodes'][1]['params']['predicate']={'op':'gt','left':{'op':'div','left':{'field':'score'},'right':{'literal':0.0}},'right':{'literal':0.0}}
        r=self.run_case(p);self.assertEqual(r['terminal_status'],'MODEL_FAILURE');self.assertEqual(r['failure']['attribution'],'plan')
    def test_memory_protection_cap_is_facility_not_oom(self):
        r=self.run_case(self.plans['full_sort'],max_materialized_rows=2)
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['failure']['code'],'REFERENCE_MATERIALIZATION_CAP')
        self.assertIsNone(r['measurements']['worker_peak_ram_bytes'])
    def test_static_failure_and_profile_gap_do_not_spawn(self):
        p=deepcopy(self.plans['streaming_heap']);p['nodes'][2]['params']['k']=-1
        r=self.run_case(p);self.assertFalse(r['execution_started']);self.assertEqual(r['status'],'PLAN_INVALID')
        p=deepcopy(self.plans['full_sort']);p['nodes'][2]['storage']='disk'
        r=self.run_case(p);self.assertFalse(r['execution_started']);self.assertEqual(r['status'],'RUNTIME_IMPLEMENTATION_GAP')
    def test_verifier_recipe_stays_parent_side(self):
        self.run_case();request=read_json(self.out/'worker_request.json')
        self.assertNotIn('recipe',request);self.assertNotIn('verification_recipe',request)
        self.assertFalse(self.events()[0]['payload']['recipe_present'])
        self.assertNotIn('expected_result_sha256',json.dumps(request))
        self.assertIn('rcwg_exec/verifier.py',source_closure());self.assertIn('rcwg_exec/worker.py',source_closure())
    def test_private_output_modes_and_exclusive_run(self):
        self.run_case()
        for p in self.out.rglob('*'):
            self.assertEqual(p.stat().st_mode&0o077,0)
        with self.assertRaises(FileExistsError):PrivateStore(self.out)
    def test_reread_rejects_content_metadata_and_context_swaps(self):
        for name in ('worker/result.json','worker/artifact.json','worker/artifact_binding.json','plan.json','task.json','expected_manifest.json'):
            r=self.run_case();p=self.out/name;p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaises(ExecFault):reopen_run(self.out,manifest=self.manifest,seal_sha256=r['seal_sha256'])
    def test_reread_rejects_cross_execution_artifact_even_identical_result(self):
        self.run_case();first=(self.out/'worker/artifact_binding.json').read_bytes()
        r=self.run_case(repeat_id='r1');(self.out/'worker/artifact_binding.json').write_bytes(first)
        e=self.manifest.as_dict()['expected_records'][0]
        with self.assertRaises(ExecFault):validate_artifact(self.out/'worker',expected=e,task=self.task,
            plan=self.plans['streaming_heap'],compiled=validate_workflow(self.task,self.plans['streaming_heap']))
    def test_rewriting_seal_cannot_replace_external_anchor(self):
        r=self.run_case();p=self.out/'seal.json';v=read_json(p);v['files']={};p.write_bytes(canonical(v))
        with self.assertRaises(ExecFault):reopen_run(self.out,manifest=self.manifest,seal_sha256=r['seal_sha256'])
    def test_real_node_events_have_queue_ready_running_finished(self):
        self.run_case();states=validate_node_events(self.events(),self.plans['streaming_heap'],completed=True)
        self.assertEqual(len(states),5);self.assertEqual(set(states.values()),{'COMPLETED'})
    def test_node_event_drop_repeat_reorder_or_dispatch_change_rejected(self):
        self.run_case();events=self.events();node=[e for e in events if e['event'].startswith('node_')]
        variants=[node[1:],node+[node[-1]],list(reversed(node))]
        changed=deepcopy(node);changed[0]['payload']['implementation']='auto';variants.append(changed)
        for data in variants:
            with self.assertRaises(ExecFault):validate_node_events(data,self.plans['streaming_heap'],completed=True)
    def test_measurement_scope_censoring_and_missingness(self):
        r=self.run_case();m=r['measurements']
        self.assertIsNone(m['budget_within']);self.assertIsNone(m['worker_peak_ram_bytes'])
        self.assertGreaterEqual(m['verifier_wall_ns_separate'],0);self.assertGreater(m['process_cpu_ns'],0)
        for field,value in [('worker_peak_ram_bytes',0),('physical_copy_bytes',0),('block_io_bytes',0),('budget_within',True),
                            ('elapsed_ns',True),('process_cpu_ns',-1),('verifier_cpu_ns_separate',None),('formal_ready',True),
                            ('process_cpu_scope','whole_process'),('rss_scope','isolated_ram')]:
            bad=deepcopy(m);bad[field]=value
            with self.assertRaises(ExecFault):validate_measurements(bad,'COMPLETED')
        with self.assertRaises(ExecFault):validate_measurements(m,'TIMEOUT')
    def test_wrong_recipe_produces_unknown_not_repaired_gold(self):
        self.recipe['revision']='UNSUPPORTED_PRIVATE_RECIPE'
        r=self.run_case();self.assertEqual(r['terminal_status'],'COMPLETED');self.assertEqual(r['verification']['status'],'UNKNOWN')
    def test_source_closure_change_during_worker_rejects_success(self):
        original=source_closure();changed={**original,'rcwg_exec/worker.py':'0'*64}
        with patch('rcwg_exec.supervisor.source_closure',side_effect=[original,changed]):r=self.run_case()
        self.assertEqual(r['terminal_status'],'INFRA_FAILURE');self.assertEqual(r['failure']['code'],'SOURCE_CHANGED_DURING_EXECUTION')
    def test_output_timestamp_cannot_predate_this_run(self):
        self.run_case();e=self.manifest.as_dict()['expected_records'][0]
        p=self.out/'worker/artifact.json';meta=read_json(p);meta['created_ns']=0;p.write_bytes(canonical(meta))
        p=self.out/'worker/artifact_binding.json';binding=read_json(p);binding['artifact_metadata_sha256']=digest(meta);p.write_bytes(canonical(binding))
        with self.assertRaises(ExecFault):validate_artifact(self.out/'worker',expected=e,task=self.task,
            plan=self.plans['streaming_heap'],compiled=validate_workflow(self.task,self.plans['streaming_heap']),creation_window=(1,time.perf_counter_ns()))


class JournalAndSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_journal_fsync_is_incremental_and_hash_chained(self):
        p=self.root/'journal';j=Journal(p,execution_key='key',manifest_hash='hash',origin='worker')
        try:
            j.append('worker_started','RUNNING',{});self.assertEqual(len(p.read_bytes().splitlines()),1)
            j.append('worker_finished','COMPLETED',{});self.assertEqual(len(p.read_bytes().splitlines()),2)
        finally:j.close()
        r=read_journal(p,execution_key='key',manifest_hash='hash',origin='worker',pid=os.getpid());self.assertEqual(len(r['events']),2)
        original=p.read_bytes();lines=original.splitlines(keepends=True)
        for raw in (lines[1]+lines[0],lines[0]+lines[0],lines[1],original[:-1]):
            p.write_bytes(raw)
            with self.assertRaises(ExecFault):read_journal(p,execution_key='key',manifest_hash='hash',origin='worker')
    def test_journal_rejects_foreign_clock_pid_or_context(self):
        p=self.root/'journal';j=Journal(p,execution_key='key',manifest_hash='hash',origin='worker')
        j.append('x','RUNNING',{});j.close()
        for kwargs in ({'execution_key':'other'},{'manifest_hash':'other'},{'origin':'other'},{'pid':os.getpid()+1}):
            args={'execution_key':'key','manifest_hash':'hash','origin':'worker',**kwargs}
            with self.assertRaises(ExecFault):read_journal(p,**args)
    def test_ancestor_directory_symlink_rejected(self):
        t,p,r,data=prepare_fixture(self.root/'real');(self.root/'link').symlink_to(self.root/'real',target_is_directory=True)
        with self.assertRaises(ExecFault):FileRegistry(t,{t['datasets'][0]['id']:self.root/'link/records.jsonl'},allowed_root=self.root)
    def test_source_replaced_by_symlink_after_registration_rejected(self):
        t,p,r,data=prepare_fixture(self.root/'real');reg=FileRegistry(t,{t['datasets'][0]['id']:data},allowed_root=self.root)
        copy=self.root/'copy';copy.write_bytes(data.read_bytes());data.unlink();data.symlink_to(copy)
        with self.assertRaises(ExecFault):list(reg.frames(t['datasets'][0]['id'],{},lambda:None))
    def test_source_changed_while_iterator_active_rejected(self):
        t,p,r,data=prepare_fixture(self.root/'real',n=12);reg=FileRegistry(t,{t['datasets'][0]['id']:data},allowed_root=self.root)
        stream=reg.frames(t['datasets'][0]['id'],{},lambda:None);next(stream)
        with data.open('ab') as f:f.write(canonical({'id':999,'score':1.0,'eligible':True})+b'\n')
        with self.assertRaises(ExecFault):list(stream)
    def test_actual_registered_file_duplicate_and_bad_utf8_rejected(self):
        t,p,r,data=prepare_fixture(self.root/'real',n=1)
        for raw in (b'{"id":1,"id":2,"score":1.0,"eligible":true}\n',b'\xff\n'):
            data.write_bytes(raw);t['datasets'][0]['data_sha256']=hashlib.sha256(raw).hexdigest()
            reg=FileRegistry(t,{t['datasets'][0]['id']:data},allowed_root=self.root)
            with self.assertRaises(ExecFault):list(reg.frames(t['datasets'][0]['id'],{},lambda:None))
    def test_private_json_rejects_duplicate_encoding_and_noncanonical(self):
        p=self.root/'value'
        for raw in (b'{"a":1,"a":2}',b'\xff',b'{"a": 1}',b'[{'):
            p.write_bytes(raw)
            with self.assertRaises(ExecFault):read_json(p)
    def test_nonregular_fifo_rejected_without_waiting_for_writer(self):
        from rcwg_exec.files import open_regular
        p=self.root/'fifo';os.mkfifo(p)
        with self.assertRaises(ExecFault):open_regular(p)
    def test_rehashed_backwards_clock_and_wrong_node_status_rejected(self):
        p=self.root/'journal';j=Journal(p,execution_key='key',manifest_hash='hash',origin='worker')
        j.append('x','RUNNING',{});j.append('y','RUNNING',{});j.close()
        items=[json.loads(line) for line in p.read_bytes().splitlines()]
        items[1]['monotonic_ns']=items[0]['monotonic_ns']-1
        items[1]['sha256']=digest({k:v for k,v in items[1].items() if k!='sha256'})
        p.write_bytes(b''.join(canonical(x)+b'\n' for x in items))
        with self.assertRaises(ExecFault):read_journal(p,execution_key='key',manifest_hash='hash',origin='worker')
        plan={'nodes':[{'id':'n','operator':'scan','implementation':'sequential'}]}
        event={'event':'node_queued','status':'RUNNING','payload':{'node_instance_id':'root/n#0','operator':'scan','implementation':'sequential'}}
        with self.assertRaises(ExecFault):validate_node_events([event],plan,completed=False)


if __name__=='__main__':unittest.main()
