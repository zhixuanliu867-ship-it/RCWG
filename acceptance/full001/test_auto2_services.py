"""Instrumented offline wire fixtures exercise real AUTO2 admission code, not cloud evidence."""
import json,unittest,uuid
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from rcwg_full.evidence import canonical,digest,write
from rcwg_full.auto2.services import validate_requested,DelegatedClient,ScopeBudget
from rcwg_full.services.bindings import validate_binding
from rcwg_full.services.client import RequestIndex,generate
from rcwg_full.data.templates import f1
from rcwg_api.vertex import Response
import test_auto2
from test_services import binding


class Auto2Services(unittest.TestCase):
    setUp=test_auto2.Auto2Control.setUp
    def client(self,responses):
        b=binding();b.update(reported_revision=None,count_method='PROVIDER_COUNT',data_policy={'fixture_only':True},
            valid_from=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),valid_until=self.expiry,
            price_snapshot={'as_of':'fixture','source':'offline-fixture','input_usd_per_million':'0.1','output_usd_per_million':'0.4',
             'evidence_sha256':'c'*64,'billing_policy':{'revision':'FULL001_BILLING_BOUND_1','rates_are_upper_bounds':True,
               'output_cap_includes_thinking':True,'count_request_microusd_upper':0}})
        models={'bindings':[b]};write(self.root/'MODEL_LOCK.json',models);self.identity['models']=digest(models)
        scope=self.state.derive_scope(stage='B_INITIAL',identity=self.identity,limits={'G':24,'E':4,'COUNT':28},ceiling_microusd=15_000_000,expires_at=self.expiry)
        class WireFixture:
            mode='LIVE'
            def __init__(self):self.calls=[];self.responses=list(responses)
            def send(inner,kind,body,rid,*,reservation):
                self.assertIn(rid,[r['request_id'] for r in self.state.summary()['reservations']])
                inner.calls.append(kind)
                if kind=='COUNT':return Response(200,b'{"totalTokens":7}',{},100)
                value=inner.responses.pop(0)
                if isinstance(value,Exception):raise value
                revision,text=value
                return Response(200,canonical({'modelVersion':revision,'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}],
                    'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':9,'totalTokenCount':16}}),{},200)
        wire=WireFixture();index=RequestIndex(self.root/'requests');self.addCleanup(index.close)
        return DelegatedClient(b,wire,ScopeBudget(self.state,scope,lambda:self.identity,{'G':100000,'E':100000,'COUNT':1}),index),wire
    def request(self,client,rid=None):
        body={'contents':[{'role':'user','parts':[{'text':'fixture'}]}],'generationConfig':{'maxOutputTokens':20}}
        return {'request_id':rid or str(uuid.uuid4()),'body':body,'body_hash':digest(body),'binding_hash':digest(client.binding),'max_input_tokens':12288}
    def test_requested_revision_is_not_fabricated_or_legacy_authorized(self):
        client,_=self.client([]);self.assertIsNone(validate_requested(client.binding)['reported_revision'])
        with self.assertRaises(PermissionError):validate_binding(client.binding,live=True)
    def test_missing_price_evidence_cannot_be_requested(self):
        client,_=self.client([]);b=deepcopy(client.binding);b['price_snapshot'].pop('evidence_sha256')
        with self.assertRaises(PermissionError):validate_requested(b)
    def test_returned_revision_is_first_observed_then_drift_checked(self):
        client,wire=self.client([('r1','{}'),('r2','{}')]);statuses=[]
        for _ in range(2):
            request=self.request(client);measurement,_=client.measure(request);statuses.append(client.call(request,'G',input_measurement=measurement)['status'])
        self.assertEqual(statuses,['COMPLETED','SERVICE_DRIFT']);self.assertIsNone(client.binding['reported_revision'])
    def test_unknown_inference_and_its_count_are_not_reissued(self):
        client,wire=self.client([TimeoutError('offline uncertain fixture')]);request=self.request(client)
        first,_=client.measure(request);a=client.call(request,'G',input_measurement=first)
        second,_=client.measure(request);b=client.call(request,'G',input_measurement=second)
        self.assertEqual(a,b);self.assertEqual(a['status'],'SENT_UNCONFIRMED');self.assertEqual(wire.calls,['COUNT','G'])
    def test_model_bad_json_is_not_infrastructure_failure(self):
        client,wire=self.client([('r1','This is not WorkIR JSON')])
        result=generate(f1('F1-01',0,'C0')['task'],{'protocol':'P0','trial_label':17},client,'fixture')
        self.assertEqual(result['status'],'MODEL_FAILURE');self.assertEqual(result['records'][0]['response']['http_status'],200)
    def test_budget_full_prevents_even_count_wire_dispatch(self):
        client,wire=self.client([]);self.state.reserve(client.budget.scope,'fill','G',15000000,self.identity)
        measurement,result=client.measure(self.request(client))
        self.assertIsNone(measurement);self.assertEqual(result['status'],'NOT_AUTHORIZED');self.assertEqual(wire.calls,[])
    def test_scope_locked_model_cannot_be_substituted(self):
        client,_=self.client([]);client.binding['template_hash']='d'*64
        with self.assertRaisesRegex(PermissionError,'MODEL_NOT'):client.authorize_live()
    def test_mock_mode_is_rejected_before_any_call(self):
        client,wire=self.client([]);wire.mode='ENGINEERING_REPLAY'
        with self.assertRaisesRegex(ValueError,'ACTUAL_PROVIDER'):DelegatedClient(client.binding,wire,client.budget,client.index)
    def test_parallel_semantic_nodes_never_overlap_provider_requests(self):
        import threading,time
        from concurrent.futures import ThreadPoolExecutor
        client,wire=self.client([('r1','{}')]*4)
        original=wire.send;guard=threading.Lock();observed={'active':0,'peak':0}
        def measured(*args,**kwargs):
            with guard:
                observed['active']+=1;observed['peak']=max(observed['peak'],observed['active'])
            try:
                time.sleep(.01)
                return original(*args,**kwargs)
            finally:
                with guard:observed['active']-=1
        wire.send=measured
        def node(_):
            request=self.request(client);measurement,failure=client.measure(request)
            self.assertIsNone(failure)
            return client.call(request,'G',input_measurement=measurement)['status']
        with ThreadPoolExecutor(max_workers=4) as pool:statuses=list(pool.map(node,range(4)))
        self.assertEqual(statuses,['COMPLETED']*4);self.assertEqual(observed['peak'],1)
    def test_token_near_expiry_is_refreshed_by_existing_credential_owner(self):
        from rcwg_full.auto2.services import ExistingWindowsIdentity
        owner=ExistingWindowsIdentity.__new__(ExistingWindowsIdentity)
        owner.binding={};owner.audit=[];owner.cached='old-token-near-expiry';owner.at=0
        tokens=iter([b'valid-near-expiry-token-12345',b'refreshed-provider-token-67890'])
        owner.sdk_call=lambda *args:(next(tokens),{})
        self.assertEqual(owner(),'valid-near-expiry-token-12345')
        self.assertEqual(owner(),'refreshed-provider-token-67890')
