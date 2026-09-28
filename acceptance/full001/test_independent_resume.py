"""BOOT_ONLY finite recovery, cumulative ledger and dependency refusal tests."""
import json,unittest,uuid
from copy import deepcopy
from rcwg_full.evidence import digest,sha,canonical
from rcwg_full.auto2 import next_live as nl
from rcwg_full.auto2.independent_resume import install,eligible,PROFILE,isolation_for
from rcwg_full.auto2.budget_extension import reservation_snapshot
from rcwg_full.auto2.recovery import active_epoch
from rcwg_full.auto2.dispatch import DispatchGate
from rcwg_full.services.timeout3 import PROFILE as TIMEOUT
from rcwg_full.services.request4 import assemble_request4
import test_next_live2_review as fixtures

class IndependentResume(unittest.TestCase):
    archive=fixtures.ContinuationReview.archive
    scope4=fixtures.ContinuationReview.scope4
    append=fixtures.ContinuationReview.append
    def setUp(self):
        fixtures.ContinuationReview.setUp(self);self.mid=self.append()
        first=self.packet['requests'][:2];self.new_unknown=first[1]['id'];scope_id=digest(self.scope4())
        with self.state.db() as db:
            for r in first:
                status='COMPLETED' if r['kind']=='COUNT' else 'SENT_UNCONFIRMED'
                result={'status':status,'request_id':r['id'],'sent':None if r['kind']=='G' else True}
                row=nl._row(db,r['id']);row.update(state='DONE',result_sha256=digest(result));nl._put(db,row)
                db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',(r['id'],scope_id,r['kind'],r['amount'],status,'{}'))
                self.index.db.execute('INSERT INTO requests VALUES(?,?,?,?)',(r['id'],'BOOT_ONLY',status,json.dumps(result)))
            old={'status':'SENT_UNCONFIRMED','request_id':'old','sent':None}
            self.index.db.execute('INSERT INTO requests VALUES(?,?,?,?)',('old','BOOT_ONLY','SENT_UNCONFIRMED',json.dumps(old)))
            DispatchGate(self.state)._record(db,'FUSED',{'request_id':self.new_unknown,'result_sha256':digest(result)})
        ident=self.identity|{'manifest':self.mid,'source':'timeout3-source','dependencies':digest(TIMEOUT)}
        self.resume_scope=self.state.derive_scope(stage='B_DEVELOPMENT',identity=ident,limits={'G':19,'COUNT':19,'E':0},ceiling_microusd=1917,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
        with self.state.db() as db:
            allowed,excluded=eligible(db,self.index,self.mid,{'old',self.new_unknown});self.before=reservation_snapshot(db)
            self.decision={'revision':PROFILE,'user_text':'BOOT_ONLY explicitly preserve two unknowns and resume independent fresh slots','user_reference':'fixture://owner','root_sha256':digest(self.auth),'epoch_sha256':digest(active_epoch(db)),'prior_reservations_sha256':digest(self.before),'manifest_sha256':self.mid,'execution_identity':ident,'timeout_profile':TIMEOUT,'client_concurrency':1,'provider_active_count':None,'accept_unknown_provider_activity':True,'old_local_dispatchers_stopped':True,'offline_acceptance_pass':True,'new_unknown_stops':True,'families':['F2','F3'],'isolated_holds':{'old':251904,self.new_unknown:100},'isolated_result_hashes':{'old':digest(old),self.new_unknown:digest(result)},'allowed_request_ids':allowed,'excluded_logical_slots':excluded,'remaining_packet_upper_microusd':1917}
        self.decision['user_text_sha256']=sha(self.decision['user_text'].encode())
    def install(self):return install(self.state,self.index,self.resume_scope,self.decision)
    def bind_next(self):
        r=self.packet['requests'][2];q=r['recipe']
        actual=assemble_request4(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],request_id=q['request_id'],trial_label=17)
        body={k:v for k,v in actual['body'].items() if k!='generationConfig'}
        request=actual|{'request_id':r['id'],'body':body,'body_hash':digest(body)}
        nl.bind(self.state,request,'COUNT',self.index);return request
    def test_installs_once_preserves_epoch_holds_and_first_unknown(self):
        with self.state.db() as db:epoch=active_epoch(db);before=nl._row(db,self.new_unknown)
        self.install()
        with self.state.db() as db:
            self.assertEqual(reservation_snapshot(db),self.before);self.assertEqual(active_epoch(db),epoch);self.assertEqual(nl._row(db,self.new_unknown),before)
            self.assertEqual(isolation_for(db,self.mid,digest(self.resume_scope)),{'old',self.new_unknown})
        with self.assertRaisesRegex(PermissionError,'ALREADY_INSTALLED'):self.install()
    def test_next_fresh_slot_admitted_but_unknown_not(self):
        self.install();r=self.bind_next()
        with DispatchGate(self.state).locked() as gate:gate.admit(r['request_id'],'COUNT',body_hash=r['body_hash'],scope_hash=digest(self.resume_scope))
        with self.state.db() as db:
            with self.assertRaisesRegex(PermissionError,'ALLOWLIST'):nl.check(db,self.new_unknown,'G',None,digest(self.resume_scope))
    def test_new_unknown_fuses_without_expanding_isolation(self):
        self.install();r=self.bind_next()
        with self.state.db() as db:db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',('third',None,'G',1,'UNKNOWN','{}'))
        with DispatchGate(self.state).locked() as gate:
            with self.assertRaisesRegex(PermissionError,'UNRESOLVED'):gate.admit(r['request_id'],'COUNT',body_hash=r['body_hash'],scope_hash=digest(self.resume_scope))
    def test_no_authority_or_added_unknown_or_raised_ceiling(self):
        for key,value in [('user_text',''),('accept_unknown_provider_activity',False),('offline_acceptance_pass',False),('new_unknown_stops',False)]:
            saved=deepcopy(self.decision);self.decision[key]=value
            with self.subTest(key=key),self.assertRaises(PermissionError):self.install()
            self.decision=saved
        self.resume_scope=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.decision['execution_identity'],limits={'G':19,'COUNT':19,'E':0},ceiling_microusd=1918,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
        with self.assertRaisesRegex(PermissionError,'NO_BUDGET_RESET'):self.install()
    def test_attempted_index_entry_cannot_be_called_fresh(self):
        rid=self.decision['allowed_request_ids'][0]
        self.index.db.execute('INSERT INTO requests VALUES(?,?,?,?)',(rid,'BOOT_ONLY','PREPARED',None))
        with self.assertRaisesRegex(PermissionError,'ELIGIBLE_SET'):self.install()
    def test_tampered_unknown_result_refused(self):
        self.decision['isolated_result_hashes'][self.new_unknown]='0'*64
        with self.assertRaisesRegex(PermissionError,'EVIDENCE_CHANGED'):self.install()
    def test_new_pending_reservation_refused(self):
        with self.state.db() as db:
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',('third',None,'G',1,'RESERVED_BEFORE_IO','{}'))
            self.decision['prior_reservations_sha256']=digest(reservation_snapshot(db))
        with self.assertRaisesRegex(PermissionError,'ISOLATION_SET'):self.install()
    def test_known_unknown_cannot_be_recreated_with_new_uuid(self):
        self.install()
        with self.state.db() as db:self.assertFalse(nl.check(db,'new-unregistered-id','G',None,digest(self.resume_scope)))
    def test_other_scope_does_not_inherit_two_unknown_isolation(self):
        self.install()
        with self.state.db() as db:self.assertIsNone(isolation_for(db,self.mid,'different-scope'))
    def f3(self):
        from rcwg_full.auto2.continuation import append_packet
        block=json.loads(json.dumps(self.old_block).replace('F2','F3').replace('-f2-','-f3-'))
        packet=json.loads(json.dumps(self.packet).replace('F2','F3').replace('-f2-','-f3-'))
        mapping={r['id']:str(uuid.uuid5(uuid.UUID(r['id']),'BOOT_ONLY_F3')) for r in packet['requests'] if r['kind']=='G'}
        for r in packet['requests']:
            q=r['recipe'];prior=q['request_id'];q['request_id']=mapping[prior]
            q['logical_request_id']=mapping.get(q['logical_request_id'],str(uuid.uuid5(uuid.UUID(q['logical_request_id']),'BOOT_ONLY_F3')))
            r['id']=q['request_id'] if r['kind']=='G' else str(uuid.uuid5(uuid.UUID(q['request_id']),'COUNT'))
        packet.update(original_block_sha256=digest(block),previous_packet_sha256=self.mid,resume_decision_sha256=digest(self.decision))
        scope=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.decision['execution_identity']|{'manifest':digest(packet)},limits={'G':20,'COUNT':20,'E':0},ceiling_microusd=2018,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
        return append_packet(self.state,scope,packet,original_block=block),scope
    def test_f3_admitted_with_original_unknown_missing_but_fresh_f2_done(self):
        self.install()
        with self.state.db() as db:
            for rid in self.decision['allowed_request_ids']:
                row=nl._row(db,rid);row['state']='SKIPPED';row['BOOT_ONLY_terminal_fixture']=True;nl._put(db,row)
        mid,scope=self.f3()
        with self.state.db() as db:self.assertEqual(isolation_for(db,mid,digest(scope)),{'old',self.new_unknown})
    def test_f3_rejected_while_any_allowed_f2_slot_unfinished(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'INCOMPLETE'):self.f3()
