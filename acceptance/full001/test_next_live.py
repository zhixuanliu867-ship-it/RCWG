"""BOOT_ONLY: adversarial local protocol tests, never paid service evidence."""
import asyncio,json,threading,time,unittest,uuid
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from rcwg_full.evidence import canonical,digest,sha,write
from rcwg_full.services.client import RequestIndex,ServiceClient
from rcwg_full.services.request3 import neutral_example,operator_cards,assemble_request3
from rcwg_full.services.quotes import (SentFragment,resolve_quote,prepare_fragments,resolve_rows,
    public_fragments,response_schema,assemble_quote,TEMPLATE)
from rcwg_full.runtime.documents import Documents,canonical_document,compose,piece
from rcwg_full.services.broker import SemanticBroker,RemoteSemantic
from rcwg_full.compiler import FullCompiler
from rcwg_full.auto2.dispatch import DispatchGate
from rcwg_full.auto2 import next_live as nl
from rcwg_full.auto2.control import TaskState
from test_services import binding
import test_recovery_epoch

class Request3Tests(unittest.TestCase):
    def test_all_operators_and_implementations(self):
        cards=operator_cards();self.assertEqual(len(cards),32);self.assertEqual(sum(len(c['implementations']) for c in cards),56)
        self.assertTrue(all(c['inputs'] and c['outputs'] and c['parameter_contract'] for c in cards))
    def test_neutral_example_compiles(self):
        e=neutral_example();self.assertEqual(FullCompiler().compile(e['task'],e['workflow'])['status'],'IR_VALIDATED')
    def test_observed_wrong_types_and_case_stay_invalid(self):
        e=neutral_example()
        for decl in ['stream_of_records','read_source.rows','stream[Record]','Table']:
            with self.subTest(decl=decl):
                p=deepcopy(e['workflow']);p['nodes'][0]['outputs']['rows']=decl
                self.assertEqual(FullCompiler().compile(e['task'],p)['status'],'PLAN_INVALID')
    def test_reference_type_swap_not_repaired(self):
        e=neutral_example();p=deepcopy(e['workflow']);p['nodes'][1]['inputs']['rows']='Stream[Record]'
        self.assertEqual(FullCompiler().compile(e['task'],p)['status'],'PLAN_INVALID')
    def test_models_share_semantics_and_legacy_example_removed(self):
        e=neutral_example();kw=dict(protocol='P0',stage='physical',attempt_id='new',request_id=str(uuid.uuid4()),trial_label=17)
        a=assemble_request3(e['task'],binding('G0'),**kw);b=assemble_request3(e['task'],binding('G5'),**kw)
        self.assertEqual(a['body'],b['body']);self.assertNotIn('prompts/v1_1/system.txt',a['source_hashes'])
        self.assertEqual(a['schema_version'],'FULL001_REQUEST_3')
    def test_broadcast_dynamic_ports_rejected_when_mismatched(self):
        from rcwg_full.compiler.operators import validate_operator
        from rcwg_full.compiler.typesystem import Type
        n={'operator':'broadcast','implementation':'shared_ref','params':{'consumers':['a','b']},'outputs':{'a':'ArtifactRef'},'inputs':{'artifact':'x.rows'}}
        with self.assertRaises(Exception):validate_operator(n,{'artifact':Type('Table',schema=(('flag',Type('Bool')),))},task={},stage='primary_execution',path='/n')

