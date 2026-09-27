"""Independent failure-boundary regression cases for delegated execution."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,tempfile,unittest,uuid
from rcwg_full.evidence import ROOT,digest,write
from rcwg_full.auto2.control import TaskState,delegation,preparation_gate,advance_to_live,IDENTITIES,validate_policy


class Auto2Control(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.policy=json.loads((ROOT/'specs/full001/auto2_policy.json').read_text())
        self.history={'reconciled_upper_bound':True,'holds':[{'id':'past','microusd':1_000_000,'evidence_sha256':'a'*64,'reason':'retained old reservation'}]}
        self.auth=delegation(self.policy,'Explicit task delegation for this test fixture','fixture-project',self.history)
        self.state=TaskState(self.root,self.policy,self.auth)
        self.identity={k:digest(k) for k in IDENTITIES}
        self.expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        self.scope=self.state.derive_scope(stage='B_INITIAL',identity=self.identity,limits={'G':24,'E':4,'COUNT':28},ceiling_microusd=15_000_000,expires_at=self.expiry)
    def evidence(self):
        result={}
        for k in ['software','data','isolation','cloud','pricing','preregistration']:
            p=self.root/(k+'.json');h=write(p,{'status':'PASS','identity':self.identity,'actual_account_verified':True,'mock_only':False})
            result[k]={'path':str(p),'sha256':h}
        return result
    def test_root_resume_keeps_prior_and_open_reservations(self):
        self.state.reserve(self.scope,'one','G',200000,self.identity)
        resumed=TaskState(self.root,self.policy,self.auth)
        self.assertEqual(resumed.summary()['reserved_microusd'],1200000)
    def test_lower_existing_limit_wins(self):
        root=delegation(self.policy,'x','p',self.history,lower_limit_microusd=5000000)
        self.assertEqual(root['ceiling_microusd'],5000000)
    def test_root_change_cannot_reset_cumulative_budget(self):
        changed=deepcopy(self.auth);changed['historical_accounting']['holds']=[]
        with self.assertRaisesRegex(PermissionError,'CANNOT_RESET'):TaskState(self.root,self.policy,changed)
    def test_unknown_send_never_refunds_or_replays(self):
        self.state.reserve(self.scope,'unknown','G',200000,self.identity)
        self.state.observe('unknown','SENT_UNCONFIRMED',{'error':'timeout'})
        with self.assertRaisesRegex(PermissionError,'NO_REPLAY'):self.state.reserve(self.scope,'unknown','G',200000,self.identity)
        self.assertEqual(self.state.summary()['reserved_microusd'],1200000)
    def test_budget_exhaustion_prevents_dispatch(self):
        self.state.reserve(self.scope,'large','G',15000000,self.identity)
        with self.assertRaisesRegex(PermissionError,'AFFORDABLE'):self.state.reserve(self.scope,'next','G',1,self.identity)
    def test_new_boot_invalidates_old_scope(self):
        changed={**self.identity,'boot':digest('another boot')}
        with self.assertRaisesRegex(PermissionError,'APPLICABILITY'):self.state.reserve(self.scope,'bad','G',1,changed)
    def test_new_scope_cannot_reset_initial_limits(self):
        for i in range(24):self.state.reserve(self.scope,str(i),'G',1,self.identity)
        new=self.state.derive_scope(stage='B_INITIAL',identity={**self.identity,'boot':'new'},limits={'G':24},ceiling_microusd=10,expires_at=self.expiry)
        with self.assertRaisesRegex(PermissionError,'CUMULATIVE_LIMIT'):self.state.reserve(new,'again','G',1,new['identity'])
    def test_scope_cannot_expand_authority(self):
        with self.assertRaises(ValueError):self.state.derive_scope(stage='B_INITIAL',identity=self.identity,limits={'G':24},ceiling_microusd=101000000,expires_at=self.expiry)
    def test_scope_tampering_rejected(self):
        changed=deepcopy(self.scope);changed['limits']['G']=25
        with self.assertRaisesRegex(PermissionError,'NOT_DERIVED'):self.state.reserve(changed,'x','G',1,self.identity)
    def test_missing_calibration_cannot_make_resource_budget_true(self):
        evidence=self.evidence()
        with self.assertRaisesRegex(PermissionError,'calibration'):preparation_gate(evidence,self.identity,'FORMAL_RESOURCE')
        self.assertFalse(preparation_gate(evidence,self.identity,'SERVICE_ONLY')['budget_success_comparable'])
    def test_preparation_calls_live_action_immediately(self):
        calls=[]
        class ActualAdapter:
            mode='LIVE'
            def __call__(inner):calls.append(self.state.summary()['state']);return {'http_status':200,'test_fixture':True}
        result=advance_to_live(self.state,self.scope,self.evidence(),self.identity,'SERVICE_ONLY',ActualAdapter())
        self.assertEqual(calls,['LIVE_RUNNING']);self.assertEqual(result['http_status'],200)
    def test_mock_cannot_satisfy_actual_transition(self):
        class Mock:
            mode='ENGINEERING_REPLAY'
            def __call__(self):raise AssertionError('must not dispatch')
        with self.assertRaisesRegex(PermissionError,'ACTUAL_PROVIDER'):advance_to_live(self.state,self.scope,self.evidence(),self.identity,'SERVICE_ONLY',Mock())
    def test_changed_evidence_fails(self):
        evidence=self.evidence();Path(evidence['data']['path']).write_text('{}')
        with self.assertRaisesRegex(PermissionError,'BYTES_CHANGED'):preparation_gate(evidence,self.identity,'SERVICE_ONLY')
    def test_preparation_does_not_require_returned_revision(self):
        self.assertEqual(preparation_gate(self.evidence(),self.identity,'SERVICE_ONLY')['status'],'PASS')
    def test_policy_cannot_expand_research_or_initial_requests(self):
        p=deepcopy(self.policy);p['initial_live']['max_g_requests']=25
        with self.assertRaises(ValueError):validate_policy(p)
    def test_legacy_receipt_rejects_auto_scope(self):
        from rcwg_full.campaign.sealing import validate_receipt
        with self.assertRaises((ValueError,PermissionError,KeyError)):validate_receipt(self.scope,action='PAID_SERVICES',subject_hash=digest(self.scope),actor_role='Owner')
