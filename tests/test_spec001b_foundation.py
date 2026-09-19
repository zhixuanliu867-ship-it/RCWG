"""Foundation tests are not evidence of complete SPEC-001B compiler acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from rcwg_spec.common import ContractError, digest
from rcwg_spec.ir_structure import analyze_structure, analyze_bytes, parse_ir_bytes, default_registry
from rcwg_spec.identity import (CONTEXT_HASHES, comparison_identity, execution_identity,
                                require_same_context)

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT/'specs/reference_v1_0/examples/workflow_topk.json').read_text())


def analyze(p):
    return analyze_structure(p, task_id='F1-demo-001',
                             allowed_sources={'dataset:records:v1'})


def passthrough_control(kind='map', name='batch'):
    special = '$item' if kind == 'map' else '$state'
    labels = ['then', 'else'] if kind == 'branch' else ['body']
    bindings = {'x': 'read.rows'} if kind == 'branch' else {'x': special}
    return {'id':name, 'operator':kind, 'implementation':{'map':'bounded_map','branch':'predicate_branch','loop':'bounded_loop'}[kind],
            'inputs':{'rows':'read.rows'}, 'params':{}, 'outputs':{'rows':'Stream[Record]'},
            'regions':{label:{'bindings':deepcopy(bindings),'nodes':[], 'yield':{'rows':'$bound.x'}} for label in labels}}


class TestStructure(unittest.TestCase):
    def check_error(self, p, code):
        with self.assertRaises(ContractError) as cm: analyze(p)
        self.assertEqual(cm.exception.code, code)
        self.assertIsInstance(cm.exception.path, str)

    def test_original_five_nodes(self):
        r=analyze(fixture());self.assertEqual(r['status'],'STRUCTURE_PASS')
        self.assertEqual(r['logical_node_count'],5)
        self.assertFalse(r['full_validation']);self.assertFalse(r['formal_ready'])
        self.assertIn('type_inference',r['pending_checks'])

    def test_input_is_not_mutated(self):
        p=fixture();before=deepcopy(p);analyze(p);self.assertEqual(p,before)

    def test_full_sort_legacy_task_id_is_not_silently_rewritten(self):
        p=json.loads((ROOT/'specs/reference_v1_0/examples/workflow_topk_sort.json').read_text())
        self.check_error(p,'TASK_ID_MISMATCH')
        r=analyze_structure(p,task_id='F1-demo-002',allowed_sources={'dataset:records:v1'})
        self.assertEqual(r['status'],'STRUCTURE_PASS')

    def test_algorithm_remains_as_declared(self):
        p=fixture();a=analyze(p);p['nodes'][2]['implementation']='full_sort';b=analyze(p)
        self.assertNotEqual(a['canonical_plan_hash'],b['canonical_plan_hash'])
        self.assertEqual(b['nodes'][2]['implementation'],'full_sort')

    def test_forward_reference_is_legal(self):
        p=fixture();p['nodes'].reverse();r=analyze(p)
        root=[x for x in r['scopes'] if x['scope']=='root'][0]
        self.assertEqual(root['serialization_order'][0],'answer')
        self.assertEqual(root['analysis_topological_order'][0],'read')

    def test_data_cycle(self):
        p=fixture();p['nodes'][0]['inputs']['source']='best.rows';self.check_error(p,'CYCLIC_DEPENDENCY')

    def test_after_cycle(self):
        p=fixture();p['nodes'][0]['after']=['answer'];self.check_error(p,'CYCLIC_DEPENDENCY')

    def test_duplicate_id(self):
        p=fixture();p['nodes'][1]['id']='read';self.check_error(p,'DUPLICATE_NODE_ID')

    def test_missing_port(self):
        p=fixture();p['nodes'][1]['inputs']['rows']='read.nope';self.check_error(p,'UNKNOWN_REFERENCE')

    def test_missing_node(self):
        p=fixture();p['nodes'][1]['inputs']['rows']='absent.rows';self.check_error(p,'UNKNOWN_REFERENCE')

    def test_unbound_source(self):
        p=fixture();p['nodes'][0]['inputs']['source']='$input.hidden';self.check_error(p,'UNKNOWN_REFERENCE')

    def test_hidden_dataset_handle(self):
        p=fixture();p['external_inputs']['records']='dataset:gold:v1';self.check_error(p,'EXTERNAL_INPUT_MISMATCH')

    def test_unknown_operator(self):
        p=fixture();p['nodes'][0]['operator']='arbitrary_python';self.check_error(p,'UNKNOWN_OPERATOR')

    def test_unknown_implementation(self):
        p=fixture();p['nodes'][2]['implementation']='magic';self.check_error(p,'UNKNOWN_IMPLEMENTATION')

    def test_registry_32_ids_is_only_design_coverage(self):
        self.assertEqual(len(default_registry()),32)
        self.assertFalse(analyze(fixture())['full_validation'])

    def test_unknown_node_field(self):
        p=fixture();p['nodes'][0]['shell']='echo';self.check_error(p,'IR_SHAPE')

    def test_direct_external_result_rejected(self):
        p=fixture();p['result']='$input.records';self.check_error(p,'RESULT_REFERENCE')

    def test_root_bound_reference_rejected(self):
        p=fixture();p['nodes'][1]['inputs']['rows']='$bound.x';self.check_error(p,'SCOPE_VIOLATION')

    def test_per_node_cpu_over_limit(self):
        p=fixture();p['nodes'][1]['resources']={'cpu_slots':9};self.check_error(p,'RESOURCE_LIMIT')

    def test_bool_is_not_integer_resource(self):
        p=fixture();p['nodes'][1]['resources']={'cpu_slots':True};self.check_error(p,'RESOURCE_LIMIT')

    def test_total_declared_cpu_not_naively_summed(self):
        p=fixture()
        for n in p['nodes']:n['resources']={'cpu_slots':8}
        self.assertEqual(analyze(p)['status'],'STRUCTURE_PASS')

    def test_total_logical_nodes(self):
        p=fixture();p['nodes']=[{**deepcopy(p['nodes'][0]),'id':'node_'+str(i)} for i in range(49)]
        self.check_error(p,'IR_SHAPE')

    def test_map_empty_identity_body(self):
        p=fixture();p['nodes'].append(passthrough_control());self.assertEqual(analyze(p)['status'],'STRUCTURE_PASS')

    def test_loop_state_binding(self):
        p=fixture();p['nodes'].append(passthrough_control('loop'));self.assertEqual(analyze(p)['status'],'STRUCTURE_PASS')

    def test_branch_arms_and_parent_dependencies(self):
        p=fixture();p['nodes'].append(passthrough_control('branch'))
        r=analyze(p);self.assertTrue(any(e['kind']=='region_binding' for e in r['dependency_edges']))

    def test_controller_binding_cycle(self):
        p=fixture();n=passthrough_control('branch');n['regions']['then']['bindings']['x']='batch.rows';p['nodes'].append(n)
        self.check_error(p,'CYCLIC_DEPENDENCY')

    def test_regions_required(self):
        p=fixture();n=passthrough_control();del n['regions'];p['nodes'].append(n);self.check_error(p,'IR_SHAPE')

    def test_regions_on_data_operator(self):
        p=fixture();p['nodes'][1]['regions']={};self.check_error(p,'REGION_FORBIDDEN')

    def test_wrong_intrinsic(self):
        p=fixture();n=passthrough_control();n['regions']['body']['bindings']['x']='$state';p['nodes'].append(n)
        self.check_error(p,'REFERENCE_SYNTAX')

    def test_implicit_parent_capture(self):
        p=fixture();n=passthrough_control();n['regions']['body']['yield']['rows']='read.rows';p['nodes'].append(n)
        self.check_error(p,'UNKNOWN_REFERENCE')

    def test_implicit_global_capture(self):
        p=fixture();n=passthrough_control();n['regions']['body']['yield']['rows']='$input.records';p['nodes'].append(n)
        self.check_error(p,'SCOPE_VIOLATION')

    def test_yield_port_mismatch(self):
        p=fixture();n=passthrough_control();n['regions']['body']['yield']={'other':'$bound.x'};p['nodes'].append(n)
        self.check_error(p,'IR_SHAPE')

    def test_local_ids_can_repeat_in_distinct_arms(self):
        p=fixture();n=passthrough_control('branch')
        for arm in n['regions'].values():
            child=deepcopy(p['nodes'][1]);child['id']='keep';child['inputs']['rows']='$bound.x';arm['nodes']=[child];arm['yield']={'rows':'keep.rows'}
        p['nodes'].append(n);r=analyze(p)
        ids=[x['id'] for x in r['nodes']];self.assertEqual(len(ids),len(set(ids)))

    def test_nested_depth_limit(self):
        p=fixture();outer=passthrough_control();middle=passthrough_control();inner=passthrough_control()
        for n in (middle,inner):n['inputs']={'rows':'$bound.x'}
        middle['regions']['body']['nodes']=[inner];outer['regions']['body']['nodes']=[middle];p['nodes'].append(outer)
        self.check_error(p,'REGION_DEPTH_LIMIT')

    def test_empty_region_explicit_parent_binding(self):
        p=fixture();n=passthrough_control();n['regions']['body']['bindings']['x']='read.rows';p['nodes'].append(n)
        self.assertEqual(analyze(p)['status'],'STRUCTURE_PASS')

    def test_resource_claim_is_not_memory_prediction(self):
        p=fixture();r=analyze(p);self.assertIn('dynamic_instance_guards',r['pending_checks'])

    def test_consistent_renaming_preserves_dependency_pattern(self):
        p=fixture();a=analyze(p);mapping={n['id']:'x_'+n['id'] for n in p['nodes']}
        for n in p['nodes']:
            n['id']=mapping[n['id']]
            for key,ref in n['inputs'].items():
                if not ref.startswith('$'):
                    node,port=ref.split('.');n['inputs'][key]=mapping[node]+'.'+port
        node,port=p['result'].split('.');p['result']=mapping[node]+'.'+port
        b=analyze(p)
        self.assertEqual([(e['source'].replace('root/','root/x_'),e['target'].replace('root/','root/x_')) for e in a['dependency_edges']],[(e['source'],e['target']) for e in b['dependency_edges']])
        self.assertNotEqual(a['canonical_plan_hash'],b['canonical_plan_hash'])

    def test_two_nested_regions_are_legal(self):
        p=fixture();outer=passthrough_control();inner=passthrough_control()
        inner['inputs']={'rows':'$bound.x'};outer['regions']['body']['nodes']=[inner]
        p['nodes'].append(outer);self.assertEqual(analyze(p)['status'],'STRUCTURE_PASS')

    def test_recursive_global_node_limit(self):
        p=fixture();n=passthrough_control();n['regions']['body']['nodes']=[{**deepcopy(p['nodes'][1]),'id':'child','inputs':{'rows':'$bound.x'}}]
        p['nodes'].append(n)
        p['nodes'].extend({**deepcopy(p['nodes'][0]),'id':'extra_'+str(i)} for i in range(42))
        self.check_error(p,'LOGICAL_NODE_LIMIT')


class TestBytes(unittest.TestCase):
    def error(self, raw, code):
        with self.assertRaises(ContractError) as cm:parse_ir_bytes(raw)
        self.assertEqual(cm.exception.code,code)

    def test_duplicate_json_key(self):self.error(b'{"a":1,"a":2}','DUPLICATE_JSON_KEY')
    def test_overflow(self):self.error(b'{"a":1e400}','INVALID_NUMBER')
    def test_nan(self):self.error(b'{"a":NaN}','INVALID_NUMBER')
    def test_fenced_json_not_repaired(self):self.error(b'```json\n{}\n```','INVALID_JSON')
    def test_invalid_utf8(self):self.error(b'\xff','INVALID_UNICODE')
    def test_unpaired_surrogate(self):self.error(b'{"x":"\\ud800"}','INVALID_UNICODE')
    def test_depth_guard(self):self.error(b'['*65+b'0'+b']'*65,'IR_INPUT_LIMIT')
    def test_brackets_in_string_are_not_depth(self):self.assertEqual(parse_ir_bytes(b'{"x":"'+b'['*100+b'"}')['x'],'['*100)
    def test_byte_guard(self):self.error(b' '*65537,'IR_INPUT_LIMIT')
    def test_scalar_root(self):self.error(b'null','IR_SHAPE')
    def test_negative_numbers_allowed_in_json(self):self.assertEqual(parse_ir_bytes(b'{"x":-7}')['x'],-7)
    def test_raw_and_canonical_hashes(self):
        p=fixture();raw=json.dumps(p,indent=2).encode();r=analyze_bytes(raw,task_id=p['task_id'],allowed_sources={'dataset:records:v1'})
        self.assertEqual(r['raw_plan_hash'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(r['canonical_plan_hash'],digest(p))
    def test_inprocess_cycles(self):
        p=fixture();p['assumptions']=[p]
        with self.assertRaises(ContractError):analyze(p)
    def test_nonstring_json_keys(self):
        p=fixture();p[1]='oops'
        with self.assertRaises(ContractError):analyze(p)


class TestIdentity(unittest.TestCase):
    def context(self):return {'case_id':'case1','condition_id':'C0',**{k:digest(k) for k in CONTEXT_HASHES}}
    def execution(self,**kw):
        values=dict(plan_hash=digest('p'),compiler_hash=digest('compiler'),input_hash=digest('input'),generation_id='g17',repeat_id='r0')
        values.update(kw);return execution_identity(self.context(),**values)
    def test_context_order_irrelevant(self):
        a=self.context();self.assertEqual(comparison_identity(a),comparison_identity(dict(reversed(list(a.items())))))
    def test_all_common_context_dimensions_are_binding(self):
        a=self.context()
        for k in CONTEXT_HASHES:
            with self.subTest(k=k):
                b=deepcopy(a);b[k]=digest('changed')
                with self.assertRaises(ContractError):require_same_context(a,b)
    def test_plan_change_not_comparison_context_change(self):
        a=self.execution();b=self.execution(plan_hash=digest('different'))
        self.assertEqual(a['comparison_context_hash'],b['comparison_context_hash'])
        self.assertNotEqual(a['execution_key'],b['execution_key'])
    def test_confirmation_not_primary(self):
        a=self.execution();b=self.execution(repeat_role='TIMING_CONFIRMATION');self.assertNotEqual(a['execution_key'],b['execution_key'])
    def test_repeat_changes_execution_identity(self):self.assertNotEqual(self.execution()['execution_key'],self.execution(repeat_id='r1')['execution_key'])
    def test_invalid_hash(self):
        a=self.context();a['data_manifest_hash']='UNRESOLVED'
        with self.assertRaises(ContractError):comparison_identity(a)
    def test_missing_hash(self):
        a=self.context();a.pop('runtime_hash')
        with self.assertRaises(ContractError):comparison_identity(a)
    def test_gold_is_not_an_allowed_context_field(self):
        a=self.context();a['gold']='private'
        with self.assertRaises(ContractError):comparison_identity(a)
    def test_identity_does_not_mutate_input(self):
        a=self.context();before=deepcopy(a);comparison_identity(a);self.assertEqual(a,before)

    def test_invalid_repeat_role_is_structured_error(self):
        with self.assertRaises(ContractError):self.execution(repeat_role=[])


if __name__=='__main__':unittest.main()
