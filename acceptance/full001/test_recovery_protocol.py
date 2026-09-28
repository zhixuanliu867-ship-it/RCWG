"""New opt-in grammar disclosure does not rewrite protected legacy profiles."""
import json,unittest
from copy import deepcopy
from rcwg_full.services.requests import assemble,assemble_recovery2
from rcwg_full.data.templates import f1
from rcwg_full.evidence import digest,ROOT
from rcwg_full.compiler import FullCompiler
from test_services import binding

class RecoveryProtocol(unittest.TestCase):
    def make(self,task=None):
        task=task or f1('F1-01',0,'C0')['task']
        kwargs={'protocol':'P0','stage':'physical','attempt_id':'diagnostic-new-profile','request_id':'new-request','trial_label':17}
        return task,kwargs,assemble_recovery2(task,binding(),**kwargs)
    def test_new_profile_discloses_actual_source_ids_alias_pattern_and_emit_type(self):
        task,_,r=self.make();text=r['body']['systemInstruction']['parts'][-1]['text']
        public=json.loads(text.splitlines()[-1])
        self.assertEqual(public['allowed_source_ids'],sorted(x['id'] for x in task['datasets']))
        self.assertEqual(public['alias_pattern'],'^[a-z][a-z0-9_]{0,47}$')
        self.assertEqual(public['emit_parameter_type'],'string')
        self.assertEqual(public['allowed_emit_contract_names'],['result'])
        self.assertEqual(r['body_hash'],digest(r['body']))
    def test_legacy_assembly_remains_identical_and_opt_in_hash_changes(self):
        task,kwargs,new=self.make();old=assemble(task,binding(),**kwargs)
        self.assertEqual(old['schema_version'],'FULL001_REQUEST_1');self.assertEqual(len(old['source_hashes']),10)
        self.assertEqual(new['schema_version'],'FULL001_REQUEST_2');self.assertNotEqual(old['body_hash'],new['body_hash'])
        self.assertEqual(old['body']['systemInstruction']['parts'],new['body']['systemInstruction']['parts'][:-1])
        self.assertEqual(old['body']['contents'],new['body']['contents'])
    def test_legacy_example_alias_is_explicitly_qualified_for_records(self):
        _,_,r=self.make();text=r['body']['systemInstruction']['parts'][-1]['text']
        self.assertIn('ordered_records AND mode is exact',text)
        self.assertNotIn('exact_ordered_topk_v1',json.loads(text.splitlines()[-1])['allowed_emit_contract_names'])
    def test_independent_legal_witness_uses_public_names_without_output_repair(self):
        fixture=f1('F1-01',0,'C0');task=fixture['task']
        # Construct an independent small witness from public operator contracts.
        plan={'ir_version':'1.0','task_id':task['task_id'],'external_inputs':{'records':'dataset:records'},'nodes':[
            {'id':'scan','operator':'scan','implementation':'sequential','inputs':{'source':'$input.records'},'params':{'columns':['id','score','eligible']},'outputs':{'rows':'Stream[Record]'}},
            {'id':'filter','operator':'filter','implementation':'vectorized','inputs':{'rows':'scan.rows'},'params':{'predicate':{'op':'eq','left':{'field':'eligible'},'right':{'literal':True}}},'outputs':{'rows':'Stream[Record]'}},
            {'id':'top','operator':'top_k','implementation':'streaming_heap','inputs':{'rows':'filter.rows'},'params':{'k':20,'keys':[{'field':'score','direction':'desc'},{'field':'id','direction':'asc'}]},'outputs':{'rows':'Table'}},
            {'id':'fields','operator':'project','implementation':'column_view','inputs':{'rows':'top.rows'},'params':{'columns':['id','score']},'outputs':{'rows':'Table'}},
            {'id':'emit','operator':'emit','implementation':'json_artifact','inputs':{'rows':'fields.rows'},'params':{'output_contract':'result'},'outputs':{'result':'Result'}}],
            'result':'emit.result'}
        self.assertEqual(FullCompiler().compile(task,plan)['status'],'IR_VALIDATED')
        _,_,request=self.make(task)
        self.assertNotIn(json.dumps(plan),json.dumps(request))
        bad=deepcopy(plan);bad['nodes'][-1]['params']['output_contract']='exact_ordered_topk_v1'
        self.assertEqual(FullCompiler().compile(task,bad)['diagnostics'][0]['code'],'PARAMETER_ENUM')
