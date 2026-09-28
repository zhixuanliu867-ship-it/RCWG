"""BOOT_ONLY negative admission tests; no provider or cloud resources."""
from copy import deepcopy
import unittest
from rcwg_full.auto2.control import TaskState
from rcwg_full.auto2.recovery import install_epoch
from rcwg_full.auto2.dispatch import DispatchGate
from rcwg_full.evidence import digest,sha
import test_auto2

class RecoveryEpoch(unittest.TestCase):
    def setUp(self):
        test_auto2.Auto2Control.setUp(self)
        self.state.reserve(self.scope,'old','G',251904,self.identity)
        self.state.observe('old','SENT_UNCONFIRMED',{'fixture':True})
        with self.state.db() as db:rows=db.execute('SELECT id,kind,amount,status FROM reservations ORDER BY id').fetchall()
        self.amendment={'revision':'AUTO2_RECOVERY_POLICY_1','epoch':1,'authority_kind':'USER_TASK_DELEGATION',
            'root_sha256':digest(self.auth),'user_text':'Explicit recovery fixture','user_text_sha256':sha(b'Explicit recovery fixture'),
            'measurement_profile':'SERVICE_ONLY','manual_signature':False,'client_concurrency':1,'provider_active_count':None,
            'hard_provider_concurrency_required':False,'pure_generation_without_external_tools':True,'old_dispatchers_stopped':True,
            'cleanup_complete':True,'transport_tests_pass':True,'independent_unstarted_jobs':True,'original_initial_limits_cumulative':True,
            'maximum_additional_microusd':5_000_000,'scope_sha256':digest(self.scope),'baseline_reserved_microusd':1251904,
            'prior_reservation_rows_sha256':digest(rows),'isolated_request_ids':['old'],
            'planned_requests':[{'request_id':'count','kind':'COUNT','microusd':1,'body_sha256':'a'*64},
                                {'request_id':'new-e','kind':'E','microusd':100,'body_sha256':'b'*64}]}
    def install(self):install_epoch(self.state,self.amendment,self.scope)
    def dispatch(self,rid,kind,h,status='COMPLETED'):
        gate=DispatchGate(self.state)
        with gate.locked():
            gate.admit(rid,kind,body_hash=h,scope_hash=digest(self.scope))
            amount=next(x['microusd'] for x in self.amendment['planned_requests'] if x['request_id']==rid)
            self.state.reserve(self.scope,rid,kind,amount,self.identity)
            self.state.observe(rid,status,{'fixture':True})
            gate.finish(rid,{'status':status})
    def test_one_independent_epoch_preserves_old_unknown_and_original_root(self):
        self.install();self.dispatch('count','COUNT','a'*64);self.dispatch('new-e','E','b'*64)
        s=self.state.summary();old=next(x for x in s['reservations'] if x['request_id']=='old')
        self.assertEqual(old['status'],'SENT_UNCONFIRMED');self.assertEqual(old['microusd'],251904)
        self.assertEqual(s['reserved_microusd'],1252005);self.assertEqual(s['root_hash'],digest(self.auth))
    def test_second_unknown_blocks_remaining_and_second_recovery_epoch(self):
        self.install();self.dispatch('count','COUNT','a'*64,'SENT_UNCONFIRMED')
        with self.assertRaisesRegex(PermissionError,'FUSED'):self.dispatch('new-e','E','b'*64)
        with self.assertRaisesRegex(PermissionError,'ONLY_ONE_EPOCH'):self.install()
    def test_hard_provider_limit_cannot_be_relabelled_client_limit(self):
        self.amendment['hard_provider_concurrency_required']=True
        with self.assertRaisesRegex(PermissionError,'HARD_PROVIDER_LIMIT'):self.install()
    def test_missing_cleanup_or_live_old_dispatcher_blocks(self):
        self.amendment['old_dispatchers_stopped']=False
        with self.assertRaisesRegex(PermissionError,'PREREQUISITE'):self.install()
    def test_unknown_tools_or_side_effects_blocks(self):
        self.amendment['pure_generation_without_external_tools']=False
        with self.assertRaisesRegex(PermissionError,'PREREQUISITE'):self.install()
    def test_replay_new_uuid_for_unregistered_trial_is_blocked(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'NOT_PREREGISTERED'):self.dispatch('replacement','E','b'*64)
    def test_replay_original_id_rejected_at_install(self):
        self.amendment['planned_requests'][0]['request_id']='old'
        with self.assertRaisesRegex(PermissionError,'NO_REPLAY'):self.install()
    def test_body_or_scope_change_is_blocked(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'NOT_PREREGISTERED'):self.dispatch('count','COUNT','c'*64)
    def test_frozen_order_enforced(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'FROZEN_ORDER'):self.dispatch('new-e','E','b'*64)
    def test_recovery_amount_cannot_be_enlarged(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'NOT_PREREGISTERED'):self.state.reserve(self.scope,'count','COUNT',2,self.identity)
    def test_more_than_five_dollars_rejected(self):
        self.amendment['maximum_additional_microusd']=5000001
        with self.assertRaisesRegex(PermissionError,'SUBCAP'):self.install()
    def test_complete_block_must_fit_recovery_budget(self):
        self.amendment['maximum_additional_microusd']=100
        with self.assertRaisesRegex(PermissionError,'COMPLETE_BLOCK_UNAFFORDABLE'):self.install()
    def test_history_hash_prevents_dropped_or_changed_reservation(self):
        self.amendment['prior_reservation_rows_sha256']='f'*64
        with self.assertRaisesRegex(PermissionError,'HISTORY_CHANGED'):self.install()
    def test_original_initial_limits_still_apply_to_whole_planned_block(self):
        for i in range(4):
            self.state.reserve(self.scope,'used'+str(i),'E',1,self.identity)
            self.state.observe('used'+str(i),'COMPLETED',{})
        with self.state.db() as db:rows=db.execute('SELECT id,kind,amount,status FROM reservations ORDER BY id').fetchall()
        self.amendment.update(prior_reservation_rows_sha256=digest(rows),baseline_reserved_microusd=1251908)
        with self.assertRaisesRegex(PermissionError,'INITIAL_COMPLETE_BLOCK_LIMIT'):self.install()