class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.doc=canonical_document('doc','r','T',[{'text':'Heading\n甲🙂 e\u0301 aa aa aaa\nTail'}]);self.docs=Documents([self.doc])
        self.context=compose([piece(self.doc,8,len(self.doc['canonical_text'])-5)])
        self.sent,self.sources=prepare_fragments([self.context],self.docs)
    def resolve(self,q):return resolve_quote({'fragment_id':'f0','quote':q},self.sent,self.sources)
    def test_unicode_codepoints_exact(self):
        c=self.resolve('🙂 e\u0301');self.assertEqual(self.doc['canonical_text'][c['start_cp']:c['end_cp']],c['quote'])
    def test_combining_whitespace_and_unpresented_rejected(self):
        for q in ['é','🙂  e\u0301','Heading','Tail']:
            with self.subTest(q=q),self.assertRaisesRegex(ValueError,'NOT_PRESENTED'):self.resolve(q)
    def test_overlapping_and_nonoverlapping_ambiguity_rejected(self):
        for q in ['aa','a']:
            with self.subTest(q=q),self.assertRaisesRegex(ValueError,'AMBIGUOUS'):self.resolve(q)
    def test_source_hash_and_fragment_text_bound(self):
        self.sent['f0']=replace(self.sent['f0'],source_text_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'SOURCE_HASH'):self.resolve('🙂')
    def test_source_revision_and_unknown_fragment_rejected(self):
        with self.assertRaisesRegex(ValueError,'FRAGMENT_NOT_SENT'):resolve_quote({'fragment_id':'missing','quote':'🙂'},self.sent,self.sources)
        self.sent['f0']=replace(self.sent['f0'],revision='new')
        with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):self.resolve('🙂')
    def test_inserted_separator_cannot_be_cited(self):
        text=self.doc['canonical_text'];c=compose([piece(self.doc,0,7),piece(self.doc,len(text)-4,len(text))])
        sent,sources=prepare_fragments([c],self.docs)
        with self.assertRaisesRegex(ValueError,'NOT_PRESENTED'):resolve_quote({'fragment_id':'f0','quote':'Heading\n\nTail'},sent,sources)
    def test_offsets_from_model_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'CITATION_FIELDS'):resolve_quote({'fragment_id':'f0','quote':'🙂','start_cp':1},self.sent,self.sources)
    def test_dynamic_schema_required_nullable_and_nested_fields(self):
        schema=response_schema({'answer':'Utf8','count':'Nullable[Int64]','tags':{'kind':'List','item':'Utf8','max_length':5}})
        self.assertEqual(schema['type'],'ARRAY');self.assertTrue(schema['items']['properties']['count']['nullable'])
        self.assertEqual(set(schema['items']['required']),{'answer','count','tags','evidence'})
    def test_prompt_fallback_schema_is_inside_counted_body(self):
        b={**binding('E0'),'template_hash':digest(TEMPLATE)}
        req={'service_id':'E0','question':'Read','field_schema':{'answer':'Utf8'},'contexts':public_fragments(self.sent)}
        a=assemble_quote(req,b,TEMPLATE,str(uuid.uuid4()))
        self.assertNotIn('responseSchema',a['body']['generationConfig'])
        self.assertIn('response_contract',a['body']['contents'][0]['parts'][0]['text'])
    def test_schema_mode_cannot_claim_contents_only_measurement(self):
        b={**binding('E0'),'template_hash':digest(TEMPLATE)};req={'service_id':'E0','question':'Read','field_schema':{'answer':'Utf8'},'contexts':public_fragments(self.sent)}
        a=assemble_quote(req,b,TEMPLATE,str(uuid.uuid4()),profile='E_QUOTE_1')
        with self.assertRaisesRegex(PermissionError,'FULL_INPUT_MEASUREMENT'):ServiceClient.measure(SimpleNamespace(),a)
    def test_async_worker_mapping_preserves_business_answer_for_independent_verifier(self):
        class Semantic:
            evidence_profile='E_QUOTE_PROMPT_1';service_id='E0';mode='ENGINEERING_REPLAY'
            async def extract(inner,request):
                inner.request=request;return [{'answer':'deliberately unsupported','evidence':[{'fragment_id':'f0','quote':'🙂'}]}]
        events=[];self.docs.event=lambda k,v:events.append((k,v));s=Semantic()
        rows=asyncio.run(self.docs.dispatch('semantic_extract','fixed_e0',{'documents':[self.context]},
             {'field_schema':{'answer':'Utf8'},'context_budget':100},semantic=s,instance='n',scheduler=None,node={}))
        self.assertEqual(rows[0]['answer'],'deliberately unsupported')
        self.assertEqual(rows[0]['evidence'][0]['quote'],'🙂')
        self.assertTrue(any(k=='semantic_fragment_binding' for k,v in events))
    def test_rpc_transmits_profile_and_bound_request(self):
        class Service:
            service_id='E0';mode='ENGINEERING_REPLAY';evidence_profile='E_QUOTE_PROMPT_1';client=SimpleNamespace(binding=binding('E0'))
            async def extract(self,request):return [request]
        broker=SemanticBroker(Service())
        try:
            remote=RemoteSemantic(broker.connection());self.assertEqual(remote.evidence_profile,'E_QUOTE_PROMPT_1')
            self.assertEqual(asyncio.run(remote.extract({'public':'only'})),[{'public':'only'}])
        finally:broker.close()

