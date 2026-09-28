"""Independent BOOT_ONLY candidate tests. No cloud calls or real account state."""
from copy import deepcopy
import json
import unittest
import uuid
from rcwg_full.evidence import canonical, digest
from rcwg_full.services.request3 import assemble_request3, neutral_example
from rcwg_full.services.request4 import assemble_request4, LOGICAL_KEYS
from rcwg_full.services.requests import parse_final
from rcwg_full.services.client import ServiceClient, RequestIndex, generate
from rcwg_spec.generation import validate_logical_contract
from rcwg_full.auto2 import next_live as nl
from rcwg_full.auto2.budget_extension import (
    install_extension, effective_recovery_cap, reservation_snapshot,
)
from rcwg_full.verification.semantic import verify_semantics, evidence_metrics
from test_services import binding, Replay, Counter
import test_recovery_epoch
import tempfile
from pathlib import Path


class Request4Review(unittest.TestCase):
    def setUp(self):
        self.example=neutral_example()
        self.kw=dict(protocol='P0',stage='physical',attempt_id='new-fixture',
                     request_id=str(uuid.uuid4()),trial_label=17)
    def request(self,**kwargs):
        return assemble_request4(self.example['task'],binding(),**(self.kw|kwargs))
    def test_physical_root_is_actual_schema(self):
        r=self.request();parts=r['body']['systemInstruction']['parts']
        contract=json.loads(parts[-1]['text'].split('\n',1)[1])
        self.assertEqual(set(contract['required_root_keys']),{'ir_version','task_id','external_inputs','nodes','result'})
        rules=json.loads(parts[2]['text'])
        self.assertNotIn('wire_schema',rules);self.assertNotIn('stage_contracts',rules)
        self.assertEqual(len(rules['operators']),32)
        self.assertEqual(sum(len(c['implementations']) for c in rules['operators']),56)
    def test_logical_exact_seven_keys_and_no_ambiguous_stage_wrappers(self):
        r=self.request(protocol='P1',stage='logical');parts=r['body']['systemInstruction']['parts']
        contract=json.loads(parts[-1]['text'].split('\n',1)[1])
        self.assertEqual(contract['required_root_keys'],list(LOGICAL_KEYS))
        self.assertEqual(contract['allowed_root_keys'],list(LOGICAL_KEYS))
        self.assertNotIn('under wire_schema',parts[0]['text'])
        self.assertNotIn('return the logical_contract fields in stage_contracts',parts[0]['text'])
    def test_parser_still_rejects_old_logical_wrapper(self):
        value={k:['Public explanation'] for k in LOGICAL_KEYS}
        self.assertEqual(parse_final(canonical(value),'logical')['value'],value)
        with self.assertRaises(ValueError):parse_final(canonical({'logical_contract':value}),'logical')
    def test_compiler_still_rejects_old_workflow_wrapper(self):
        from rcwg_full.compiler import FullCompiler
        proof=FullCompiler().compile(self.example['task'],{'wire_schema':self.example['workflow']})
        self.assertNotEqual(proof['status'],'IR_VALIDATED')
    def test_decoding_limits_input_and_old_profile_unchanged(self):
        before=assemble_request3(self.example['task'],binding(),**self.kw)
        new=self.request();after=assemble_request3(self.example['task'],binding(),**self.kw)
        self.assertEqual(before,after)
        self.assertEqual(before['body']['generationConfig'],new['body']['generationConfig'])
        self.assertEqual(before['body']['contents'],new['body']['contents'])
        self.assertEqual(new['max_input_tokens'],12288);self.assertEqual(new['max_output_tokens'],16384)
        self.assertEqual(new['body_hash'],digest(new['body']))
        self.assertNotEqual(before['body_hash'],new['body_hash'])
    def test_p1_physical_requires_same_real_logical_contract(self):
        logical={k:['public'] for k in LOGICAL_KEYS}
        r=self.request(protocol='P1',stage='physical',logical=logical)
        public=json.loads(r['body']['contents'][0]['parts'][0]['text'])
        self.assertEqual(public['completed_logical_contract'],logical)
        self.assertEqual(r['max_output_tokens'],12288)
        with self.assertRaises(ValueError):self.request(protocol='P1',stage='physical',logical={'logical_contract':logical})
    def test_different_models_get_identical_public_body(self):
        a=self.request()
        b=assemble_request4(self.example['task'],binding('G5'),**self.kw)
        self.assertEqual(a['body'],b['body'])
    def test_client_generate_uses_opt_in_profile_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            index=RequestIndex(Path(temp)/'requests')
            try:
                wire=Replay([json.dumps(self.example['workflow'])])
                client=ServiceClient(binding(),wire,None,index)
                r=generate(self.example['task'],{'protocol':'P0','trial_label':17,'request_profile':'FULL001_REQUEST_4'},client,'fresh',local_counter=Counter())
                self.assertEqual(r['status'],'COMPLETED')
                self.assertIn('FULL001_REQUEST_4',wire.calls[0]['body']['systemInstruction']['parts'][0]['text'])
            finally:index.close()


