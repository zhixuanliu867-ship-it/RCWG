"""Independent boundary tests for versioned compiler, journals and slot storage."""
import asyncio
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from rcwg_full.evidence import ROOT,digest
from rcwg_full.compiler import FullCompiler
from rcwg_full.compiler.operators import validate_operator
from rcwg_spec.compiler import validate_workflow
from rcwg_spec.typesystem import Type
from rcwg_spec.common import ContractError
from rcwg_full.runtime.streams import BoundedStream,CpuAdmission,bounded_map,StreamClosed
from rcwg_full.runtime.events import Journal,verify_journal
from rcwg_full.campaign.planning import primary_slots,diagnostic_slots,selected_tasks,rebind_frozen
from rcwg_full.campaign.store import CampaignStore,Conflict


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.task=json.loads((ROOT/'specs/reference_v1_0/examples/task_input.json').read_text('utf-8'))
        self.plan=json.loads((ROOT/'specs/reference_v1_0/examples/workflow_topk.json').read_text('utf-8'))

    def test_legacy_unchanged_and_partition_only_new_profile(self):
        original=copy.deepcopy(self.plan)
        top=next(n for n in self.plan['nodes'] if n['operator']=='top_k')
        top['params']['partition_by']=['eligible']
        self.assertEqual(validate_workflow(self.task,original)['status'],'IR_VALIDATED')
        self.assertEqual(validate_workflow(self.task,self.plan)['status'],'PLAN_INVALID')
        self.assertEqual(FullCompiler().compile(self.task,self.plan)['status'],'IR_VALIDATED')

    def test_explicit_record_expression(self):
        node={'operator':'project','implementation':'column_view','params':{'columns':['id'],'representation':'record','expressions':{'next':{'op':'add','left':{'field':'id'},'right':{'literal':1}}}},'outputs':{'rows':'Record'}}
        result=validate_operator(node,{'rows':Type('Table',schema=(('id',Type('Int64')),))},task=self.task,stage='primary_execution',path='/nodes/0')
        self.assertEqual(dict(result['outputs']['rows'].schema)['next'].kind,'Int64')
        self.assertIn('CARDINALITY_EXACTLY_ONE',[x['code'] for x in result['runtime_obligations']])

    def test_parameter_binding_dependency_and_type(self):
        self.task['datasets'].append({'id':'dataset:cursor','kind':'record','revision':'v1','schema_source':'engineering-fixture','schema':{'k':'Int64'}})
        self.plan['external_inputs']['cursor']='dataset:cursor'
        top=next(n for n in self.plan['nodes'] if n['operator']=='top_k')
        top['params'].pop('k');top['param_bindings']=[{'parameter':'k','ref':'$input.cursor','field':'k'}]
        report=FullCompiler().compile(self.task,self.plan)
        self.assertEqual(report['status'],'IR_VALIDATED',report)
        typed=next(n for n in report['typed_graph']['nodes'] if n['operator']=='top_k')
        self.assertEqual(typed['param_bindings'][0]['type'],{'kind':'Int64'})
        self.task['datasets'][-1]['schema']['k']='Bool'
        self.assertEqual(FullCompiler().compile(self.task,self.plan)['status'],'PLAN_INVALID')

    def test_dynamic_service_identity_forbidden(self):
        node={'operator':'project','implementation':'column_view','params':{'columns':['id'],'representation':'set'},'outputs':{'rows':'Set'}}
        result=validate_operator(node,{'rows':Type('Table',schema=(('id',Type('Int64')),),domain='graph-a',revision='v1')},task=self.task,stage='primary_execution',path='/nodes/0')
        self.assertEqual(result['outputs']['rows'].domain,'graph-a')
        node['params']['representation']='record';node['params']['field_map']={'x':'rows'}
        with self.assertRaises(ContractError):validate_operator(node,{'rows':Type('Int64')},task=self.task,stage='primary_execution',path='/nodes/0')


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_backpressure_and_cancel_wakes_producer(self):
        stream=BoundedStream(max_batches=2,target_bytes=8,max_object_bytes=32)
        await stream.put(b'abcd',4);await stream.put(b'efgh',4)
        waiting=asyncio.create_task(stream.put(b'i',1))
        await asyncio.sleep(.01);self.assertFalse(waiting.done())
        await stream.cancel()
        with self.assertRaises(StreamClosed):await waiting
        self.assertEqual(stream.peak_bytes,8)

    async def test_one_oversized_batch_and_single_pass(self):
        stream=BoundedStream(target_bytes=8,max_object_bytes=32)
        await stream.put(b'x'*12,12);await stream.finish()
        values=[v async for v in stream];self.assertEqual(values,[b'x'*12])
        with self.assertRaises(StreamClosed):stream.__aiter__()
        stream=BoundedStream(max_object_bytes=5)
        with self.assertRaises(ValueError):await stream.put(b'x'*6,6)

    async def test_map_reorder_and_global_permits(self):
        admission=CpuAdmission(2)
        async def inputs():
            for i in range(6):yield i
        async def compute(i):
            admission.admit_instance()
            async with admission.acquire():await asyncio.sleep((6-i)*.001)
            return i*i
        values=[v async for v in bounded_map(inputs(),compute,parallelism=4,admission=admission)]
        self.assertEqual(values,[0,1,4,9,16,25]);self.assertEqual(admission.peak_in_use,2)
        self.assertEqual(admission.instances,6)

    async def test_instance_budget_is_not_refunded(self):
        a=CpuAdmission(1,instance_limit=2)
        for _ in range(2):
            a.admit_instance()
            async with a.acquire():pass
        with self.assertRaisesRegex(RuntimeError,'DYNAMIC_INSTANCE_LIMIT'):a.admit_instance()


