from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import unittest
from rcwg_full.campaign.store import CampaignStore
from rcwg_full.control.api import ControlAPI,Principal,VIEWS,offline_html
from rcwg_full.evidence import digest,write
from support import EvidenceDirectory
import io
import json

OWNER=Principal('owner','Owner');OPERATOR=Principal('op','Operator');VIEWER=Principal('viewer','Viewer');AUDITOR=Principal('audit','Auditor')


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.evidence=EvidenceDirectory('control-'+digest(self.id())[:16]);self.root=Path(self.evidence.name)
        self.store=CampaignStore(self.root/'index.sqlite3');self.api=ControlAPI(self.store)
    def tearDown(self):self.store.close();self.evidence.cleanup()
    def create(self):
        status,c=self.api.handle('POST','/campaigns',{'manifest_hash':'a'*64,'spec_hash':'b'*64,'mode':'ENGINEERING_REPLAY'},principal=OWNER,idempotency_key='create')
        self.assertEqual(status,200);return c
    def freeze(self,c):
        status,c=self.api.handle('POST',f'/campaigns/{c["id"]}/freeze',{'version':c['version'],'freeze_hash':'c'*64},principal=OWNER,idempotency_key='freeze')
        self.assertEqual(status,200);return c
    def workflow(self,c):
        self.api.register('workflow','wf',{'campaign_id':c['id'],'mode':'FORMAL','plan':{'nodes':[]},'visibility':'PUBLIC'})
        self.store.register([{'slot_id':'slot','campaign_id':c['id'],'ledger_role':'PRIMARY','slot_kind':'execution'}])

    def test_idempotency_cas_and_no_duplicate_queue(self):
        c=self.freeze(self.create());self.workflow(c);path=f'/campaigns/{c["id"]}/runs'
        body={'version':c['version'],'slot_id':'slot','workflow_hash':'wf'}
        first=self.api.handle('POST',path,body,principal=OPERATOR,idempotency_key='run')
        self.assertEqual(first,self.api.handle('POST',path,body,principal=OPERATOR,idempotency_key='run'))
        self.assertEqual(self.api.handle('POST',path,{**body,'slot_id':'changed'},principal=OPERATOR,idempotency_key='run')[0],409)
        self.assertEqual(self.api.handle('POST',path,body,principal=OPERATOR,idempotency_key='different')[0],409)
        self.assertEqual(len(self.api.rows('run_attempt',c['id'])),1)
        run=first[1];self.assertEqual(run['status'],'QUEUED')
        result=self.api.handle('POST',f'/runs/{run["id"]}/cancel',{'version':0},principal=OPERATOR,idempotency_key='cancel')
        self.assertTrue(result[1]['cancel_requested']);self.assertEqual(result[1]['status'],'QUEUED')
        self.assertEqual(self.api.handle('POST',f'/runs/{run["id"]}/cancel',{'version':0},principal=OPERATOR,idempotency_key='cancel-stale')[0],409)

    def test_role_cannot_be_supplied_in_payload_or_forged_header(self):
        c=self.create();path=f'/campaigns/{c["id"]}/freeze';body={'version':0,'freeze_hash':'c'*64}
        self.assertEqual(self.api.handle('POST',path,body,principal=VIEWER,idempotency_key='denied')[0],403)
        self.assertEqual(self.api.handle('POST',path,{**body,'actor_role':'Owner'},principal=OWNER,idempotency_key='fields')[0],400)
        self.assertEqual(self.api.handle('POST',path,body,principal={'role':'Owner'},idempotency_key='forged')[0],403)

    def test_private_evidence_stays_hidden_before_complete_audit(self):
        c=self.freeze(self.create());self.api.register('metric_summary','m',{'campaign_id':c['id'],'gold':'secret sentinel','score':0.1})
        for actor in [OWNER,OPERATOR,VIEWER,AUDITOR]:
            _,value=self.api.handle('GET',f'/campaigns/{c["id"]}/export',{},principal=actor)
            self.assertNotIn('secret sentinel',str(value));self.assertNotIn('score',str(value))
        body={'version':c['version'],'receipt':{'actor_id':'audit','actor_role':'Auditor'}}
        self.assertEqual(self.api.handle('POST',f'/campaigns/{c["id"]}/unseal',body,principal=AUDITOR,idempotency_key='unseal')[0],403)

    def test_fork_is_separate_manual_identity_and_parent_immutable(self):
        c=self.freeze(self.create());self.workflow(c);before=self.api.get('workflow','wf')
        status,fork=self.api.handle('POST','/workflows/wf/fork',{'version':0,'plan':{'nodes':['manual']}},principal=OPERATOR,idempotency_key='fork')
        self.assertEqual(status,200);self.assertEqual(fork['mode'],'MANUAL_DEBUG');self.assertIsNone(fork['campaign_id'])
        self.assertEqual(before,self.api.get('workflow','wf'))
        self.assertEqual(self.api.handle('POST',f'/campaigns/{c["id"]}/runs',{'version':1,'slot_id':'slot','workflow_hash':fork['id']},principal=OPERATOR,idempotency_key='mix')[0],403)

    def test_nine_views_and_html_escape(self):
        c=self.create();self.api.register('workflow','w',{'campaign_id':c['id'],'plan':'<script>bad()</script>','visibility':'PUBLIC'})
        status,views=self.api.handle('GET',f'/campaigns/{c["id"]}/views',{},principal=VIEWER)
        self.assertEqual(status,200);self.assertEqual(set(views['views']),set(VIEWS))
        page=offline_html(views);self.assertNotIn(b'<script>',page);self.assertIn(b'&lt;script&gt;',page)
        write(self.root/'views.json',views);write(self.root/'views.html',page)

    def test_concurrent_idempotency_has_one_campaign(self):
        path=self.root/'concurrent.sqlite3'
        def call(_):
            store=CampaignStore(path)
            try:return ControlAPI(store).handle('POST','/campaigns',{'manifest_hash':'a'*64,'spec_hash':'b'*64,'mode':'ENGINEERING_REPLAY'},principal=OWNER,idempotency_key='same')
            finally:store.close()
        # Initialize schema once; transactions still race across connections.
        initial=CampaignStore(path);initial.close()
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(call,range(8)))
        self.assertTrue(all(r==results[0] for r in results));self.assertEqual(results[0][0],200)

    def connect_runner(self):
        from test_campaign_runner import slots
        from rcwg_full.campaign.runner import CampaignRunner
        c=self.freeze(self.create());calls=[]
        def handle(slot,attempt,dependencies,directory):
            calls.append(slot['slot_id']);return {'status':'COMPLETED','fixture_only':True}
        runner=CampaignRunner(self.root/'run',slots(),manifest_hash=c['manifest_hash'],spec_hash=c['spec_hash'],
            mode=c['mode'],generate=handle,execute=handle,store=self.store)
        self.api.attach_runner(c['id'],runner);self.api.attach_runner(c['id'],runner)
        self.api.register('workflow','wf',{'campaign_id':c['id'],'mode':c['mode'],'plan':{},'visibility':'PUBLIC'})
        return c,runner,calls

    def queue(self,c,slot):
        status,value=self.api.handle('POST',f'/campaigns/{c["id"]}/runs',
            {'version':c['version'],'slot_id':slot,'workflow_hash':'wf'},principal=OPERATOR,idempotency_key='queue-'+slot)
        self.assertEqual(status,200);return value

    def test_actual_outbox_dispatch_waits_for_dependencies_and_never_duplicates(self):
        c,runner,calls=self.connect_runner();child=self.queue(c,'exec-0')
        self.assertEqual(self.api.dispatch_one(c['id'],runner)['status'],'WAITING_DEPENDENCIES')
        self.assertEqual(calls,[]);self.queue(c,'generation')
        generated=self.api.dispatch_one(c['id'],runner);executed=self.api.dispatch_one(c['id'],runner)
        self.assertEqual(calls,['generation','exec-0']);self.assertEqual(generated['run']['status'],'COMPLETED')
        self.assertEqual(executed['evidence_index']['status'],'INDEXED_PRIVATE')
        self.assertGreaterEqual(executed['evidence_index']['files'],2)
        self.assertEqual(executed['run']['id'],child['id']);self.assertIsNotNone(executed['run']['attempt_id'])
        self.assertEqual(self.api.dispatch_one(c['id'],runner)['status'],'NO_NEW_ACTION')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],2)
        status,reconciled=self.api.handle('GET','/requests/queue-exec-0',{},principal=OPERATOR)
        self.assertEqual(status,200);self.assertEqual(reconciled['response']['id'],child['id']);self.assertEqual(reconciled['new_actions'],0)
        self.assertEqual(self.api.handle('GET','/requests/queue-exec-0',{},principal=VIEWER)[0],404)
        runner.close();self.assertEqual(self.store.slot('exec-1')['status'],'NOT_RUN')

    def test_cancelled_queued_run_never_claims_or_falls_into_resume(self):
        c,runner,calls=self.connect_runner();run=self.queue(c,'exec-0')
        self.api.handle('POST',f'/runs/{run["id"]}/cancel',{'version':0},principal=OPERATOR,idempotency_key='cancel-before')
        result=self.api.dispatch_one(c['id'],runner)
        self.assertEqual(result['run']['status'],'CANCELLED');self.assertEqual(calls,[])
        self.assertIsNone(result['run']['attempt_id']);self.assertEqual(self.store.slot('exec-0')['status'],'CANCELLED')
        records=self.store.observations(c['mode']);self.assertFalse(records[0]['physical_attempt'])
        runner.run();self.assertNotIn('exec-0',calls);runner.close()

    def test_wsgi_parsing_and_trusted_authentication(self):
        from rcwg_full.control.wsgi import application
        app=application(self.api,lambda env:VIEWER)
        def call(raw,**overrides):
            env={'REQUEST_METHOD':'POST','PATH_INFO':'/campaigns','CONTENT_TYPE':'application/json',
                 'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_IDEMPOTENCY_KEY':'wsgi','HTTP_ACTOR_ROLE':'Owner',**overrides}
            response=[];body=b''.join(app(env,lambda status,headers:response.append((status,headers))))
            return response[0][0],json.loads(body)
        self.assertTrue(call(b'{"role":"Owner"}')[0].startswith('403'))
        self.assertTrue(call(b'{"a":1,"a":2}')[0].startswith('400'))
        self.assertTrue(call(b'{}',CONTENT_LENGTH='131073')[0].startswith('400'))
        self.assertTrue(call(b'{}',CONTENT_LENGTH='3')[0].startswith('400'))

    def test_concurrent_wsgi_requests_use_independent_sqlite_connections(self):
        from rcwg_full.control.wsgi import application
        from rcwg_full.evidence import canonical
        app=application(self.api,lambda env:OWNER)
        raw=canonical({'manifest_hash':'a'*64,'spec_hash':'b'*64,'mode':'ENGINEERING_REPLAY'})
        def call(_):
            response=[];body=b''.join(app({'REQUEST_METHOD':'POST','PATH_INFO':'/campaigns','CONTENT_TYPE':'application/json',
                'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_IDEMPOTENCY_KEY':'threaded','wsgi.multithread':True},
                lambda status,headers:response.append(status)))
            return response[0],json.loads(body)
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(call,range(8)))
        self.assertTrue(all(r==results[0] for r in results));self.assertEqual(results[0][0],'200 OK')

    def test_crashed_dispatch_claim_does_not_expire_into_duplicate(self):
        c,runner,calls=self.connect_runner();self.queue(c,'generation')
        def interrupted(*args):calls.append('interrupted');raise SystemExit('controller exit fixture')
        runner.generate=interrupted
        with self.assertRaises(SystemExit):self.api.dispatch_one(c['id'],runner)
        result=self.api.dispatch_one(c['id'],runner)
        self.assertEqual(result['status'],'NO_NEW_ACTION');self.assertEqual(result['reconcile_required'],['generation'])
        self.assertEqual(calls,['interrupted']);runner.close()

    def test_actual_private_journal_and_lifetime_are_indexed_and_tampering_is_rejected(self):
        from rcwg_full.runtime.events import Journal
        from rcwg_full.control.indexing import index_attempt
        from rcwg_full.evidence import sha,read
        c,runner,calls=self.connect_runner()
        def action(slot,attempt,deps,directory):
            root=directory/'native';worker=root/'worker';worker.mkdir(parents=True)
            journal=Journal(worker/'events.jsonl',attempt)
            journal.append('node_started',{'operator':'fixture','secret_label':'private sentinel'},node_instance='root/a#1')
            journal.append('buffer_created',{'buffer_id':'fixture-buffer','capacity_bytes':64,'storage_kind':'arrow_memory'})
            journal.append('buffer_released',{'buffer_id':'fixture-buffer'})
            journal.append('node_finished',{},node_instance='root/a#1',status='COMPLETED');journal.close()
            write(root/'report.json',{'verification':{'status':'PASS','private_annotation':'sentinel'}})
            write(root/'seal.json',{'status':'SEALED','run_id':attempt,'files':{p.relative_to(root).as_posix():sha(read(p)) for p in root.rglob('*') if p.is_file()}})
            return {'status':'COMPLETED','protocol_fixture_only':True}
        runner.generate=action;run=self.queue(c,'generation');result=self.api.dispatch_one(c['id'],runner)
        self.assertEqual(result['evidence_index']['nodes'],1);self.assertEqual(result['evidence_index']['buffers'],1)
        _,events=self.api.handle('GET',f'/runs/{run["id"]}/events',{},principal=OPERATOR)
        self.assertEqual(len(events['items']),1);self.assertNotIn('private sentinel',str(events))
        self.assertEqual(events['items'][0]['status'],'SEALED_PRIVATE')
        self.assertTrue(any(r.get('kind')=='BUFFER_LIFETIME' for r in self.api.rows('artifact',c['id'])))
        index_attempt(self.api,c['id'],run['id'],runner,'generation')
        attempt=self.store.slot('generation')['active_attempt'];path=runner.root/'attempts'/attempt/'native/worker/events.jsonl'
        path.write_bytes(read(path)+b'bad')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'):index_attempt(self.api,c['id'],run['id'],runner,'generation')
        runner.close()
