"""Independent R1 regression cases; no host loads, API calls or cgroup writes."""
import copy
import itertools
import json
import random
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from rcwg_full.evidence import digest, write, read, sha, source_hashes
from rcwg_full.verification.compare import bag_equal, equivalent, check_output
from rcwg_full.runtime.measurement import terminal_budget
from rcwg_full.analysis.metrics import capability
from rcwg_full.runtime.host_scope import HostClaim, run_identity
from support import EvidenceDirectory


class FloatBagR1(unittest.TestCase):
    def test_1005_identical_float_and_integer_control(self):
        for value in (1.0, 1):
            rows = [{'score': value} for _ in range(1005)]
            self.assertEqual(check_output(rows, copy.deepcopy(rows), {'comparison':'bag'})['status'], 'PASS')

    def test_duplicate_multiplicity_and_overlapping_neighborhoods(self):
        self.assertFalse(bag_equal([1.0]*1005, [1.0]*1004+[2.0]))
        self.assertTrue(bag_equal([1e-8]*1005+[2e-8]*1005, [0.0]*1005+[1e-8]*1005, abs_tol=1.01e-8, rel_tol=0))
        self.assertFalse(bag_equal([1e-8]*1004+[2e-8]*1006, [0.0]*1005+[1e-8]*1005, abs_tol=1.01e-8, rel_tol=0))

    def test_exact_key_partition_and_type_are_preserved(self):
        rows = [{'id': i, 'score': float(i)} for i in range(4096)]
        self.assertTrue(bag_equal(list(reversed(rows)), rows))
        self.assertFalse(bag_equal([{'id':1, 'score':1}], [{'id':1, 'score':1.0}]))
        self.assertFalse(bag_equal([{'id':2, 'score':1.0}], [{'id':1, 'score':1.0}]))

    def test_compressed_flow_against_exhaustive_small_oracle(self):
        rng = random.Random(9182)
        for n in range(1, 7):
            for _ in range(30):
                a=[float(rng.randrange(5)) for _ in range(n)]; b=[float(rng.randrange(5)) for _ in range(n)]
                oracle=any(all(equivalent(x,y,abs_tol=1.01,rel_tol=0) for x,y in zip(a,order)) for order in itertools.permutations(b))
                self.assertEqual(bag_equal(a,b,abs_tol=1.01,rel_tol=0),oracle,(a,b))


def budget_report(status='TIMEOUT'):
    task={'resources':{'wall_timeout_s':1,'worker_memory_limit_bytes':67108864,'cpu_slots':1}}
    report={'terminal_status':status,'mode':'ENGINEERING_NATIVE','execution_started':True,
            'exec_started_monotonic_ns':100,'effective_timeout_ns':1000000000,'task_deadline_ns':1000000100,
            'observed_elapsed_ns':1001000000,'exec_elapsed_ns':None,'failure':{'code':'WALL_TIMEOUT'},
            'cleanup_failures':[],'process_group_final':{'live':[]},'measurements':{},
            'verification':{'status':'UNKNOWN'}}
    return task,report