class JournalTests(unittest.TestCase):
    def test_real_chain_and_missing_event(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'events.jsonl';j=Journal(p,'r')
            j.append('run_started',{});j.append('node_ready',{'node':'n'});j.append('run_finished',{});j.seal(Path(temp)/'seal.json')
            self.assertEqual(len(verify_journal(p)),3)
            lines=p.read_bytes().splitlines(keepends=True);p.write_bytes(lines[0]+lines[2])
            with self.assertRaisesRegex(ValueError,'JOURNAL_CHAIN'):verify_journal(p)

    def test_partial_and_tampered_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'events.jsonl';j=Journal(p,'r');j.append('run_started',{});j.close()
            raw=p.read_bytes();p.write_bytes(raw[:-1])
            with self.assertRaisesRegex(ValueError,'PARTIAL_WRITE'):verify_journal(p)
            p.write_bytes(raw.replace(b'run_started',b'run_sabotage'))
            with self.assertRaisesRegex(ValueError,'JOURNAL_CHAIN'):verify_journal(p)


class PlanningTests(unittest.TestCase):
    def test_all_primary_identities_and_dimensions(self):
        spec=json.loads((ROOT/'specs/full001/campaign.json').read_text('utf-8'))
        counts=Counter();seen=set();generation=set()
        for row in primary_slots(spec):
            self.assertNotIn(row['slot_id'],seen);seen.add(row['slot_id']);counts[row['slot_kind']]+=1
            if row['slot_kind']=='generation':generation.add(row['slot_id'])
            else:self.assertIn(row['generation_slot_id'],generation)
        self.assertEqual(counts,{'generation':23040,'execution':61440})

    def test_diagnostic_counts_and_balanced_preselection(self):
        expected={'E2':(0,46080),'E3':(1440,11520),'E4':(0,5120),'E7':(0,1920)}
        for experiment,(generation,execution) in expected.items():
            counts=Counter(r['slot_kind'] for r in diagnostic_slots(experiment))
            self.assertEqual(counts['generation'],generation);self.assertEqual(counts['execution'],execution)
        self.assertEqual(Counter(r['family'] for r in selected_tasks('E3')),{f'F{i}':40 for i in range(1,7)})

    def test_e2_plan_identity_and_pair_mismatch(self):
        source=dict(template_id='F1-05',base_id=1,generator='G0',protocol='P1',trial_label=17,condition='C0')
        target={**source,'condition':'C2'};plan={'nodes':[{'implementation':'full_sort'}]}
        self.assertEqual(rebind_frozen(plan,source,target)['source_plan_hash'],digest(plan))
        with self.assertRaisesRegex(ValueError,'PAIR_MISMATCH'):rebind_frozen(plan,source,{**target,'base_id':2})


class TransactionTests(unittest.TestCase):
    def test_idempotent_claim_and_payload_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            store=CampaignStore(Path(temp)/'db');store.register([{'slot_id':'s'}])
            a=store.claim('s','worker','key');self.assertEqual(a,store.claim('s','worker','key'))
            with self.assertRaises(Conflict):store.claim('s','other','key')
            store.close()

    def test_two_claimers_and_expiry_no_steal(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'db';store=CampaignStore(p);store.register([{'slot_id':'s'}]);store.close()
            def claim(owner):
                db=CampaignStore(p)
                try:db.claim('s',owner,owner);return 'CLAIMED'
                except Conflict:return 'CONFLICT'
                finally:db.close()
            with ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,['a','b']))
            self.assertCountEqual(results,['CLAIMED','CONFLICT'])
            db=CampaignStore(p);rows=db.reconcile(time.time_ns()+120_000_000_000)
            self.assertEqual(rows[0]['coordination'],'RECONCILE_REQUIRED');self.assertFalse(rows[0]['launch_authorized'])
            with self.assertRaises(Conflict):db.claim('s','c','c',version=1)
            db.close()

    def test_one_facility_retry_preserves_original(self):
        with tempfile.TemporaryDirectory() as temp:
            db=CampaignStore(Path(temp)/'db');db.register([{'slot_id':'s'}]);a=db.claim('s','w','k')
            version=db.mark('s',a['attempt_id'],'w',1,'INFRA_FAILURE',{'cause':'IO'})
            with self.assertRaises(Conflict):db.retry('s','w',version,reconciliation={'worker_stopped':False,'request_uncertain':False})
            b=db.retry('s','w',version,reconciliation={'worker_stopped':True,'request_uncertain':False})
            version=db.mark('s',b['attempt_id'],'w',b['version'],'INFRA_FAILURE',{'cause':'IO'})
            with self.assertRaisesRegex(Conflict,'RETRY_LIMIT'):db.retry('s','w',version,reconciliation={'worker_stopped':True,'request_uncertain':False})
            self.assertEqual(db.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2);db.close()


if __name__=='__main__':unittest.main()
