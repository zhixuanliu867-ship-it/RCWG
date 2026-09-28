"""BOOT_ONLY: no cloud calls; original ledger and isolation remain authoritative."""
import unittest
from copy import deepcopy
from rcwg_full.evidence import digest,canonical
from rcwg_full.auto2.readiness_budget import install,register_host,amendment
from rcwg_full.auto2.budget_extension import reservation_snapshot,effective_recovery_cap
from rcwg_full.auto2.recovery import active_epoch,check_dispatch
from rcwg_full.auto2.dispatch import DispatchGate
import test_recovery_epoch


class ReadinessBudget(unittest.TestCase):
    def setUp(self):
        test_recovery_epoch.RecoveryEpoch.setUp(self)
        test_recovery_epoch.RecoveryEpoch.install(self)
        with self.state.db() as db:
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',('second',None,'G',189440,'SENT_UNCONFIRMED','{}'))
            self.before=reservation_snapshot(db);self.epoch=active_epoch(db)
        self.args=dict(user_text='BOOT_ONLY authorized bounded cloud calibration and formal continuation',attachment_sha256='a'*64,
            expected_rows_sha256=digest(self.before),expected_epoch_sha256=digest(self.epoch),isolated_requests={'old':251904,'second':189440})
        self.hostscope=self.state.derive_scope(stage='A_INFRA',identity=self.identity,limits={'VM':1},ceiling_microusd=4_500_000,expires_at=self.expiry)
        self.lease={'vcpu':16,'ram_gib':64,'disk_gib':100,'hours':4,'gpu_count':0,'simultaneous_vms':1,
            'platform_termination_action':'STOP','max_run_duration':'4h','idle_minutes':15,
            'labels':{'task_id':'rcwg-full-001','run_id':'BOOT_ONLY'},'startup_script_sha256':'b'*64,
            'pricing_evidence_sha256':'c'*64,'reserved_microusd':4_500_000}

    def test_append_preserves_root_epoch_holds_and_cleanup(self):
        value=install(self.state,**self.args)
        with self.state.db() as db:
            self.assertEqual(reservation_snapshot(db),self.before);self.assertEqual(active_epoch(db),self.epoch)
            self.assertEqual(effective_recovery_cap(db,self.epoch),90_000_000-self.epoch['baseline_reserved_microusd'])
        self.assertEqual(value['allocation_a_microusd']+value['allocation_b_microusd'],75_000_000)
        with self.assertRaisesRegex(PermissionError,'ALREADY_APPENDED'):install(self.state,**self.args)

    def test_only_one_exact_host_reservation_and_no_model_exception(self):
        install(self.state,**self.args);register_host(self.state,self.hostscope,self.lease,'vm')
        with self.assertRaises(PermissionError):self.state.reserve(self.hostscope,'other','VM',4_500_000,self.identity)
        with self.assertRaises(PermissionError):self.state.reserve(self.hostscope,'vm','VM',4_500_001,self.identity)
        self.state.reserve(self.hostscope,'vm','VM',4_500_000,self.identity)
        with self.assertRaisesRegex(PermissionError,'NO_REPLAY'):register_host(self.state,self.hostscope,self.lease,'vm')
        with self.assertRaisesRegex(PermissionError,'ONE_HOST'):register_host(self.state,self.hostscope,self.lease,'another')
        with self.state.db() as db:
            with self.assertRaises(PermissionError):check_dispatch(db,'vm','G','a'*64,digest(self.hostscope))

    def test_changed_history_and_new_unknown_refused(self):
        with self.state.db() as db:db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',('third',None,'G',1,'UNKNOWN','{}'))
        with self.assertRaisesRegex(PermissionError,'HISTORY_CHANGED'):install(self.state,**self.args)
        with self.state.db() as db:self.args['expected_rows_sha256']=digest(reservation_snapshot(db))
        with self.assertRaisesRegex(PermissionError,'NEW_UNKNOWN'):install(self.state,**self.args)

    def test_fused_dispatch_refuses_amendment(self):
        with self.state.db() as db:DispatchGate(self.state)._record(db,'FUSED',{'BOOT_ONLY':True})
        with self.assertRaisesRegex(PermissionError,'NOT_QUIESCENT'):install(self.state,**self.args)

    def test_tampered_amendment_cannot_expand_budget(self):
        value=install(self.state,**self.args);value['cleanup_microusd']=0
        with self.state.db() as db:
            db.execute('UPDATE formal_readiness_budget SET body=?,sha256=?',(canonical(value).decode(),digest(value)))
            with self.assertRaisesRegex(PermissionError,'BINDING'):effective_recovery_cap(db,self.epoch)

    def test_host_lease_cannot_expand_hardware_or_runtime(self):
        install(self.state,**self.args)
        for key,value in [('hours',5),('vcpu',17),('ram_gib',65),('gpu_count',1)]:
            lease=deepcopy(self.lease);lease[key]=value
            with self.subTest(key=key),self.assertRaises(PermissionError):register_host(self.state,self.hostscope,lease,'vm')
