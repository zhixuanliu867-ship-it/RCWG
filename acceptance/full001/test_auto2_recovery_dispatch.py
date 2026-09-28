"""BOOT_ONLY real locks and durable state; no network or cloud calls."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json, multiprocessing, tempfile, unittest, threading
from rcwg_full.auto2.control import TaskState
from rcwg_full.auto2.dispatch import DispatchGate
from rcwg_full.auto2.pipeline import Pipeline
from rcwg_full.services.client import generate, FixedSemanticService
from rcwg_full.data.templates import f1
from rcwg_full.evidence import canonical,digest,write
from rcwg_api.vertex import Response
import test_auto2, test_auto2_services


def child_permit(root, policy, authority, tag, entered, release, queue, result):
    state=TaskState(Path(root),policy,authority)
    queue.put((tag,'waiting'))
    try:
        gate=DispatchGate(state)
        with gate.locked(timeout=15):
            gate.admit(tag,'E')
            entered.set()
            if not release.wait(15):raise TimeoutError('fixture release')
            gate.finish(tag,{'status':result})
        queue.put((tag,'finished'))
    except PermissionError as exc:queue.put((tag,str(exc)))


class RecoveryDispatch(unittest.TestCase):
    setUp=test_auto2.Auto2Control.setUp
    client=test_auto2_services.Auto2Services.client
    request=test_auto2_services.Auto2Services.request

    def capability_case(self, failing):
        (self.root/'PREPARATION_EVIDENCE.json').write_text('{}')
        p=Pipeline.__new__(Pipeline);p.root=self.root;p.config={'measurement_profile':'SERVICE_ONLY'}
        p.plan={'initial_generations':[], 'initial_semantic_references':[], 'development_blocks':[]}
        events=[];calls=[]
        p.state=SimpleNamespace(summary=lambda:{'state':'LIVE_RUNNING'},transition=lambda *a:events.append(a))
        p.current_identity=lambda:{};p.scope=lambda *a,**k:{}
        def capability(slot, scope):
            calls.append(slot)
            return {'status':'SENT_UNCONFIRMED' if slot==failing else 'COMPLETED','http_status':None if slot==failing else 200}
        p.capability=capability
        with patch('rcwg_full.auto2.pipeline.preparation_gate',return_value={'status':'PASS'}):
            with self.assertRaisesRegex(PermissionError,'ACTUAL_FACILITY'):p.run()
        self.assertEqual(calls,['G'+str(i) for i in range(int(failing[1])+1)])
        self.assertEqual(json.loads((self.root/'private/capabilities'/f'{failing}.json').read_bytes())['status'],'SENT_UNCONFIRMED')
        self.assertEqual(events[-1][0],'PAUSED_EXTERNAL')

    def test_g0_stops_before_g1(self):self.capability_case('G0')
    def test_g3_stops_before_g4(self):self.capability_case('G3')
    def test_g5_is_saved_before_stop(self):self.capability_case('G5')

    def test_unknown_count_prevents_generation_and_later_count(self):
        client,wire=self.client([])
        def unknown(*args,**kwargs):wire.calls.append(args[0]);raise TimeoutError('fixture')
        wire.send=unknown
        _,first=client.measure(self.request(client))
        _,second=client.measure(self.request(client))
        self.assertEqual(first['status'],'SENT_UNCONFIRMED')
        self.assertTrue(second['task_dispatch_blocked'])
        self.assertEqual(wire.calls,['COUNT'])

    def test_unknown_logical_prevents_physical_and_new_request(self):
        client,wire=self.client([TimeoutError('fixture')])
        outcome=generate(f1('F1-01',0,'C0')['task'],{'protocol':'P1','trial_label':17},client,'fixture')
        self.assertEqual(outcome['records'][1]['status'],'NOT_RUN')
        _,denied=client.measure(self.request(client))
        self.assertTrue(denied['task_dispatch_blocked'])
        self.assertEqual(wire.calls,['COUNT','G'])

    def test_unknown_e_stops_queued_semantic_call(self):
        client,wire=self.client([TimeoutError('fixture')],slot='E0')
        service=FixedSemanticService(client,{'revision':'offline-semantic-fixture'})
        request={'service_id':'E0','question':'fixture','field_schema':{},'contexts':[]}
        with self.assertRaisesRegex(ValueError,'SEMANTIC_SENT_UNCONFIRMED'):service.extract_sync(request)
        with self.assertRaisesRegex(ValueError,'SEMANTIC_NOT_AUTHORIZED'):service.extract_sync(request)
        self.assertEqual(wire.calls,['COUNT','E'])

    def test_unknown_e1_stops_next_e1(self):
        client,wire=self.client([TimeoutError('fixture')],slot='E0')
        client.binding['slot']='E1'
        models={'bindings':[client.binding]};(self.root/'MODEL_LOCK.json').write_bytes(canonical(models));self.identity['models']=digest(models)
        scope=self.state.derive_scope(stage='B_INITIAL',identity=self.identity,limits={'G':24,'E':4,'COUNT':28},ceiling_microusd=15_000_000,expires_at=self.expiry)
        client.budget.scope=scope;client.budget.manifest_hash=digest(scope);client.scope_hash=digest(scope)
        service=FixedSemanticService(client,{'revision':'offline-semantic-fixture'})
        request={'service_id':'E1','question':'fixture','field_schema':{},'contexts':[]}
        with self.assertRaisesRegex(ValueError,'SEMANTIC_SENT_UNCONFIRMED'):service.extract_sync(request)
        with self.assertRaisesRegex(ValueError,'SEMANTIC_NOT_AUTHORIZED'):service.extract_sync(request)
        self.assertEqual(wire.calls,['COUNT','E'])

    def test_all_success_capabilities_reach_followup(self):
        (self.root/'PREPARATION_EVIDENCE.json').write_text('{}')
        p=Pipeline.__new__(Pipeline);p.root=self.root;p.config={'measurement_profile':'SERVICE_ONLY'}
        p.plan={'initial_generations':[], 'initial_semantic_references':[], 'development_blocks':[]}
        p.state=SimpleNamespace(summary=lambda:{'state':'LIVE_RUNNING'},transition=lambda *a:None)
        p.current_identity=lambda:{};p.scope=lambda *a,**k:{};calls=[]
        def success(slot,scope):calls.append(slot);return {'status':'COMPLETED','http_status':200}
        p.capability=success
        with patch('rcwg_full.auto2.pipeline.preparation_gate',return_value={'status':'PASS'}),patch('rcwg_full.auto2.formal.continue_references_and_formal',return_value={'status':'NOT_RUN'}):p.run()
        self.assertEqual(calls,['G'+str(i) for i in range(6)])
        self.assertEqual(len(p.available),6)

    def test_cross_thread_waiter_observes_fuse(self):
        entered=threading.Event();release=threading.Event();waiting=threading.Event();outcomes=[]
        def first():
            gate=DispatchGate(self.state)
            with gate.locked():
                gate.admit('thread-first','E');entered.set();release.wait(10)
                gate.finish('thread-first',{'status':'SENT_UNCONFIRMED'})
        def second():
            gate=DispatchGate(self.state);waiting.set()
            try:
                with gate.locked():gate.admit('thread-second','E')
                outcomes.append('UNSAFE_ADMISSION')
            except PermissionError as exc:outcomes.append(str(exc))
        a=threading.Thread(target=first);b=threading.Thread(target=second)
        try:
            a.start();self.assertTrue(entered.wait(10));b.start();self.assertTrue(waiting.wait(10));release.set()
            a.join(10);b.join(10);self.assertFalse(a.is_alive() or b.is_alive())
            self.assertEqual(outcomes,['TASK_DISPATCH_FUSED'])
        finally:release.set();a.join(10);b.join(10)

    def test_confirmed_model_failure_does_not_trip_fuse(self):
        client,wire=self.client([])
        def answer(kind,*a,**kw):
            wire.calls.append(kind)
            return Response(200,canonical({'totalTokens':7} if kind=='COUNT' else
                {'modelVersion':'r1','candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}],
                 'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':9,'totalTokenCount':16}}),{},1)
        wire.send=answer
        for _ in range(2):
            request=self.request(client);measurement,_=client.measure(request)
            self.assertEqual(client.call(request,'G',input_measurement=measurement)['status'],'MODEL_FAILURE')
        self.assertEqual(wire.calls,['COUNT','G','COUNT','G'])

    def test_preexisting_unknown_fuses_new_process_without_new_reservation(self):
        self.state.reserve(self.scope,'old','G',251904,self.identity)
        self.state.observe('old','SENT_UNCONFIRMED',{'fixture':True})
        resumed=TaskState(self.root,self.policy,self.auth)
        gate=DispatchGate(resumed)
        with gate.locked():
            with self.assertRaisesRegex(PermissionError,'UNRESOLVED_RESERVATION'):gate.admit('new','COUNT')
        self.assertEqual(resumed.summary()['reserved_microusd'],1251904)

    def test_abandoned_active_permit_never_assumes_provider_completion(self):
        gate=DispatchGate(self.state)
        with gate.locked():gate.admit('crashed','G')
        restarted=DispatchGate(TaskState(self.root,self.policy,self.auth))
        with restarted.locked():
            with self.assertRaisesRegex(PermissionError,'ABANDONED_PERMIT'):restarted.admit('new','G')

    def test_cross_process_waiter_observes_fuse_before_permit_release(self):
        ctx=multiprocessing.get_context('spawn');queue=ctx.Queue()
        entered=ctx.Event();release=ctx.Event();other_entered=ctx.Event()
        first=ctx.Process(target=child_permit,args=(str(self.root),self.policy,self.auth,'first',entered,release,queue,'SENT_UNCONFIRMED'))
        second=ctx.Process(target=child_permit,args=(str(self.root),self.policy,self.auth,'second',other_entered,release,queue,'COMPLETED'))
        try:
            first.start();self.assertTrue(entered.wait(15));self.assertEqual(queue.get(timeout=15),('first','waiting'))
            second.start();self.assertEqual(queue.get(timeout=15),('second','waiting'))
            self.assertFalse(other_entered.is_set());release.set()
            first.join(15);second.join(15)
            self.assertEqual((first.exitcode,second.exitcode),(0,0))
            self.assertEqual(set([queue.get(timeout=15),queue.get(timeout=15)]),{('first','finished'),('second','TASK_DISPATCH_FUSED')})
            self.assertFalse(other_entered.is_set())
        finally:
            release.set()
            for process in [first,second]:
                if process.pid is not None:
                    if process.is_alive():process.terminate()
                    process.join(5)
            queue.close();queue.join_thread()