class BudgetExtensionReview(unittest.TestCase):
    def setUp(self):
        test_recovery_epoch.RecoveryEpoch.setUp(self)
        test_recovery_epoch.RecoveryEpoch.install(self)
    def args(self):
        with self.state.db() as db:
            return dict(user_text='BOOT_ONLY: allow modest recovery budget increase, keep root 100.',
                user_message_reference='fixture://test-owner-message',expected_root_sha256=digest(self.auth),
                expected_epoch_sha256=digest(self.amendment),expected_reservations_sha256=digest(reservation_snapshot(db)))
    def add_fixture_cost(self,amount,kind='HISTORY',status='HISTORICAL_HOLD',rid='fixture-cost'):
        with self.state.db() as db:
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',(rid,None,kind,amount,status,'{"BOOT_ONLY":true}'))
    def test_original_five_dollar_cap_remains_before_opt_in(self):
        with self.state.db() as db:self.assertEqual(effective_recovery_cap(db,self.amendment),5000000)
    def test_actual_report_arithmetic_can_admit_next_full_f2_after_extension(self):
        self.add_fixture_cost(3_526_690)
        with self.state.db() as db:
            with self.assertRaisesRegex(PermissionError,'RECOVERY_SUBCAP'):nl._limits(self.state,db,3606142)
        install_extension(self.state,**self.args())
        with self.state.db() as db:
            cap=effective_recovery_cap(db,self.amendment)
            total=db.execute('SELECT SUM(amount) FROM reservations').fetchone()[0]
            self.assertEqual(cap-(total-self.amendment['baseline_reserved_microusd']),11473310)
            nl._limits(self.state,db,3606142)
    def test_old_epoch_root_unknown_and_reservations_byte_values_retained(self):
        with self.state.db() as db:
            before=reservation_snapshot(db);root=db.execute('SELECT * FROM root').fetchall();epoch=db.execute('SELECT * FROM recovery_epoch').fetchall()
        install_extension(self.state,**self.args())
        with self.state.db() as db:
            self.assertEqual(reservation_snapshot(db),before)
            self.assertEqual(db.execute('SELECT * FROM root').fetchall(),root)
            self.assertEqual(db.execute('SELECT * FROM recovery_epoch').fetchall(),epoch)
            self.assertEqual(db.execute("SELECT amount,status FROM reservations WHERE id='old'").fetchone(),(251904,'SENT_UNCONFIRMED'))
    def test_idempotent_install_does_not_reset_spending(self):
        args=self.args();one=install_extension(self.state,**args)
        self.add_fixture_cost(200000)
        two=install_extension(self.state,**args)
        self.assertEqual(one,two)
        self.assertEqual(self.state.summary()['reserved_microusd'],1451904)
    def test_rebinding_to_another_user_message_is_rejected(self):
        args=self.args();install_extension(self.state,**args)
        with self.assertRaisesRegex(PermissionError,'ALREADY_INSTALLED'):install_extension(self.state,**(args|{'user_text':'other'}))
    def test_changed_snapshot_cannot_be_approved(self):
        args=self.args();self.add_fixture_cost(1)
        with self.assertRaisesRegex(PermissionError,'HISTORY_CHANGED'):install_extension(self.state,**args)
    def test_new_unknown_prevents_install(self):
        self.add_fixture_cost(1,'G','SENT_UNCONFIRMED')
        with self.assertRaisesRegex(PermissionError,'NEW_UNRESOLVED'):install_extension(self.state,**self.args())
    def test_pending_reservation_prevents_install(self):
        self.add_fixture_cost(1,'G','RESERVED_BEFORE_IO')
        with self.assertRaisesRegex(PermissionError,'PENDING_RESERVATION'):install_extension(self.state,**self.args())
    def test_active_and_fused_dispatch_cannot_be_reopened_by_budget(self):
        for status in ['ACTIVE','FUSED']:
            with self.subTest(status=status):
                with self.state.db() as db:db.execute('UPDATE dispatch_control SET status=?',(status,))
                with self.assertRaisesRegex(PermissionError,'NOT_QUIESCENT'):install_extension(self.state,**self.args())
    def test_root_ceiling_unchanged_even_when_subcap_available(self):
        install_extension(self.state,**self.args())
        # Test the real root guard with a large historic hold outside this epoch's
        # baseline using a minimal fake state authority in this isolated DB.
        with self.state.db() as db:
            old=self.state.authority['ceiling_microusd'];self.state.authority['ceiling_microusd']=11_251_914
            try:
                with self.assertRaisesRegex(PermissionError,'ROOT_BUDGET'):nl._limits(self.state,db,11)
            finally:self.state.authority['ceiling_microusd']=old
    def test_amendment_tampering_rejected(self):
        install_extension(self.state,**self.args())
        with self.state.db() as db:db.execute("UPDATE recovery_budget_extensions SET body='{}'")
        with self.state.db() as db:
            with self.assertRaisesRegex(PermissionError,'EXTENSION_CHANGED'):effective_recovery_cap(db,self.amendment)
    def test_signed_hash_is_not_enough_to_raise_past_fifteen(self):
        value=install_extension(self.state,**self.args());value['new_cap_microusd']=15000001
        with self.state.db() as db:db.execute('UPDATE recovery_budget_extensions SET body=?,sha256=?',(canonical(value).decode(),digest(value)))
        with self.state.db() as db:
            with self.assertRaisesRegex(PermissionError,'EXTENSION_BINDING'):effective_recovery_cap(db,self.amendment)
    def test_missing_user_message_rejected(self):
        with self.assertRaisesRegex(PermissionError,'USER_MESSAGE'):install_extension(self.state,**(self.args()|{'user_text':''}))
    def test_admission_still_requires_registered_requests(self):
        install_extension(self.state,**self.args())
        with self.assertRaisesRegex(PermissionError,'NOT_PREREGISTERED'):
            self.state.reserve(self.scope,'random','G',1,self.identity)


