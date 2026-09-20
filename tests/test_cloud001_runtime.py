from copy import deepcopy
from pathlib import Path
import hashlib,json,tempfile,unittest
from rcwg_cloud.runtime import run_batch
from rcwg_cloud.transport import CloudError
from rcwg_cloud.admission import AlreadyExists,WriteUncertain
from rcwg_spec.common import canonical,digest
from rcwg_exec.demo import prepare_fixture
from rcwg_api.mock import wire_fixtures,count,generated
from rcwg_api.vertex import Response

class ObjectServer:
    def __init__(self):self.objects={};self.generations={};self.receipts=[];self.events=[];self.lose=None
    def put_owner(self,key,raw):
        self.objects[key]=raw;self.generations[key]=str(len(self.objects))
        return {'object':key,'generation':self.generations[key],'sha256':hashlib.sha256(raw).hexdigest()}
    def create(self,key,raw):
        self.events.append(('create',key))
        if key in self.objects:raise AlreadyExists(key)
        ref=self.put_owner(key,raw);ref.update(method='POST',ifGenerationMatch=0,bytes=len(raw));self.receipts.append(ref)
        if key==self.lose:raise WriteUncertain('lost ack')
        return ref
    def get(self,key,generation):
        if generation!=self.generations[key]:raise CloudError('GCS_GENERATION_MISMATCH')
        raw=self.objects[key]
        return raw,{'object':key,'generation':generation,'sha256':hashlib.sha256(raw).hexdigest()}
class SyntheticVertex:
    def __init__(self,responses,server):self.responses=list(responses);self.calls=[];self.server=server
    def send(self,kind,raw):
        # Prove at the actual send boundary that durable slot objects already exist.
        i=len(self.calls);slots=('p0.physical.count','p0.physical.generate','p1.logical.count','p1.logical.generate','p1.physical.count','p1.physical.generate')
        key='cloud001/reservations/'+slots[i]+'.json'
        assert key in self.server.objects
        assert json.loads(self.server.objects[key])['request_sha256']==hashlib.sha256(raw).hexdigest()
        self.server.events.append(('HTTP',kind));self.calls.append((kind,raw));r=self.responses.pop(0)
        if isinstance(r,Exception):raise r
        # Synthetic response is explicitly labeled by context, while exercising
        # the real fixed-model gate rather than adding a production mock bypass.
        if r.status==200 and kind=='generateContent':
            data=json.loads(r.body)
            if data.get('modelVersion')=='MOCK-gemini-3.1-flash-lite':data['modelVersion']='gemini-3.1-flash-lite'
            r=Response(r.status,canonical(data),r.headers,r.elapsed_ns)
        return r

class CloudRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,self.data=prepare_fixture(self.root/'fixture');self.s=ObjectServer()
        self.m={'phase':'live','inputs':{k:self.s.put_owner('cloud001/inputs/'+k,raw) for k,raw in
                 [('task',canonical(self.task)),('recipe',canonical(self.recipe)),('records',self.data.read_bytes())]}}
    def run_it(self,responses=None,manifest=None,where='evidence',vertex_absent=False):
        v=None if vertex_absent else SyntheticVertex(responses if responses is not None else wire_fixtures(self.plans['streaming_heap']),self.s)
        r=run_batch(manifest or self.m,store=self.s,vertex=v,root=self.root/where,execution_id='rcwg-cloud001-live-0001',context={'mode':'OFFLINE_SYNTHETIC_NO_CLOUD'})
        return r,v
    def test_six_synthetic_dispatches_real_linux_workers_and_archive(self):
        r,v=self.run_it();self.assertEqual(r['status'],'LIVE_RUNTIME_OBSERVED_COMPLETE',r)
        self.assertEqual(len(v.calls),6);self.assertEqual(r['model_dispatches'],{'generate':3,'count':3})
        self.assertEqual(r['possibly_reserved_microusd'],780000)
        for slot in r['slots'].values():self.assertTrue(slot['execution_started']);self.assertEqual(slot['terminal_status'],'COMPLETED');self.assertEqual(slot['answer'],'PASS')
        self.assertIn('cloud001/output/live/complete.json',self.s.objects);self.assertFalse(r['formal_ready']);self.assertIsNone(r['budget_within'])
    def test_restarted_job_or_changed_manifest_no_new_dispatch(self):
        self.run_it();changed=deepcopy(self.m);changed['extra']='different manifest identity'
        r,v=self.run_it(manifest=changed,where='restart');self.assertEqual(r['status'],'ADMISSION_NOT_ACQUIRED_NO_DISPATCH');self.assertEqual(v.calls,[])
    def test_uncertain_model_transport_consumes_slot_no_repair_or_retry(self):
        r,v=self.run_it([count(),CloudError('TRANSPORT_UNCERTAIN_NO_RETRY')])
        self.assertEqual(len(v.calls),2);self.assertEqual(r['status'],'STOPPED_NO_RETRY')
        self.assertEqual(r['possibly_reserved_microusd'],260000);self.assertEqual(r['slots']['p1']['status'],'NOT_ATTEMPTED')
        self.assertIn('cloud001/reservations/p0.physical.generate.json',self.s.objects)
    def test_gcs_lost_reservation_ack_means_zero_http_and_unknown_cost(self):
        self.s.lose='cloud001/reservations/p0.physical.count.json';r,v=self.run_it()
        self.assertEqual(v.calls,[]);self.assertEqual(r['possibly_reserved_microusd'],10000)
        self.assertEqual(r['acknowledged_reserved_microusd'],0);self.assertEqual(r['expected_generation_denominator'],2)
    def test_input_count_limit_blocks_generation_without_truncating_prompt(self):
        r,v=self.run_it([count(12289)]);self.assertEqual(len(v.calls),1)
        self.assertEqual(r['failure']['code'],'INPUT_TOKEN_LIMIT_NO_GENERATION')
        self.assertIn(b'SHARED PUBLIC DEVELOPMENT EXAMPLE',v.calls[0][1])
    def test_provider_503_is_one_dispatch_and_stops(self):
        r,v=self.run_it([Response(503,b'{}',{},1)])
        self.assertEqual(len(v.calls),1);self.assertEqual(r['status'],'STOPPED_NO_RETRY')
    def test_p1_payload_contains_exact_synthetic_logical_response(self):
        responses=wire_fixtures(self.plans['streaming_heap']);logical=json.loads(json.loads(responses[3].body)['candidates'][0]['content']['parts'][0]['text'])
        logical['uncertainty']=['AUTHENTIC_SYNTHETIC_LOGICAL_CANARY'];responses[3]=generated(logical)
        r,v=self.run_it(responses);self.assertEqual(r['status'],'LIVE_RUNTIME_OBSERVED_COMPLETE')
        user=json.loads(json.loads(v.calls[5][1])['contents'][0]['parts'][0]['text']);self.assertEqual(user['logical_contract'],logical)
        self.assertNotIn(canonical(self.recipe),v.calls[5][1])
    def test_syntactically_legal_wrong_plan_runs_and_answer_fails(self):
        r,v=self.run_it(wire_fixtures(self.plans['omitted_filter']))
        self.assertEqual(r['status'],'LIVE_RUNTIME_OBSERVED_COMPLETE');self.assertEqual(r['slots']['p0']['answer'],'FAIL');self.assertEqual(r['slots']['p1']['answer'],'FAIL')
    def test_unmodified_bare_reference_statically_refused_without_worker(self):
        plan=deepcopy(self.plans['streaming_heap']);plan['nodes'][0]['inputs']['source']='source_dataset'
        r,v=self.run_it(wire_fixtures(plan));self.assertEqual(r['slots']['p0']['status'],'PLAN_INVALID');self.assertFalse(r['slots']['p0']['execution_started'])
        saved=json.loads((self.root/'evidence/observations/p0/exact_model_plan.json').read_bytes());self.assertEqual(saved,plan)
        self.assertFalse((self.root/'evidence/executions/p0').exists())
    def test_replay_transport_absent_and_never_reserves_model(self):
        m=deepcopy(self.m);m['phase']='replay';bad=deepcopy(self.plans['streaming_heap']);bad['nodes'][0]['inputs']['source']='source_dataset'
        for k,p in [('p0_plan',self.plans['streaming_heap']),('p1_plan',bad)]:m['inputs'][k]=self.s.put_owner('cloud001/inputs/'+k,canonical(p))
        r,v=self.run_it(manifest=m,vertex_absent=True)
        self.assertEqual(r['model_dispatches'],{'generate':0,'count':0});self.assertEqual(r['slots']['p0']['terminal_status'],'COMPLETED')
        self.assertFalse(r['slots']['p1']['execution_started']);self.assertFalse(any('/reservations/' in x for x in self.s.objects))
    def test_tampered_input_rejected_before_any_model_call(self):
        self.s.objects['cloud001/inputs/records']+=b'changed';r,v=self.run_it()
        self.assertEqual(v.calls,[]);self.assertEqual(r['failure']['code'],'PINNED_OBJECT_CONTENT_CHANGED')
    def test_final_upload_failure_is_not_complete(self):
        self.s.lose='cloud001/output/live/archive.zip'
        with self.assertRaises(WriteUncertain):self.run_it()
        self.assertNotIn('cloud001/output/live/complete.json',self.s.objects)

if __name__=='__main__':unittest.main()