class CapacityTests(unittest.TestCase):
    def setUp(self):
        test_recovery_epoch.RecoveryEpoch.setUp(self)
        # Keep every fixture archive inside this test's own private directory.
        self.state=TaskState(self.root/'state',self.policy,self.auth)
        self.scope=self.state.derive_scope(stage='B_INITIAL',identity=self.identity,limits={'G':24,'E':4,'COUNT':28},ceiling_microusd=15000000,expires_at=self.expiry)
        self.state.reserve(self.scope,'old','G',251904,self.identity);self.state.observe('old','SENT_UNCONFIRMED',{})
        self.amendment['scope_sha256']=digest(self.scope)
        with self.state.db() as db:self.amendment['prior_reservation_rows_sha256']=digest(db.execute('SELECT id,kind,amount,status FROM reservations ORDER BY id').fetchall())
        self.old_id=str(uuid.uuid4());self.amendment['planned_requests'][1]['request_id']=self.old_id
        test_recovery_epoch.RecoveryEpoch.install(self)
        test_recovery_epoch.RecoveryEpoch.dispatch(self,'count','COUNT','a'*64)
        self.index=RequestIndex(nl.archive_root(self.state));self.addCleanup(self.index.close)
        self.old=self.archive(self.old_id,'b'*64)
        gate=DispatchGate(self.state)
        with gate.locked():
            gate.admit(self.old_id,'E',body_hash='b'*64,scope_hash=digest(self.scope))
            self.state.reserve(self.scope,self.old_id,'E',100,self.identity);self.state.observe(self.old_id,'INFRA_FAILURE',{})
            gate.finish(self.old_id,self.old)
        self.original={'id':'f1','generations':[]};jobs=[];requests=[]
        task=neutral_example()['task']
        for model in range(6):
            for protocol in ('P0','P1'):
                g={'id':f'g{model}-{protocol}','generator':f'G{model}','protocol':protocol,'trial_label':17,'task_id':task['task_id'],'task_file_sha256':'c'*64}
                self.original['generations'].append(g);job={**g,'id':'next-live-001-request3-'+g['id']};jobs.append(job)
                ids={s:str(uuid.uuid4()) for s in ('logical','physical')}
                for stage in (['physical'] if protocol=='P0' else ['logical','physical']):
                    q={'category':'G','binding':binding(g['generator']),'task':task,'attempt_id':job['id'],'protocol':protocol,'stage':stage,'trial_label':17,
                       'request_id':ids[stage],'logical_request_id':ids['logical'],'public_task_file_sha256':'c'*64}
                    for kind,rid,cost in [('COUNT',str(uuid.uuid5(uuid.UUID(ids[stage]),'COUNT')),1),('G',ids[stage],100)]:
                        requests.append({'id':rid,'kind':kind,'amount':cost,'recipe':q,'logical_slot':job['id'],'model':g['generator'],'stage':stage})
        self.manifest={'revision':nl.PROFILE,'root_sha256':digest(self.auth),'capacity_retry_profile':'CAPACITY_RETRY_1','retry_pool':2,
           'user_authority_sha256':'d'*64,'block':{'generations':jobs},'requests':requests,'complete_packet_upper_microusd':2018}
        self.identity={**self.identity,'manifest':digest(self.manifest)}
        self.dev=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.identity,limits={'G':20,'COUNT':20},ceiling_microusd=2018,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
    def archive(self,rid,bodyhash,*,envelope=None,complete=True,headers=None):
        req={'request_id':rid,'binding_hash':'a'*64,'body_hash':bodyhash}
        self.index.begin(rid,req);raw=canonical(envelope or {'error':{'code':429,'status':'RESOURCE_EXHAUSTED','message':'capacity'}})
        write(self.index.root/rid/'response.raw',raw)
        r={'request_id':rid,'binding_hash':'a'*64,'status':'INFRA_FAILURE','http_status':429,'sent':True,'response_complete':complete,
           'response_headers':headers or {'date':'Mon, 28 Sep 2026 12:00:00 GMT'},'response_raw_hash':sha(raw)}
        self.index.record(rid,'INFRA_FAILURE',r);return r
    def install(self):nl.install(self.state,self.dev,self.manifest,old_capacity_result=self.old,original_block=self.original)
    def first(self):
        r=self.manifest['requests'][0];q=r['recipe'];a=assemble_request3(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],request_id=q['request_id'],trial_label=17)
        a.update(request_id=r['id'],body={k:v for k,v in a['body'].items() if k!='generationConfig'});a['body_hash']=digest(a['body']);return r,a
    def capacity(self,r,a,headers=None):
        nl.bind(self.state,a,r['kind'],self.index);gate=DispatchGate(self.state)
        result=self.archive(r['id'],a['body_hash'],headers=headers)
        with gate.locked():
            gate.admit(r['id'],r['kind'],body_hash=a['body_hash'],scope_hash=digest(self.dev));self.state.reserve(self.dev,r['id'],r['kind'],r['amount'],self.identity)
            self.state.observe(r['id'],'INFRA_FAILURE',{});gate.finish(r['id'],result)
        return result
    def test_migration_keeps_original_root_unknown_and_epoch(self):
        before=self.state.summary();self.install();after=self.state.summary()
        self.assertEqual(before['reservations'],after['reservations']);self.assertEqual(before['root_hash'],after['root_hash'])
        with self.state.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM recovery_epoch').fetchone()[0],1)
    def test_no_second_install_or_scope_reset(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'NO_RESET'):self.install()
    def test_complete_429_preserved_and_retry_uses_new_id_same_body(self):
        self.install();r,a=self.first();before=self.capacity(r,a);child=nl.retry_or_defer(self.state,self.index,r['id'])
        self.assertNotEqual(child['id'],r['id']);self.assertEqual(child['parent_request_id'],r['id'])
        self.assertEqual(nl.retry_or_defer(self.state,self.index,r['id']),child)
        with self.index.lock:self.assertEqual(json.loads(self.index.db.execute('SELECT result FROM requests WHERE id=?',(r['id'],)).fetchone()[0]),before)
        bad={**a,'request_id':child['id'],'body':{'contents':[]}};bad['body_hash']=digest(bad['body'])
        with self.assertRaisesRegex(PermissionError,'BODY_RECIPE'):nl.bind(self.state,bad,r['kind'],self.index)
    def test_partial_429_and_generated_usage_never_qualify(self):
        for envelope,complete in [({'error':{'code':429,'status':'RESOURCE_EXHAUSTED'}},False),({'error':{'code':429,'status':'RESOURCE_EXHAUSTED'},'usageMetadata':{}},True),({'error':{'code':429,'status':'RESOURCE_EXHAUSTED','details':[{'usage':1}]}},True)]:
            with self.subTest(envelope=envelope,complete=complete):self.assertFalse(nl.capacity_evidence(self.archive(str(uuid.uuid4()),'a'*64,envelope=envelope,complete=complete),self.index.root))
    def test_changed_archive_rejected(self):
        (self.index.root/self.old_id/'response.raw').write_bytes(b'{}');self.assertFalse(nl.capacity_evidence(self.old,self.index.root))
        with self.assertRaisesRegex(PermissionError,'OLD_CAPACITY_EVIDENCE'):self.install()
    def test_new_unknown_prevents_migration(self):
        with self.state.db() as db:db.execute("INSERT INTO reservations VALUES('new-unknown',NULL,'G',1,'SENT_UNCONFIRMED',NULL)")
        with self.assertRaisesRegex(PermissionError,'NEW_UNRESOLVED'):self.install()
    def test_held_retry_pool_must_fit_full_recovery(self):
        with self.state.db() as db:
            a=json.loads(db.execute('SELECT body FROM recovery_epoch').fetchone()[0]);a['maximum_additional_microusd']=2000;db.execute('UPDATE recovery_epoch SET body=?',(canonical(a).decode(),))
        with self.assertRaisesRegex(PermissionError,'SUBCAP'):self.install()
    def test_backoff_enforced_after_restart(self):
        self.install();r,a=self.first();self.capacity(r,a);child=nl.retry_or_defer(self.state,self.index,r['id']);a={**a,'request_id':child['id']};nl.bind(self.state,a,r['kind'],self.index)
        resumed=TaskState(self.state.root,self.policy,self.auth);gate=DispatchGate(resumed)
        with gate.locked(),self.assertRaisesRegex(PermissionError,'BACKOFF'):gate.admit(child['id'],r['kind'],body_hash=a['body_hash'],scope_hash=digest(self.dev))
    def test_two_retries_are_durable_then_only_model_deferred(self):
        self.install();r,a=self.first()
        for attempt in range(3):
            self.capacity(r,a);child=nl.retry_or_defer(self.state,self.index,r['id'])
            if attempt<2:
                self.assertEqual(child['attempt'],attempt+1)
                # Advance the test clock only; production deadlines stay durable.
                with self.state.db() as db:child['not_before']=0;nl._put(db,child)
                r=child;a={**a,'request_id':r['id']}
            else:self.assertIsNone(child)
        self.assertTrue(nl.model_deferred(self.state,'G0'));self.assertFalse(nl.model_deferred(self.state,'G1'))
        with self.state.db() as db:self.assertEqual(db.execute('SELECT status FROM dispatch_control').fetchone()[0],'OPEN')
    def test_retry_after_date_long_invalid_and_two_delays(self):
        now=datetime(2026,9,28,12,tzinfo=timezone.utc)
        self.assertEqual(nl.delay_seconds({},0),5);self.assertEqual(nl.delay_seconds({},1),15)
        self.assertEqual(nl.delay_seconds({'Retry-After':'Mon, 28 Sep 2026 12:00:20 GMT'},0,now=now),20)
        self.assertEqual(nl.delay_seconds({'retry-after':'301'},0),301)
        for v in ['-1','nan','garbage']:
            with self.subTest(v=v),self.assertRaises(ValueError):nl.delay_seconds({'retry-after':v},0)
    def test_long_wait_defers_model_and_invalid_wait_fuses(self):
        self.install();r,a=self.first();self.capacity(r,a,headers={'Retry-After':'301'});self.assertIsNone(nl.retry_or_defer(self.state,self.index,r['id']))
        self.assertTrue(nl.model_deferred(self.state,'G0'))
    def test_unregistered_changed_and_out_of_order_requests_rejected(self):
        self.install();r,a=self.first();gate=DispatchGate(self.state)
        with gate.locked(),self.assertRaisesRegex(PermissionError,'BINDING'):gate.admit(r['id'],r['kind'],body_hash=a['body_hash'],scope_hash=digest(self.dev))
        a['body']['contents']=[];a['body_hash']=digest(a['body'])
        with self.assertRaisesRegex(PermissionError,'BODY_RECIPE'):nl.bind(self.state,a,r['kind'],self.index)
    def test_new_uncertain_response_still_fuses(self):
        self.install();r,a=self.first();nl.bind(self.state,a,r['kind'],self.index);gate=DispatchGate(self.state)
        with gate.locked():
            gate.admit(r['id'],r['kind'],body_hash=a['body_hash'],scope_hash=digest(self.dev));self.state.reserve(self.dev,r['id'],r['kind'],r['amount'],self.identity)
            self.state.observe(r['id'],'SENT_UNCONFIRMED',{});gate.finish(r['id'],{'status':'SENT_UNCONFIRMED','request_id':r['id']})
        with self.state.db() as db:self.assertEqual(db.execute('SELECT status FROM dispatch_control').fetchone()[0],'FUSED')
    def test_concurrent_retry_admission_creates_exactly_one_child(self):
        self.install();r,a=self.first();self.capacity(r,a);children=[];errors=[]
        def admit():
            try:children.append(nl.retry_or_defer(self.state,self.index,r['id']))
            except Exception as exc:errors.append(str(exc))
        threads=[threading.Thread(target=admit) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(errors,[]);self.assertEqual(len(children),2);self.assertEqual(children[0]['id'],children[1]['id'])
    def test_invalid_retry_after_fuses_without_child(self):
        self.install();r,a=self.first();self.capacity(r,a,headers={'Retry-After':'bad'})
        self.assertIsNone(nl.retry_or_defer(self.state,self.index,r['id']))
        with self.state.db() as db:
            self.assertEqual(db.execute('SELECT status FROM dispatch_control').fetchone()[0],'FUSED')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM next_live_requests WHERE attempt>0').fetchone()[0],0)
    def test_client_real_archive_chain_reuses_count_and_never_repairs_200(self):
        from rcwg_api.vertex import Response
        from rcwg_full.auto2.services import ScopeBudget
        # Costs are fixture bounds only. Real prices are frozen separately.
        b=self.manifest['requests'][0]['recipe']['binding']
        b.update(count_method='PROVIDER_COUNT',price_snapshot={'input_usd_per_million':'0','output_usd_per_million':'0',
           'billing_policy':{'revision':'FULL001_BILLING_BOUND_1','rates_are_upper_bounds':True,'output_cap_includes_thinking':True,'count_request_microusd_upper':0}})
        self.identity['manifest']=digest(self.manifest)
        self.dev=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.identity,limits={'G':20,'COUNT':20},ceiling_microusd=2018,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
        self.install();row=self.manifest['requests'][1];q=row['recipe']
        request=assemble_request3(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],request_id=q['request_id'],trial_label=17)
        calls=[]
        class Transport:
            def send(inner,kind,body,rid,**kw):
                calls.append((kind,body,rid))
                if kind=='COUNT':return Response(200,canonical({'totalTokens':7}),{},1)
                if len(calls)==2:return Response(429,canonical({'error':{'code':429,'status':'RESOURCE_EXHAUSTED'}}),{},1)
                return Response(200,canonical({'modelVersion':'fixture-revision','candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'invalid model JSON'}]}}],
                    'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':9,'totalTokenCount':16}}),{},1)
        client=object.__new__(nl.NextLiveClient);client.binding=b;client.transport=Transport();client.index=self.index;client.mode='LIVE'
        client.budget=ScopeBudget(self.state,self.dev,lambda:self.identity,{'G':100,'COUNT':1});client.scope_hash=digest(self.dev);client.authorize_live=lambda:None
        with patch.object(nl,'delay_seconds',return_value=0):
            measured,failure=client.measure(request);self.assertIsNone(failure);result=client.call(request,'G',input_measurement=measured)
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['response']['text'],'invalid model JSON')
        self.assertEqual([x[0] for x in calls],['COUNT','G','G']);self.assertEqual(calls[1][1],calls[2][1]);self.assertNotEqual(calls[1][2],calls[2][2])
        self.assertEqual(client.call(request,'G',input_measurement=measured),result);self.assertEqual(len(calls),3)