class EvidenceSufficiencyReview(unittest.TestCase):
    def setUp(self):
        self.span={'document_id':'BOOT_ONLY-document','revision':'v1','start_cp':0,'end_cp':12}
        self.obligations=[{'id':'q','acceptable_witness_sets':[[self.span]]}]
    def test_short_quote_can_have_perfect_precision_but_zero_full_witness_recall(self):
        got=evidence_metrics([self.span|{'end_cp':4}],self.obligations)
        self.assertEqual(got['precision'],1);self.assertEqual(got['recall'],0)
    def test_complete_quote_matches_original_scorer(self):
        got=evidence_metrics([self.span],self.obligations)
        self.assertEqual(got['precision'],1);self.assertEqual(got['recall'],1)
    def test_complete_quote_does_not_rescue_wrong_critical_answer(self):
        recipe={'fields':{'answer':{'acceptable_values':['true answer'],'critical':True}},'evidence_obligations':self.obligations}
        got=verify_semantics({'fields':{'answer':'wrong answer'},'evidence':[self.span]},recipe)
        self.assertEqual(got['status'],'FAIL');self.assertIn('answer',got['critical_failures'])
    def test_out_of_witness_quote_is_not_credit(self):
        got=evidence_metrics([self.span|{'start_cp':20,'end_cp':25}],self.obligations)
        self.assertEqual(got['precision'],0);self.assertEqual(got['recall'],0)


