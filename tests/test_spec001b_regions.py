"""Whole-compiler control, resource, lifetime and invariance regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from rcwg_spec.compiler import validate_workflow, validate_workflow_bytes
from rcwg_spec.common import digest

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    task = json.loads((ROOT / 'specs/reference_v1_0/examples/task_input.json').read_text())
    plan = json.loads((ROOT / 'specs/reference_v1_0/examples/workflow_topk.json').read_text())
    return task, plan


def mapping(name='mapped', source='read.rows'):
    return {'id': name, 'operator': 'map', 'implementation': 'bounded_map',
            'inputs': {'rows': source}, 'params': {}, 'outputs': {'rows': 'Stream[Record]'},
            'regions': {'body': {'bindings': {'item': '$item'}, 'nodes': [],
                                 'yield': {'rows': '$bound.item'}}}}


def looping(name='iterated', source='best.rows', declaration='Table'):
    return {'id': name, 'operator': 'loop', 'implementation': 'bounded_loop',
            'inputs': {'state': source},
            'params': {'condition': {'literal': False}, 'max_iterations': 16},
            'outputs': {'state': declaration},
            'regions': {'body': {'bindings': {'state': '$state'}, 'nodes': [],
                                 'yield': {'state': '$bound.state'}}}}


def add_branch(task, plan):
    task['datasets'].append({'id': 'dataset:flag:v1', 'kind': 'scalar', 'revision': 'v1',
                             'schema_source': 'engineering-public-v1', 'type': 'bool', 'value': True})
    plan['external_inputs']['flag'] = 'dataset:flag:v1'
    arm = {'bindings': {'x': 'best.rows'}, 'nodes': [], 'yield': {'rows': '$bound.x'}}
    branch = {'id': 'choose', 'operator': 'branch', 'implementation': 'predicate_branch',
              'inputs': {'condition': '$input.flag'}, 'params': {'predicate': {'field': 'condition'}},
              'outputs': {'rows': 'Table'}, 'regions': {'then': deepcopy(arm), 'else': deepcopy(arm)}}
    plan['nodes'].append(branch)
    return branch


def release(source='best.rows', after=('answer',)):
    return {'id': 'dispose', 'operator': 'release', 'implementation': 'explicit',
            'inputs': {'artifact': source}, 'params': {}, 'outputs': {'done': 'ControlToken'},
            'after': list(after)}


class TestCompilerControls(unittest.TestCase):
    def accepted(self, task, plan):
        report = validate_workflow(task, plan)
        self.assertEqual(report['status'], 'IR_VALIDATED', report['diagnostics'])
        self.assertFalse(report['formal_ready'])
        self.assertEqual(report['readiness']['runtime_kernels'], 'NOT_IMPLEMENTED')
        self.assertEqual(report['static_implementation_gaps'], [])
        return report

    def rejected(self, task, plan, code):
        report = validate_workflow(task, plan)
        self.assertEqual(report['status'], 'PLAN_INVALID', report['diagnostics'])
        self.assertIn(code, [x['code'] for x in report['diagnostics']])
        self.assertTrue(all(x['path'].startswith('/') for x in report['diagnostics']))

    def test_map_empty_identity_is_typed_record_to_stream(self):
        task, plan = fixture()
        plan['nodes'].append(mapping())
        report = self.accepted(task, plan)
        self.assertIn('DYNAMIC_MAP_INSTANCE_ADMISSION', [x['code'] for x in report['runtime_obligations']])

    def test_map_cannot_yield_a_table_instead_of_a_record(self):
        task, plan = fixture()
        node = mapping()
        node['regions']['body']['bindings']['table'] = 'best.rows'
        node['regions']['body']['yield']['rows'] = '$bound.table'
        plan['nodes'].append(node)
        self.rejected(task, plan, 'TYPE_MISMATCH')

    def test_loop_empty_identity_preserves_table_state(self):
        task, plan = fixture()
        plan['nodes'].append(looping())
        report = self.accepted(task, plan)
        obligation = next(x for x in report['runtime_obligations'] if 'false_at_cap' in x)
        self.assertEqual(obligation['false_at_cap'], 'COMPLETED')
        self.assertEqual(obligation['true_at_cap'], 'LOOP_LIMIT_REACHED')
        self.assertTrue(obligation['check_initial'])
        self.assertTrue(obligation['check_after_last_update'])

    def test_loop_state_type_cannot_change_to_stream(self):
        task, plan = fixture()
        node = looping()
        node['regions']['body']['bindings']['rows'] = 'read.rows'
        node['regions']['body']['yield']['state'] = '$bound.rows'
        plan['nodes'].append(node)
        self.rejected(task, plan, 'TYPE_MISMATCH')

    def test_loop_respects_smaller_global_iteration_cap(self):
        task, plan = fixture()
        plan['limits']['max_loop_iterations'] = 2
        plan['nodes'].append(looping())
        self.rejected(task, plan, 'RESOURCE_LIMIT')

    def test_branch_two_empty_arms_with_explicit_capture(self):
        task, plan = fixture()
        add_branch(task, plan)
        self.accepted(task, plan)

    def test_branch_incompatible_representations_rejected(self):
        task, plan = fixture()
        node = add_branch(task, plan)
        node['regions']['else']['bindings']['x'] = 'read.rows'
        self.rejected(task, plan, 'TYPE_MISMATCH')

    def test_same_local_id_in_distinct_arms_is_valid(self):
        task, plan = fixture()
        node = add_branch(task, plan)
        for arm in node['regions'].values():
            child = {'id': 'keep', 'operator': 'project', 'implementation': 'column_view',
                     'inputs': {'rows': '$bound.x'}, 'params': {'columns': ['id', 'score']},
                     'outputs': {'rows': 'Table'}}
            arm['nodes'] = [child]
            arm['yield'] = {'rows': 'keep.rows'}
        report = self.accepted(task, plan)
        ids = [n['id'] for n in report['typed_graph']['nodes']]
        self.assertIn('root/choose:then/keep', ids)
        self.assertIn('root/choose:else/keep', ids)

    def test_outer_source_cannot_bypass_region_binding(self):
        task, plan = fixture()
        node = mapping()
        node['regions']['body']['yield']['rows'] = '$input.records'
        plan['nodes'].append(node)
        self.rejected(task, plan, 'SCOPE_VIOLATION')

    def test_sibling_region_node_cannot_be_referenced(self):
        task, plan = fixture()
        node = add_branch(task, plan)
        node['regions']['then']['nodes'] = [{'id': 'local', 'operator': 'project', 'implementation': 'copy',
            'inputs': {'rows': '$bound.x'}, 'params': {'columns': ['id']}, 'outputs': {'rows': 'Table'}}]
        node['regions']['else']['yield']['rows'] = 'local.rows'
        self.rejected(task, plan, 'UNKNOWN_REFERENCE')

    def test_nested_map_then_loop_depth_two_is_legal(self):
        task, plan = fixture()
        outer = mapping()
        inner = looping('inner', '$bound.item', 'Record')
        outer['regions']['body']['nodes'] = [inner]
        outer['regions']['body']['yield']['rows'] = 'inner.state'
        plan['nodes'].append(outer)
        self.accepted(task, plan)

    def test_nested_loop_then_map_preserves_stream_state(self):
        task, plan = fixture()
        outer = looping(source='read.rows', declaration='Stream[Record]')
        inner = mapping('inner', '$bound.state')
        outer['regions']['body']['nodes'] = [inner]
        outer['regions']['body']['yield']['state'] = 'inner.rows'
        plan['nodes'].append(outer)
        self.accepted(task, plan)

    def test_depth_three_is_rejected_by_global_structure_check(self):
        task, plan = fixture()
        outer = mapping()
        middle = looping('middle', '$bound.item', 'Record')
        inner = looping('inner', '$bound.state', 'Record')
        middle['regions']['body']['nodes'] = [inner]
        middle['regions']['body']['yield']['state'] = 'inner.state'
        outer['regions']['body']['nodes'] = [middle]
        outer['regions']['body']['yield']['rows'] = 'middle.state'
        plan['nodes'].append(outer)
        self.rejected(task, plan, 'REGION_DEPTH_LIMIT')

    def test_known_root_instances_cannot_exceed_global_limit(self):
        task, plan = fixture()
        plan['limits']['max_node_instances'] = 4
        self.rejected(task, plan, 'RESOURCE_LIMIT')

    def test_unknown_map_work_is_guarded_not_estimate_rejected(self):
        task, plan = fixture()
        node = mapping()
        node['resources'] = {'max_parallelism': 8, 'cpu_slots': 8}
        plan['nodes'].append(node)
        plan['limits']['max_node_instances'] = 8
        report = self.accepted(task, plan)
        admission = next(x for x in report['runtime_obligations'] if x['code'] == 'GLOBAL_INSTANCE_COUNTER')
        self.assertEqual(admission['limit'], 8)
        self.assertFalse(admission['release_refunds_instances'])

    def test_sequential_cpu_claims_not_summed(self):
        task, plan = fixture()
        for n in plan['nodes']:
            n['resources'] = {'cpu_slots': 8}
        self.accepted(task, plan)

    def test_low_memory_sort_keeps_runtime_budget_obligation(self):
        task, plan = fixture()
        task['resources']['worker_memory_limit_bytes'] = 1
        plan['nodes'][2]['implementation'] = 'full_sort'
        report = self.accepted(task, plan)
        self.assertIn('WORKER_MEMORY_LIMIT', [x['code'] for x in report['runtime_obligations']])

    def test_release_after_actual_last_consumer_passes(self):
        task, plan = fixture()
        plan['nodes'].append(release())
        self.accepted(task, plan)

    def test_unordered_release_cannot_precede_indirect_view_consumer(self):
        task, plan = fixture()
        plan['nodes'].append(release(after=('fields',)))
        self.rejected(task, plan, 'RELEASE_BEFORE_LAST_USE')

    def test_two_indirect_views_keep_backing_lifetime(self):
        task, plan = fixture()
        plan['nodes'].append({'id': 'view_two', 'operator': 'project', 'implementation': 'column_view',
            'inputs': {'rows': 'fields.rows'}, 'params': {'columns': ['id', 'score']},
            'outputs': {'rows': 'Table'}})
        plan['nodes'][4]['inputs']['rows'] = 'view_two.rows'
        plan['nodes'].append(release(after=('fields',)))
        self.rejected(task, plan, 'RELEASE_BEFORE_LAST_USE')

    def test_shared_broadcast_alias_requires_downstream_consumer(self):
        task, plan = fixture()
        plan['nodes'].extend([
            {'id': 'share', 'operator': 'broadcast', 'implementation': 'shared_ref',
             'inputs': {'artifact': 'best.rows'}, 'params': {'consumers': ['reader']},
             'outputs': {'reader': 'ArtifactRef[Table]'}},
            {'id': 'replay', 'operator': 'stream_read', 'implementation': 'arrow_batches',
             'inputs': {'artifact': 'share.reader'}, 'params': {'batch_size': 10},
             'outputs': {'rows': 'Stream[Record]'}}, release(after=('answer', 'share'))])
        self.rejected(task, plan, 'RELEASE_BEFORE_LAST_USE')

    def test_region_cannot_yield_an_explicitly_released_value(self):
        task, plan = fixture()
        node = add_branch(task, plan)
        for arm in node['regions'].values():
            arm['nodes'] = [release('$bound.x', ())]
        self.rejected(task, plan, 'RELEASE_BEFORE_LAST_USE')

    def test_control_dependent_external_release_retains_runtime_guard(self):
        task, plan = fixture()
        node = add_branch(task, plan)
        node['outputs'] = {'done': 'ControlToken'}
        for arm in node['regions'].values():
            arm['nodes'] = [release('$bound.x', ())]
            arm['yield'] = {'done': 'dispose.done'}
        report = self.accepted(task, plan)
        self.assertIn('CROSS_REGION_LAST_CONSUMER_GUARD', [x['code'] for x in report['runtime_obligations']])

    def test_original_arrays_and_inputs_are_preserved(self):
        task, plan = fixture()
        plan['nodes'].reverse()
        original = deepcopy((task, plan))
        report = self.accepted(task, plan)
        self.assertEqual((task, plan), original)
        nodes = report['typed_graph']['nodes']
        self.assertEqual([x['logical_id'] for x in nodes], [n['id'] for n in plan['nodes']])
        self.assertEqual(nodes[0]['logical_id'], 'answer')

    def test_coherent_rename_preserves_static_conclusion_not_hash(self):
        task, plan = fixture()
        before = self.accepted(task, plan)
        rename = {n['id']: 'renamed_' + n['id'] for n in plan['nodes']}
        for n in plan['nodes']:
            n['id'] = rename[n['id']]
            n['inputs'] = {k: (rename[v.split('.')[0]] + '.' + v.split('.')[1]
                                   if not v.startswith('$') else v) for k, v in n['inputs'].items()}
        plan['result'] = 'renamed_answer.result'
        after = self.accepted(task, plan)
        self.assertNotEqual(before['canonical_plan_hash'], after['canonical_plan_hash'])

    def test_raw_and_canonical_plan_hashes_are_distinct(self):
        task, plan = fixture()
        raw_a = json.dumps(plan, indent=2).encode()
        raw_b = json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()
        a, b = validate_workflow_bytes(task, raw_a), validate_workflow_bytes(task, raw_b)
        self.assertEqual(a['status'], 'IR_VALIDATED', a['diagnostics'])
        self.assertEqual(a['canonical_plan_hash'], b['canonical_plan_hash'])
        self.assertNotEqual(a['raw_plan_hash'], b['raw_plan_hash'])
        self.assertEqual(a['raw_plan_hash'], hashlib.sha256(raw_a).hexdigest())

    def test_invalid_bytes_are_structured_errors_without_repair(self):
        task, _ = fixture()
        for raw in (b'```json\n{}\n```', b'{"x":1,"x":2}', b'null', b'{"x":1e400}'):
            report = validate_workflow_bytes(task, raw)
            self.assertEqual(report['status'], 'PLAN_INVALID')
            self.assertEqual(report['diagnostics'][0]['stage'], 'parse')

    def test_expected_bad_shapes_do_not_escape_or_become_internal_errors(self):
        task, plan = fixture()
        for broken in (None, 1, [], {'nodes': []}):
            self.assertEqual(validate_workflow(task, broken)['status'], 'PLAN_INVALID')
            self.assertEqual(validate_workflow(broken, plan)['status'], 'INPUT_INVALID')


if __name__ == '__main__':
    unittest.main()
