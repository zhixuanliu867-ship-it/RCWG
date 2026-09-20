from copy import deepcopy
from pathlib import Path
import json,tempfile,unittest
from rcwg_cloud.prompts import physical_body,logical_body,audit_physical_parity,common_parts,PROFILE
from rcwg_spec.common import ContractError,canonical,digest
from rcwg_spec.compiler import validate_workflow
from rcwg_exec.demo import prepare_fixture
from rcwg_exec.datasets import FileRegistry
from rcwg_exec.supervisor import run_f1_supervised
from rcwg_api.vertex import count_body

class CloudPromptParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.task,self.plans,self.recipe,self.data=prepare_fixture(self.root/'fixture')
        self.logical={k:['Public requirement'] for k in ('required_outputs','hard_constraints','necessary_operations','data_dependencies','information_requirements')}
        self.logical.update(permissible_alternatives=[],uncertainty=[])
    def bodies(self):return physical_body(self.task,'P0')[0],physical_body(self.task,'P1',self.logical)[0]
    def test_final_provider_common_material_exact_equality(self):
        a,b=self.bodies();r=audit_physical_parity(a,b,self.task,self.logical)
        self.assertEqual(r['status'],'FINAL_PROVIDER_PHYSICAL_PARITY_PASS');self.assertEqual(a['systemInstruction'],b['systemInstruction'])
        self.assertEqual(r['common_parts_sha256'],digest(a['systemInstruction']['parts']))
    def test_example_present_once_in_both_final_provider_bodies(self):
        for b in self.bodies():
            self.assertEqual(sum('SHARED PUBLIC DEVELOPMENT EXAMPLE' in p['text'] for p in b['systemInstruction']['parts']),1)
            self.assertIn('$input.records',canonical(b).decode());self.assertIn('read.rows',canonical(b).decode())
    def test_removed_example_is_rejected_even_with_same_registry(self):
        a,b=self.bodies();b['systemInstruction']['parts']=[p for p in b['systemInstruction']['parts'] if 'SHARED PUBLIC DEVELOPMENT EXAMPLE' not in p['text']]
        with self.assertRaises(ContractError):audit_physical_parity(a,b,self.task,self.logical)
    def test_tampered_reference_grammar_is_rejected(self):
        a,b=self.bodies();b['systemInstruction']['parts'][1]['text']=b['systemInstruction']['parts'][1]['text'].replace('$input.','input_')
        with self.assertRaises(ContractError):audit_physical_parity(a,b,self.task,self.logical)
    def test_exact_new_logical_response_is_used_without_substitution(self):
        logical=deepcopy(self.logical);logical['uncertainty']=['Distinct authentic stage output']
        body,_=physical_body(self.task,'P1',logical)
        u=json.loads(body['contents'][0]['parts'][0]['text']);self.assertEqual(u['logical_contract'],logical)
        a,_=physical_body(self.task,'P0')
        with self.assertRaises(ContractError):audit_physical_parity(a,body,self.task,self.logical)
    def test_p0_cannot_receive_logical_output(self):
        with self.assertRaises(ContractError):physical_body(self.task,'P0',self.logical)
    def test_p1_requires_closed_logical_schema(self):
        with self.assertRaises(ContractError):physical_body(self.task,'P1',{'gold':['CANARY_PRIVATE_GOLD']})
    def test_hidden_public_task_fields_rejected(self):
        bad=deepcopy(self.task);bad['gold']='CANARY_PRIVATE_GOLD'
        with self.assertRaises(ContractError):physical_body(bad,'P0')
    def test_recipe_and_expected_results_never_enter_wire(self):
        for body in self.bodies():
            wire=canonical(body)
            for key in ('verification_recipe','actual_result_sha256','expected_result_sha256','CANARY_PRIVATE_GOLD'):
                self.assertNotIn(key.encode(),wire)
            self.assertNotIn(canonical(self.recipe),wire)
    def test_count_receives_entire_untruncated_system_and_contents(self):
        for body in self.bodies():
            counted=count_body(body);self.assertEqual(counted,{k:body[k] for k in ('systemInstruction','contents')})
            self.assertIn('$input.',canonical(counted).decode())
    def test_protocol_output_allocations_unchanged(self):
        a,b=self.bodies();logical,_=logical_body(self.task)
        self.assertEqual([a['generationConfig']['maxOutputTokens'],logical['generationConfig']['maxOutputTokens'],b['generationConfig']['maxOutputTokens']],[16384,4096,12288])
    def test_source_mapping_alias_matches_compiler_and_bare_is_invalid(self):
        legal=deepcopy(self.plans['streaming_heap']);self.assertEqual(validate_workflow(self.task,legal)['status'],'IR_VALIDATED')
        legal['nodes'][0]['inputs']['source']='source_dataset'
        rejected=validate_workflow(self.task,legal);self.assertEqual(rejected['status'],'PLAN_INVALID')
        self.assertEqual(rejected['diagnostics'][0]['code'],'REFERENCE_SYNTAX')
    def test_schema_valid_wrong_plan_reaches_independent_verifier_failure(self):
        plan=self.plans['omitted_filter'];self.assertEqual(validate_workflow(self.task,plan)['status'],'IR_VALIDATED')
        registry=FileRegistry(self.task,{self.recipe['source_id']:self.data},allowed_root=self.root)
        result=run_f1_supervised(self.task,plan,registry=registry,recipe=self.recipe,output=self.root/'wrong',generation_id='cloud001-wrong')
        self.assertTrue(result['execution_started']);self.assertEqual(result['terminal_status'],'COMPLETED')
        self.assertEqual(result['verification']['status'],'FAIL');self.assertIsNone(result['measurements']['budget_within'])
    def test_public_brace_text_is_data_not_recursive_template(self):
        task=deepcopy(self.task);task['instruction']+=' Literal {{gold}} is not interpolation.'
        body,_=physical_body(task,'P0');self.assertIn('{{gold}}',canonical(body).decode())
    def test_profile_is_versioned_and_not_formal(self):
        _,e=physical_body(self.task,'P0');self.assertEqual(e['profile'],PROFILE);self.assertFalse(e['formal_ready']);self.assertEqual(e['real_model_requests'],0)

if __name__=='__main__':unittest.main()