# Registration tests use in-memory/sandbox BOOT_ONLY terminal fixtures, not
# invented real API completions. No real ledger is opened by this suite.
import test_next_live
from rcwg_full.auto2.continuation import append_packet, PROFILE as PACKET_PROFILE

class ContinuationReview(unittest.TestCase):
    archive = test_next_live.CapacityTests.archive
    def setUp(self):
        test_next_live.CapacityTests.setUp(self)
        # The inherited fixture task is deliberately small. Rename its public
        # identity consistently before installation so it represents family F1.
        for g in self.original['generations']:g['task_id']='F1-01-b0-C0'
        for g in self.manifest['block']['generations']:g['task_id']='F1-01-b0-C0'
        for r in self.manifest['requests']:r['recipe']['task']['task_id']='F1-01-b0-C0'
        self.identity=self.identity|{'manifest':digest(self.manifest)}
        self.dev=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.identity,limits={'G':20,'COUNT':20},ceiling_microusd=2018,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
        nl.install(self.state,self.dev,self.manifest,old_capacity_result=self.old,original_block=self.original)
        with self.state.db() as db:
            for rid,body in db.execute('SELECT id,body FROM next_live_requests').fetchall():
                value=json.loads(body);value['state']='DONE';value['BOOT_ONLY_terminal_fixture']=True
                db.execute('UPDATE next_live_requests SET body=? WHERE id=?',(canonical(value).decode(),rid))
        self.before=self.manifest
        self.old_block={'id':'dev-F2-01-b0-C0','generations':[]};jobs=[];requests=[]
        task=neutral_example()['task'];task['task_id']='F2-01-b0-C0'
        for i in range(6):
            for p in ('P0','P1'):
                old={'id':f'original-f2-g{i}-{p}','generator':f'G{i}','protocol':p,'task_id':task['task_id'],'trial_label':17,'task_file_sha256':digest(task)}
                self.old_block['generations'].append(old);job=old|{'id':'next-live-002-request4-'+old['id']};jobs.append(job)
                ids={s:str(uuid.uuid4()) for s in ('logical','physical')}
                for stage in (['physical'] if p=='P0' else ['logical','physical']):
                    recipe={'category':'G','request_profile':'FULL001_REQUEST_4','binding':binding(f'G{i}'),'task':deepcopy(task),
                        'attempt_id':job['id'],'protocol':p,'stage':stage,'trial_label':17,'request_id':ids[stage],
                        'logical_request_id':ids['logical'],'public_task_file_sha256':digest(task)}
                    for kind,rid,amount in [('COUNT',str(uuid.uuid5(uuid.UUID(ids[stage]),'COUNT')),1),('G',ids[stage],100)]:
                        requests.append({'id':rid,'kind':kind,'amount':amount,'recipe':deepcopy(recipe),'logical_slot':job['id'],'model':f'G{i}','stage':stage})
        self.packet={'revision':PACKET_PROFILE,'root_sha256':digest(self.auth),'measurement_profile':'SERVICE_ONLY',
            'request_profile':'FULL001_REQUEST_4','original_block_sha256':digest(self.old_block),'previous_packet_sha256':digest(self.before),
            'capacity_retry_profile':'CAPACITY_RETRY_1','retry_pool':2,'block':{'generations':jobs},'requests':requests,
            'complete_packet_upper_microusd':2018}
    def scope4(self):
        return self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.identity|{'manifest':digest(self.packet)},
            limits={'G':20,'COUNT':20},ceiling_microusd=2018,expires_at=self.expiry,capacity_profile='CAPACITY_RETRY_1')
    def append(self):return append_packet(self.state,self.scope4(),self.packet,original_block=self.old_block)
    def test_append_then_exact_count_recipe_binds_without_network(self):
        mid=self.append();r=self.packet['requests'][0];q=r['recipe']
        actual=assemble_request4(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],request_id=q['request_id'],trial_label=17)
        body={k:v for k,v in actual['body'].items() if k!='generationConfig'}
        counted=actual|{'request_id':r['id'],'body':body,'body_hash':digest(body)}
        nl.bind(self.state,counted,'COUNT',self.index)
        with self.state.db() as db:
            self.assertTrue(nl.check(db,r['id'],'COUNT',digest(body),digest(self.scope4()),1))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM next_live_manifests').fetchone()[0],2)
            self.assertEqual(nl._row(db,r['id'])['manifest'],mid)
    def test_request3_bytes_cannot_pass_request4_recipe(self):
        self.append();r=self.packet['requests'][0];q=r['recipe']
        actual=assemble_request3(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],request_id=q['request_id'],trial_label=17)
        body={k:v for k,v in actual['body'].items() if k!='generationConfig'}
        counted=actual|{'request_id':r['id'],'body':body,'body_hash':digest(body)}
        with self.assertRaisesRegex(PermissionError,'BODY_RECIPE'):nl.bind(self.state,counted,'COUNT',self.index)
    def test_original_request_rows_never_changed_and_same_scope_idempotent(self):
        with self.state.db() as db:before=db.execute('SELECT * FROM next_live_requests').fetchall()
        scope=self.scope4();a=append_packet(self.state,scope,self.packet,original_block=self.old_block)
        b=append_packet(self.state,scope,self.packet,original_block=self.old_block)
        self.assertEqual(a,b)
        with self.state.db() as db:
            after={row[0]:row for row in db.execute('SELECT * FROM next_live_requests')}
        for row in before:self.assertEqual(after[row[0]],row)
    def test_previous_incomplete_prevents_append(self):
        with self.state.db() as db:
            rid,body=db.execute('SELECT id,body FROM next_live_requests LIMIT 1').fetchone();value=json.loads(body);value['state']='PENDING'
            db.execute('UPDATE next_live_requests SET body=? WHERE id=?',(canonical(value).decode(),rid))
        with self.assertRaisesRegex(PermissionError,'PREVIOUS_PACKET_INCOMPLETE'):self.append()
    def test_missing_model_or_stage_prevents_append(self):
        self.packet['requests'].pop()
        with self.assertRaisesRegex(PermissionError,'REQUEST_COUNT'):self.append()
    def test_stage_order_cannot_change(self):
        self.packet['requests'][0],self.packet['requests'][1]=self.packet['requests'][1],self.packet['requests'][0]
        with self.assertRaisesRegex(PermissionError,'ORDER_OR_RATE'):self.append()
    def test_fused_dispatch_cannot_be_unblocked_by_registration(self):
        with self.state.db() as db:db.execute("UPDATE dispatch_control SET status='FUSED'")
        with self.assertRaisesRegex(PermissionError,'FUSED'):self.append()
    def test_capacity_deferral_is_packet_scoped_for_new_controller(self):
        with self.state.db() as db:
            rid,body=db.execute('SELECT id,body FROM next_live_requests LIMIT 1').fetchone()
            value=json.loads(body);value['state']='DEFERRED';model=value['model']
            db.execute('UPDATE next_live_requests SET body=? WHERE id=?',(canonical(value).decode(),rid))
        mid=self.append()
        self.assertTrue(nl.model_deferred(self.state,model))
        self.assertFalse(nl.model_deferred(self.state,model,manifest_id=mid))
        self.assertTrue(nl.model_deferred(self.state,model,manifest_id=digest(self.before)))

    def test_next_packet_must_follow_previous_family(self):
        self.old_block['generations'][0]['task_id']='F3-01-b0-C0'
        # Alter all public identities consistently; still forbidden because F2
        # must follow the already completed F1 block.
        for g in self.old_block['generations']:g['task_id']='F3-01-b0-C0'
        for g in self.packet['block']['generations']:g['task_id']='F3-01-b0-C0'
        for r in self.packet['requests']:r['recipe']['task']['task_id']='F3-01-b0-C0'
        self.packet['original_block_sha256']=digest(self.old_block)
        with self.assertRaisesRegex(PermissionError,'FROZEN_FAMILY_ORDER'):self.append()

if __name__=='__main__':unittest.main(verbosity=2)
