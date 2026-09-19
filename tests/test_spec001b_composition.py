"""Whole public-family chains: static engineering fixtures, no kernels or data."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from rcwg_spec.compiler import validate_workflow
from rcwg_spec.common import canonical
from rcwg_spec.generation import run_mock_generation, LOGICAL_FIELDS
from test_spec001b_regions import mapping

ROOT = Path(__file__).resolve().parents[1]


def node(name, operator, implementation, inputs, params, outputs):
    result = dict(id=name, operator=operator, implementation=implementation,
                  inputs=inputs, params=params, outputs=outputs)
    if operator in {'materialize', 'cache'}:
        result['storage'] = implementation
    return result


def family_plan(family):
    task = json.loads((ROOT / f'specs/spec001b/examples/public_{family}.json').read_text())
    sources = {d['id'].split(':')[1]: d['id'] for d in task['datasets']}
    plan = dict(ir_version='1.0', task_id=task['task_id'], external_inputs=sources,
                nodes=[], result='answer.result', limits={'max_node_instances': 4096, 'max_loop_iterations': 16})
    rows = 'rows'
    if family == 'F1':
        plan = json.loads((ROOT / 'specs/reference_v1_0/examples/workflow_topk.json').read_text())
        plan['task_id'] = task['task_id']
        plan['nodes'][2]['params']['k'] = 2
        return task, plan
    if family == 'F2':
        for source, columns in [('orders', ['customer', 'amount']), ('customers', ['customer', 'region'])]:
            plan['nodes'].append(node(source, 'scan', 'sequential', {'source': '$input.' + source},
                                      {'columns': columns}, {'rows': 'Stream[Record]'}))
        plan['nodes'].extend([
            node('joined', 'join', 'hash', {'left': 'orders.rows', 'right': 'customers.rows'},
                 {'keys': [{'left': 'customer', 'right': 'customer'}], 'join_type': 'inner', 'build_side': 'right'}, {'rows': 'Table'}),
            node('totals', 'aggregate', 'hash_group', {'rows': 'joined.rows'},
                 {'group_by': ['region'], 'aggregates': [{'function': 'sum', 'field': 'amount', 'as': 'total'}]}, {'rows': 'Table'})])
        result = 'totals.rows'
    elif family == 'F3':
        plan['nodes'] = [node('reachable', 'graph_reachability', 'bfs', {'graph': '$input.graph', 'seeds': '$input.seeds'},
                               {'direction': 'out', 'max_hops': 2}, {'nodes': 'NodeSet'})]
        result = 'reachable.nodes'
    elif family == 'F4':
        plan['nodes'] = [node('read', 'scan', 'sequential', {'source': '$input.records'},
                             {'columns': ['id', 'score']}, {'rows': 'Stream[Record]'}), mapping(),
                         node('store', 'materialize', 'memory', {'rows': 'mapped.rows'},
                              {'format': 'arrow_ipc'}, {'rows': 'Table'})]
        result = 'store.rows'
    elif family in {'F5', 'F6'}:
        if family == 'F6':
            plan['nodes'] = [
                node('neighbors', 'graph_neighbors', 'csr', {'graph': '$input.graph', 'seeds': '$input.seeds'},
                     {'direction': 'out', 'edge_types': []}, {'edges': 'EdgeStream'}),
                node('edge_rows', 'stream_read', 'arrow_batches', {'artifact': 'neighbors.edges'},
                     {'batch_size': 8}, {'rows': 'Stream[Record]'}),
                node('map_rows', 'scan', 'sequential', {'source': '$input.node_document'},
                     {'columns': ['node_id', 'doc_id']}, {'rows': 'Stream[Record]'}),
                node('mapped_ids', 'join', 'hash', {'left': 'edge_rows.rows', 'right': 'map_rows.rows'},
                     {'keys': [{'left': 'target', 'right': 'node_id'}], 'join_type': 'inner', 'build_side': 'right'}, {'rows': 'Table'}),
                node('ids', 'project', 'column_view', {'rows': 'mapped_ids.rows'}, {'columns': ['doc_id']}, {'rows': 'Table'})]
            ids = 'ids.rows'
        else:
            ids = '$input.ids'
        plan['nodes'].extend([
            node('documents', 'read_documents', 'batched', {'index': '$input.documents', 'ids': ids},
                 {'fields': ['id', 'text'], 'batch_size': 8}, {'documents': 'DocumentStream'}),
            node('chunks', 'split_documents', 'token_window', {'documents': 'documents.documents'},
                 {'size': 128, 'overlap': 16}, {'chunks': 'ChunkStream'}),
            node('context', 'gather_context', 'neighbors', {'chunks': 'chunks.chunks'}, {'window': 1}, {'chunks': 'ChunkStream'}),
            node('extract', 'semantic_extract', 'fixed_e0', {'documents': 'context.chunks'},
                 {'field_schema': deepcopy(task['output_contract']['schema']), 'context_budget': 512}, {'evidence': 'EvidenceTable'}),
            node('merge', 'evidence_merge', 'by_document', {'evidence': 'extract.evidence'},
                 {'keys': list(task['output_contract']['schema'])[:1], 'conflict_policy': 'keep_all'}, {'evidence': 'EvidenceTable'}),
            node('validate', 'evidence_validate', 'span_check', {'evidence': 'merge.evidence', 'index': '$input.documents'},
                 {'strict': True}, {'evidence': 'EvidenceTable'})])
        if family == 'F6':
            next(n for n in plan['nodes'] if n['id'] == 'documents')['params']['id_field'] = 'doc_id'
        result = 'validate.evidence'
    else:
        raise ValueError(family)
    plan['nodes'].append(node('answer', 'emit', 'json_artifact', {rows: result},
                              {'output_contract': task['output_contract']['id']}, {'result': 'Result'}))
    return task, plan


class FamilyCompositionTests(unittest.TestCase):
    def check_family(self, family):
        task, plan = family_plan(family)
        original = deepcopy((task, plan))
        report = validate_workflow(task, plan)
        self.assertEqual(report['status'], 'IR_VALIDATED', report['diagnostics'])
        self.assertEqual((task, plan), original)
        self.assertEqual(report['typed_graph']['result']['type']['kind'], 'Result')
        json.dumps(report, allow_nan=False)
        self.assertFalse(report['formal_ready'])
        self.assertEqual(report['readiness']['resource_measurements'], 'NOT_COLLECTED')
        return report

    def test_f1_topk_chain(self): self.check_family('F1')
    def test_f2_join_group_emit_chain(self): self.check_family('F2')
    def test_f3_graph_reachability_emit_chain(self): self.check_family('F3')
    def test_f4_identity_map_materialize_chain(self): self.check_family('F4')
    def test_f5_document_evidence_chain(self): self.check_family('F5')
    def test_f6_graph_document_mapping_evidence_chain(self): self.check_family('F6')

    def test_each_family_mock_p1_plan_uses_same_public_task_and_compiler(self):
        logical = {key: ['Follow public task requirements'] for key in LOGICAL_FIELDS}
        for family in ('F1', 'F2', 'F3', 'F4', 'F5', 'F6'):
            with self.subTest(family=family):
                task, plan = family_plan(family)
                mock = run_mock_generation(task, protocol='P1', responses=[canonical(logical), canonical(plan)],
                                           generation_attempt_id='engineering-' + family)
                self.assertEqual(mock['real_requests'], 0)
                self.assertEqual(mock['mock_requests'], 2)
                self.assertEqual(mock['plan_generation_attempts'], 1)
                checked = validate_workflow(task, mock['plan'])
                self.assertEqual(checked['status'], 'IR_VALIDATED', checked['diagnostics'])

    def test_direct_wrong_result_cannot_bypass_public_output_contract(self):
        task, plan = family_plan('F1')
        plan['nodes'] = plan['nodes'][:1]
        plan['nodes'][0]['params']['columns'] = ['eligible']
        plan['result'] = 'read.rows'
        report = validate_workflow(task, plan)
        self.assertEqual(report['status'], 'PLAN_INVALID')
        self.assertEqual(report['diagnostics'][0]['path'], '/result')

    def test_valid_native_result_keeps_plan_without_implicit_emit(self):
        task, plan = family_plan('F3')
        plan['nodes'].pop()
        plan['result'] = 'reachable.nodes'
        report = validate_workflow(task, plan)
        self.assertEqual(report['status'], 'IR_VALIDATED', report['diagnostics'])
        self.assertEqual(len(report['typed_graph']['nodes']), 1)
        self.assertEqual(report['typed_graph']['result']['type']['kind'], 'NodeSet')

    def test_f6_graph_ids_cannot_be_document_ids_without_explicit_mapping(self):
        task, plan = family_plan('F6')
        docs = next(n for n in plan['nodes'] if n['id'] == 'documents')
        docs['inputs']['ids'] = '$input.seeds'
        self.assertEqual(validate_workflow(task, plan)['status'], 'PLAN_INVALID')

    def test_f6_mapping_revision_cannot_silently_follow_document_revision(self):
        task, plan = family_plan('F6')
        documents = next(d for d in task['datasets'] if d['kind'] == 'document_index')
        documents['revision'] = 'other-revision'
        for index in documents['indexes']:
            index['revision'] = 'other-revision'
        report = validate_workflow(task, plan)
        self.assertEqual(report['status'], 'PLAN_INVALID', report['diagnostics'])

    def test_typed_regions_carry_binding_and_yield_without_embedding_execution(self):
        report = self.check_family('F4')
        mapped = next(n for n in report['typed_graph']['nodes'] if n['operator'] == 'map')
        self.assertEqual(mapped['regions']['body']['bindings'], {'item': '$item'})
        self.assertEqual(mapped['regions']['body']['yield'], {'rows': '$bound.item'})
        self.assertEqual(mapped['regions']['body']['scope'], 'root/mapped:body')


if __name__ == '__main__':
    unittest.main()
