"""BOOT_ONLY recovery continuation: no network, model requests or host writes."""
from copy import deepcopy
from types import SimpleNamespace
import json,sqlite3,threading,unittest,uuid
import test_recovery_epoch
from test_services import binding
from rcwg_full.data.templates import f1
from rcwg_full.evidence import digest,canonical
from rcwg_full.auto2.dispatch import DispatchGate
from rcwg_full.auto2.recovery_development import install_block,bind_request,skip_failed_physical,rows
from rcwg_full.services.requests import assemble_recovery2
from rcwg_spec.generation import LOGICAL_FIELDS


class RecoveryDevelopment(unittest.TestCase):
    def setUp(self):
        test_recovery_epoch.RecoveryEpoch.setUp(self);test_recovery_epoch.RecoveryEpoch.install(self)
        test_recovery_epoch.RecoveryEpoch.dispatch(self,'count','COUNT','a'*64);test_recovery_epoch.RecoveryEpoch.dispatch(self,'new-e','E','b'*64)
        self.dev=self.state.derive_scope(stage='B_DEVELOPMENT',identity=self.identity,limits={'G':18,'COUNT':18},ceiling_microusd=1818,expires_at=self.expiry)
        self.old={'id':'dev-f1','max_E_requests':0,'generations':[]};self.recipes=[];jobs=[]
        for i in range(6):
            for protocol in ['P0','P1']:
                g={'id':f'g{i}-{protocol}','task_id':'F1-01-b0-C0','generator':'G'+str(i),'protocol':protocol,'trial_label':17,'task_file_sha256':'c'*64}
                self.old['generations'].append(g);job={**g,'id':'recovery-r1-request2-'+g['id']};jobs.append(job)
                self.recipes.append({'attempt_id':job['id'],'binding':{**binding(),'slot':g['generator']},'protocol':protocol,'trial_label':17,'public_task_file_sha256':'c'*64,'task':f1('F1-01',0,'C0')['task'],'rates':{'G':100,'COUNT':1}})
        self.block={'id':'recovery-r1-request2-dev-f1','original_block_id':'dev-f1','generations':jobs,'max_E_requests':0,'reserved_upper_microusd':1818}
        self.index=SimpleNamespace(lock=threading.Lock(),db=sqlite3.connect(':memory:'))
        self.index.db.execute('CREATE TABLE requests(id TEXT,status TEXT,result TEXT)');self.addCleanup(self.index.db.close)
    def install(self):install_block(self.state,self.dev,self.block,self.recipes,original_blocks=[self.old],original_manifest_sha256='d'*64)
    def request(self,position=0,logical=None):
        with self.state.db() as db:r=rows(db)[position]
        q=json.loads(r['recipe']);a=assemble_recovery2(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],request_id=q['request_id'],trial_label=q['trial_label'],logical=logical)
        if r['kind']=='COUNT':a={**a,'request_id':r['id'],'body':{k:v for k,v in a['body'].items() if k in {'contents','systemInstruction'}}};a['body_hash']=digest(a['body'])
        return r,a
    def dispatch(self,position,status='COMPLETED'):
        row,req=self.request(position);bind_request(self.state,req,row['kind'],self.index);gate=DispatchGate(self.state)
        with gate.locked():
            gate.admit(row['id'],row['kind'],body_hash=req['body_hash'],scope_hash=digest(self.dev))
            self.state.reserve(self.dev,row['id'],row['kind'],row['amount'],self.identity)
            self.state.observe(row['id'],status,{});gate.finish(row['id'],{'status':status})
        return row
    def test_complete_block_preserves_initial_counts_root_and_old_unknown(self):
        self.install();self.dispatch(0);self.dispatch(1)
        s=self.state.summary();self.assertEqual(s['root_hash'],digest(self.auth));self.assertEqual(next(r for r in s['reservations'] if r['request_id']=='old')['status'],'SENT_UNCONFIRMED')
        with self.state.db() as db:self.assertEqual(len(rows(db)),36)
    def test_partial_comparison_cannot_be_admitted(self):
        self.recipes.pop()
        with self.assertRaisesRegex(PermissionError,'COMPLETE_COMPARISON'):self.install()
    def test_changed_task_model_or_protocol_lineage_cannot_be_admitted(self):
        self.recipes[0]['binding']['slot']='G5'
        with self.assertRaisesRegex(PermissionError,'LINEAGE'):self.install()
    def test_new_unknown_fuses_same_epoch_and_queued_development(self):
        self.install();self.dispatch(0,'SENT_UNCONFIRMED')
        with self.assertRaisesRegex(PermissionError,'FUSED'):self.dispatch(1)
        with self.assertRaisesRegex(PermissionError,'FUSED'):self.install()
    def test_body_not_matching_frozen_public_recipe_is_rejected(self):
        self.install();r,a=self.request();a['body']['contents'][0]['parts'][0]['text']='Changed task';a['body_hash']=digest(a['body'])
        with self.assertRaisesRegex(PermissionError,'BODY_RECIPE'):bind_request(self.state,a,r['kind'],self.index)
    def test_unbound_request_cannot_dispatch(self):
        self.install();r,a=self.request();gate=DispatchGate(self.state)
        with gate.locked():
            with self.assertRaisesRegex(PermissionError,'DEVELOPMENT_BINDING'):gate.admit(r['id'],r['kind'],body_hash=a['body_hash'],scope_hash=digest(self.dev))
    def test_count_and_generation_order_is_enforced(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'FROZEN_ORDER'):self.dispatch(1)
    def test_no_next_block_when_current_comparison_is_incomplete(self):
        self.install()
        with self.assertRaisesRegex(PermissionError,'PREVIOUS_BLOCK_INCOMPLETE'):self.install()
    def test_p1_physical_requires_actual_completed_logical_response(self):
        self.install();logical={k:[] if k in {'uncertainty','permissible_alternatives'} else ['public contract'] for k in LOGICAL_FIELDS};r,a=self.request(4,logical)
        with self.assertRaisesRegex(PermissionError,'LOGICAL_DEPENDENCY'):bind_request(self.state,a,r['kind'],self.index)
        q=json.loads(r['recipe']);rid=str(uuid.uuid5(uuid.NAMESPACE_URL,digest(self.auth)+':'+q['attempt_id']+':logical'))
        self.index.db.execute('INSERT INTO requests VALUES(?,?,?)',(rid,'COMPLETED',canonical({'response':{'text':canonical(logical).decode()}}).decode()))
        bind_request(self.state,a,r['kind'],self.index)
        with self.assertRaisesRegex(PermissionError,'SKIP_VALID_LOGICAL'):skip_failed_physical(self.state,q['attempt_id'],self.index)
    def test_failed_logical_skips_only_its_physical_dependency(self):
        self.install();q=self.recipes[1];rid=str(uuid.uuid5(uuid.NAMESPACE_URL,digest(self.auth)+':'+q['attempt_id']+':logical'))
        self.index.db.execute('INSERT INTO requests VALUES(?,?,?)',(rid,'COMPLETED',canonical({'response':{'text':'not json'}}).decode()))
        skip_failed_physical(self.state,q['attempt_id'],self.index)
        with self.state.db() as db:self.assertEqual(sum(r['state']=='SKIPPED' for r in rows(db)),2)
    def test_complete_block_must_fit_remaining_recovery_subcap(self):
        with self.state.db() as db:
            a=json.loads(db.execute('SELECT body FROM recovery_epoch').fetchone()[0]);a['maximum_additional_microusd']=1818;db.execute('UPDATE recovery_epoch SET body=?',(canonical(a).decode(),))
        with self.assertRaisesRegex(PermissionError,'COMPLETE_BLOCK_UNAFFORDABLE'):self.install()