class BudgetR1(unittest.TestCase):
    def test_confirmed_task_timeout_retains_censoring_and_false_capability(self):
        task, report=budget_report(); result=terminal_budget(report,task)
        self.assertTrue(result['budget_failure_confirmed']); self.assertFalse(result['budget'])
        scored=capability(result); self.assertFalse(scored['success']); self.assertFalse(scored['efficient'])
        self.assertIsNone(scored['completed_time_ns']); self.assertEqual(scored['observed_elapsed_ns'],report['observed_elapsed_ns'])

    def test_startup_override_deadline_or_cleanup_uncertainty_is_not_confirmed(self):
        task, report=budget_report()
        for changed in [{'execution_started':False},{'effective_timeout_ns':1000},
                        {'task_deadline_ns':1000},{'cleanup_failures':[{'stage':'cleanup'}]},
                        {'process_group_final':{'live':[123]}}]:
            self.assertFalse(terminal_budget({**report,**changed},task)['budget_failure_confirmed'])

    def test_oom_with_missing_worker_report_uses_scoped_counters_only(self):
        task,report=budget_report('INFRA_FAILURE')
        report.update(enforced_resources=task['resources'],launch_ack={'status':'PASS'},
                      measurements={'status':'COUNTERS_OBSERVED','oom_kill_delta':1,'run_memory_oom_delta':1,'cleanup':{'status':'REMOVED'}})
        result=terminal_budget(report,task); self.assertEqual(result['status'],'OOM'); self.assertTrue(result['budget_failure_confirmed'])
        for field in ['oom_kill_delta','run_memory_oom_delta']:
            bad=copy.deepcopy(report);bad['measurements'][field]=None
            self.assertEqual(terminal_budget(bad,task)['status'],'INFRA_FAILURE')

    def test_uncalibrated_counters_and_evidence_binding_cannot_pass_budget(self):
        task,report=budget_report('COMPLETED')
        report.update(exec_elapsed_ns=500,verification={'status':'PASS'},binding_validation={'status':'EVIDENCE_BOUND'},
                      measurements={'status':'COUNTERS_OBSERVED','calibrated':False,'budget_within':None,
                                    'worker_peak_ram_bytes':1024,'oom_kill_delta':0})
        result=terminal_budget(report,task)
        self.assertIsNone(result['budget']); self.assertFalse(result['measurement_valid'])
        self.assertIsNone(capability({**result,'semantic':True,'evidence_valid':True})['success'])

    def test_actual_adapter_store_analysis_timeout_path(self):
        from rcwg_full.campaign.runner import PreparedNativeExecutor
        from rcwg_full.campaign.store import CampaignStore
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);task,report=budget_report();task['task_id']='r1-task'
        item={}
        for name,value in [('task',task),('data_manifest',{}),('private_verifier',{'expected':[],'comparison':'bag'})]:
            path=root/(name+'.json');h=write(path,value)
            item['task_path' if name=='task' else name]=str(path)
            item['task_sha256' if name=='task' else name+'_sha256']=h
        slot={'slot_id':'execution','slot_kind':'execution','task_id':task['task_id'],'generation_slot_id':'generation','condition':'C0','ledger_role':'PRIMARY'}
        def supervisor(*a,**k):
            k['output'].mkdir();write(k['output']/'report.json',report);return report
        executor=PreparedNativeExecutor({task['task_id']:item},root,'ENGINEERING_NATIVE')
        with patch('rcwg_full.runtime.supervisor.execute',supervisor):
            result=executor(slot,'unused',{'generation':{'plan':{},'plan_hash':digest({}),'model_snapshot_hash':'x'}},root)
        store=CampaignStore(root/'campaign.sqlite3')
        try:
            store.register([slot]);claim=store.claim('execution','test','unique')
            version=store.mark('execution',claim['attempt_id'],'test',claim['version'],'RUNNING',{})
            store.mark('execution',claim['attempt_id'],'test',version,result['status'],result)
            observation=store.observations('ENGINEERING_NATIVE')[0]
        finally:store.close()
        self.assertFalse(capability(observation)['success']);self.assertEqual(observation['observed_elapsed_ns'],report['observed_elapsed_ns'])


