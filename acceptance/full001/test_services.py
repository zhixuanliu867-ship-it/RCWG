"""Offline protocol fixtures do not stand in for provider or billing evidence."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import unittest
import uuid
from rcwg_full.evidence import canonical,digest,write
from rcwg_full.data.templates import f1
from rcwg_full.services.bindings import validate_binding,registry
from rcwg_full.services.requests import assemble,parse_final
from rcwg_full.services.client import ServiceClient,RequestIndex,generate
from rcwg_api.vertex import Response
from rcwg_spec.generation import LOGICAL_FIELDS
from support import EvidenceDirectory
import asyncio


def binding(slot='G0'):
    return {'slot':slot,'role':'GENERATOR' if slot.startswith('G') else 'EXECUTOR','provider':'VERTEX',
            'endpoint':'https://us-central1-aiplatform.googleapis.com/v1/projects/fixture-project/locations/us-central1/publishers/google/models/fixture-model',
            'api_version':'v1','requested_model':'fixture-model','reported_revision':'fixture-revision','region':'us-central1',
            'account_binding_hash':'a'*64,'supported_parameters':{'seed':'UNSUPPORTED','temperature':'SUPPORTED','top_k':'UNSUPPORTED','thinking':'UNSUPPORTED','json':'SUPPORTED'},
            'max_input_tokens':12288,'max_output_tokens':16384,'thinking':False,'structured_json':True,
            'tokenizer':'fixture-tokenizer','count_method':'LOCAL_TOKENIZER','price_snapshot':None,'data_policy':None,
            'valid_from':None,'valid_until':None,'decoding':{'temperature':0,'top_k':None,'thinking':None},
            'idempotency':'UNSUPPORTED','template_hash':'b'*64}


class Replay:
    mode='ENGINEERING_REPLAY'
    def __init__(self,values):self.values=list(values);self.calls=[]
    def send(self,kind,body,request_id,*,reservation):
        self.calls.append({'kind':kind,'body':json.loads(body),'request_id':request_id,'reservation':reservation})
        item=self.values.pop(0)
        if isinstance(item,Exception):raise item
        return Response(200,canonical({'modelVersion':'fixture-revision','candidates':[{'finishReason':'STOP','content':{'parts':[{'text':item}]}}],
                                       'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':9,'totalTokenCount':16}}),{},123)


class Counter:
    identity='fixture-tokenizer'
    def __call__(self,body):return 23


class ServicesTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory('services-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()

    def test_index_close_defers_until_late_inflight_response_is_persisted(self):
        import threading
        index=RequestIndex(self.root/'deferred');rid=str(uuid.uuid4());ready=threading.Event();release=threading.Event();errors=[]
        def active():
            try:
                with index.operation():
                    index.begin(rid,{'fixture':True});ready.set()
                    if not release.wait(5):raise TimeoutError('test synchronization')
                    index.record(rid,'COMPLETED',{'status':'COMPLETED','late_fixture':True})
            except Exception as exc:errors.append(str(exc))
        worker=threading.Thread(target=active);worker.start()
        try:
            self.assertTrue(ready.wait(5));index.close();self.assertFalse(index.closed)
            with self.assertRaisesRegex(RuntimeError,'CLOSING'):
                with index.operation():pass
        finally:release.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[]);self.assertTrue(index.closed)
        reopened=RequestIndex(self.root/'deferred')
        try:self.assertEqual(reopened.begin(rid,{'fixture':True}),(False,{'status':'COMPLETED','late_fixture':True}))
        finally:reopened.close()
    def client(self,values):
        replay=Replay(values);index=RequestIndex(self.root/'requests');self.addCleanup(index.close)
        return ServiceClient(binding(),replay,None,index),replay
    def request(self,client):
        task=f1('F1-01',0,'C0')['task']
        return assemble(task,client.binding,protocol='P0',stage='physical',attempt_id='attempt',request_id=str(uuid.uuid4()),trial_label=17)

    def test_six_generators_and_two_fixed_executors(self):
        r=registry([binding(s) for s in [*[f'G{i}' for i in range(6)],'E0','E1']]);self.assertEqual(len(r['bindings']),8)
        with self.assertRaisesRegex(ValueError,'SIX_GENERATORS'):registry([binding()]*8)
        with self.assertRaisesRegex(ValueError,'ENDPOINT'):validate_binding(dict(binding(),endpoint='https://evil.example/v1'))
        with self.assertRaisesRegex(PermissionError,'NOT_FROZEN'):validate_binding(binding(),live=True)

    def test_paid_reservation_requires_explicit_count_and_thinking_bounds(self):
        from types import SimpleNamespace
        from rcwg_full.services.pricing import check_reservation,reservation_bound
        b=binding();b['price_snapshot']={'input_usd_per_million':'1.1','output_usd_per_million':'2.2'}
        request={'body':{'generationConfig':{'maxOutputTokens':12}}};measurement={'tokens':10}
        with self.assertRaisesRegex(PermissionError,'NOT_FROZEN'):reservation_bound(b,request,'G',measurement)
        policy={'revision':'FULL001_BILLING_BOUND_1','rates_are_upper_bounds':True,'output_cap_includes_thinking':True,'count_request_microusd_upper':3}
        b['price_snapshot']['billing_policy']=policy
        self.assertEqual(reservation_bound(b,request,'G',measurement),38)
        self.assertEqual(reservation_bound(b,request,'COUNT',None),3)
        with self.assertRaisesRegex(PermissionError,'BELOW'):check_reservation(b,request,'G',measurement,SimpleNamespace(config={'reservation_microusd':{'G':37}}))
        self.assertEqual(check_reservation(b,request,'G',measurement,SimpleNamespace(config={'reservation_microusd':{'G':38}})),38)
        policy['output_cap_includes_thinking']=False
        with self.assertRaisesRegex(PermissionError,'THINKING'):reservation_bound(b,request,'G',measurement)
        policy['thinking_tokens_upper']=4;self.assertEqual(reservation_bound(b,request,'G',measurement),47)
        del policy['count_request_microusd_upper']
        with self.assertRaisesRegex(PermissionError,'COUNT_COST'):reservation_bound(b,request,'COUNT',None)

    def test_p1_two_requests_same_attempt_and_no_seed_claim(self):
        task=f1('F1-01',0,'C0');logical={k:[] if k in {'uncertainty','permissible_alternatives'} else ['public contract'] for k in LOGICAL_FIELDS}
        client,replay=self.client([canonical(logical).decode(),canonical(task['plan']).decode()])
        result=generate(task['task'],{'protocol':'P1','trial_label':17},client,'same-attempt',local_counter=Counter())
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(replay.calls),2)
        self.assertNotEqual(replay.calls[0]['request_id'],replay.calls[1]['request_id'])
        self.assertEqual([c['body']['generationConfig']['maxOutputTokens'] for c in replay.calls],[4096,12288])
        self.assertTrue(all('seed' not in c['body']['generationConfig'] for c in replay.calls))
        self.assertTrue(all(c['reservation'] is None for c in replay.calls));write(self.root/'result.json',result)

    def test_failed_logical_preserves_not_run_physical(self):
        client,replay=self.client(['{}']);result=generate(f1('F1-01',0,'C0')['task'],{'protocol':'P1','trial_label':29},client,'attempt',local_counter=Counter())
        self.assertEqual(result['status'],'MODEL_FAILURE');self.assertEqual(len(replay.calls),1)
        self.assertEqual(result['records'][1],{'stage':'physical','status':'NOT_RUN','request_id':None})

    def test_uncertain_request_never_resends_and_late_response_only_appends(self):
        client,replay=self.client([OSError('uncertain')]);request=self.request(client);m,_=client.measure(request,local_counter=Counter())
        first=client.call(request,'G',input_measurement=m);second=client.call(request,'G',input_measurement=m)
        self.assertEqual(first,second);self.assertEqual(len(replay.calls),1);self.assertEqual(first['status'],'SENT_UNCONFIRMED')
        client.index.late_response(request['request_id'],Response(200,b'{"late":true}',{},8))
        self.assertEqual(client.call(request,'G',input_measurement=m),first)
        changed={**request,'body':{'different':True},'body_hash':digest({'different':True})}
        with self.assertRaisesRegex(ValueError,'PAYLOAD_CONFLICT'):client.call(changed,'G',input_measurement=m)

    def test_unknown_or_over_limit_input_never_dispatches(self):
        client,replay=self.client([]);request=self.request(client)
        self.assertEqual(client.call(request,'G')['status'],'NOT_AUTHORIZED')
        request=self.request(client);m,_=client.measure(request,local_counter=Counter());m['tokens']=12289
        self.assertEqual(client.call(request,'G',input_measurement=m)['status'],'INPUT_LIMIT_EXCEEDED');self.assertFalse(replay.calls)

    def test_strict_output_and_opt_in_single_fence(self):
        plan=f1('F1-01',0,'C0')['plan'];raw=canonical(plan)
        self.assertEqual(parse_final(raw,'physical')['value'],plan)
        with self.assertRaises(ValueError):parse_final(b'```json\n'+raw+b'\n```','physical')
        self.assertTrue(parse_final(b'```json\n'+raw+b'\n```','physical',allow_single_fence=True)['single_fence_removed'])
        for raw in [b'{}{}',b'{"x":NaN}',b'{"x":1,"x":2}',b'\xff']:
            with self.assertRaises(ValueError):parse_final(raw,'physical')

    def test_capability_and_private_task_boundaries(self):
        b=binding();b['decoding']['top_k']=5
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED'):validate_binding(b)
        client,_=self.client([]);task=f1('F1-01',0,'C0')['task'];task['private_gold']={'answer':7}
        with self.assertRaises(ValueError):assemble(task,client.binding,protocol='P0',stage='physical',attempt_id='a',request_id=str(uuid.uuid4()),trial_label=17)

    def test_live_without_exact_receipt_stops_before_budget_and_transport(self):
        now=datetime.now(timezone.utc);b=binding();b.update(data_policy='fixture-only',price_snapshot={'as_of':'2026-09-22','source':'fixture','input_usd_per_million':'1','output_usd_per_million':'1'},valid_from=(now-timedelta(hours=1)).isoformat(),valid_until=(now+timedelta(hours=1)).isoformat())
        replay=Replay([]);replay.mode='LIVE';index=RequestIndex(self.root/'requests');self.addCleanup(index.close)
        client=ServiceClient(b,replay,None,index,mode='LIVE',scope_hash='c'*64)
        request=self.request(client);m,_=client.measure(request,local_counter=Counter())
        self.assertEqual(client.call(request,'G',input_measurement=m)['status'],'NOT_AUTHORIZED');self.assertEqual(replay.calls,[])

    def test_guided_diagnostic_sends_only_one_physical_stage(self):
        from rcwg_full.campaign.transforms import public_guidance
        task=f1('F1-01',0,'C0');client,replay=self.client([canonical(task['plan']).decode()])
        result=generate(task['task'],{'protocol':'P1','trial_label':17,'generation_stage':'GUIDED_PHYSICAL'},client,'guided',local_counter=Counter(),guidance=public_guidance(task['task']))
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(replay.calls),1)
        self.assertEqual(replay.calls[0]['body']['generationConfig']['maxOutputTokens'],12288)

    def test_real_loopback_fixed_executor_with_replay_and_no_credentials(self):
        from rcwg_full.services.client import FixedSemanticService
        from rcwg_full.services.broker import SemanticBroker,RemoteSemantic
        template={'revision':'fixture-only','instruction':'Return the bound fields and citations.'};b=binding('E0');b['template_hash']=digest(template)
        replay=Replay(['[]','[]']);index=RequestIndex(self.root/'ipc');self.addCleanup(index.close)
        client=ServiceClient(b,replay,None,index);service=FixedSemanticService(client,template,local_counter=Counter());broker=SemanticBroker(service)
        try:
            connection=broker.connection();remote=RemoteSemantic(connection)
            request={'service_id':'E0','question':'public fixture','field_schema':{},'contexts':[]}
            async def both():return await asyncio.gather(remote.extract(request),remote.extract(request))
            self.assertEqual(asyncio.run(both()),[[],[]]);self.assertEqual(broker.snapshot()['responses'],2)
            self.assertEqual(broker.snapshot()['inflight'],0);self.assertNotIn('credential',str(connection).lower())
            bad=RemoteSemantic({**connection,'token':'wrong'})
            with self.assertRaisesRegex(ValueError,'RPC_FAILED'):asyncio.run(bad.extract(request))
            self.assertEqual(len(replay.calls),2);self.assertEqual(broker.snapshot()['inflight'],0)
        finally:broker.close()