class HostScopeR1(unittest.TestCase):
    def setUp(self):
        self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
        self.task={'resources':{'cpu_slots':1,'worker_memory_limit_bytes':67108864,'wall_timeout_s':1}}
        self.identity={'host':{'system':'Linux','machine_id_sha256':'a'*64,'boot_id_sha256':'b'*64,'kernel':'fixture'}}
        self.scope={'revision':'FULL001_HOST_SCOPE_2','affinity':[0],'runtime_identity':self.identity,
                    'claim_ledger':str(self.root/'claims.sqlite3'),
                    'slots':[{'slot_id':'one','task_hash':digest(self.task),'max_attempts':2}]}
    def tearDown(self):self.tmp.cleanup()
    def claim(self,attempt=None,actual=None):
        receipt={'approved':True,'action':'HOST','subject_hash':digest(self.scope),'actor_role':'Owner',
                 'actor_id':'fixture','receipt_id':'fixture','valid_from':'2020-01-01T00:00:00Z','valid_until':'2099-01-01T00:00:00Z'}
        return HostClaim(self.scope,receipt,self.task,self.root,'one',attempt or str(uuid.uuid4()),
                         identity_reader=lambda *a,**k:actual if actual is not None else self.identity)
    def test_wrong_boot_rejected_before_claim_or_fs_write(self):
        actual=copy.deepcopy(self.identity);actual['host']['boot_id_sha256']='c'*64
        with self.assertRaisesRegex(PermissionError,'APPLICABILITY'):self.claim(actual=actual)
        self.assertFalse((self.root/'claims.sqlite3').exists())
    def test_no_replay_or_lease_expiry_and_finite_attempts(self):
        first=self.claim();first.activate()
        with self.assertRaisesRegex(PermissionError,'CONSUMED_OR_UNCERTAIN'):self.claim(first.attempt_id)
        with self.assertRaisesRegex(PermissionError,'UNRECONCILED'):self.claim()
        first.finish({'cleanup':{'status':'REMOVED'}})
        second=self.claim();second.activate();second.finish({'cleanup':{'status':'REMOVED'}})
        self.assertEqual(second.snapshot()['state'],'CONSUMED')
        with self.assertRaisesRegex(PermissionError,'EXHAUSTED'):self.claim()
    def test_identity_rechecked_before_activation(self):
        first=self.claim();first.identity_reader=lambda *a,**k:{'host':{'system':'Linux'}}
        with self.assertRaisesRegex(PermissionError,'APPLICABILITY'):first.activate()
        self.assertEqual(first.snapshot()['state'],'CLAIMED')


class AllocationR1(unittest.IsolatedAsyncioTestCase):
    async def test_stream_conversion_buffers_live_until_consumer_advance(self):
        import pyarrow as pa
        from rcwg_full.runtime.artifacts import ArtifactStore
        from rcwg_full.runtime.events import Journal
        from rcwg_full.runtime.streams import BoundedStream
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        journal=Journal(root/'events.jsonl','allocation-r1');self.addCleanup(journal.close)
        store=ArtifactStore(root/'artifacts','allocation-r1',journal)
        stream=BoundedStream(on_retain=lambda batch:store.register(batch,{'kind':'RuntimeBatch'},'transform'),on_release=store.drop_view)
        batch=pa.record_batch({'value':[1,2,3]})
        await stream.put(batch,batch.nbytes);await stream.finish()
        iterator=stream.__aiter__();actual=await iterator.__anext__()
        self.assertEqual(actual,batch);self.assertTrue(any(b['released_ns'] is None for b in store.buffers.values()))
        with self.assertRaises(StopAsyncIteration):await iterator.__anext__()
        self.assertTrue(all(b['released_ns'] is not None for b in store.buffers.values()))
        self.assertGreaterEqual(store.lifetime_metrics()['registered_buffer_peak_bytes'],batch.nbytes)

    async def test_graph_json_object_aliases_are_counted_once_and_released(self):
        from rcwg_full.runtime.artifacts import ArtifactStore
        from rcwg_full.runtime.events import Journal
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        journal=Journal(root/'events.jsonl','json-r1');self.addCleanup(journal.close)
        store=ArtifactStore(root/'artifacts','json-r1',journal)
        payload={'nodes':[{'node_id':1001}],'edges':[]}
        a=store.register(payload,{'kind':'Graph'},'graph');b=store.register(payload,{'kind':'Graph'},'view')
        self.assertEqual(a.buffer_ids,b.buffer_ids);self.assertGreater(len(a.buffer_ids),1)
        store.drop_view(a);self.assertTrue(all(store.buffers[k]['released_ns'] is None for k in b.buffer_ids))
        store.drop_view(b);self.assertTrue(all(v['released_ns'] is not None for v in store.buffers.values()))
        metrics=store.lifetime_metrics();self.assertGreater(metrics['registered_python_heap']['peak_bytes'],0)
