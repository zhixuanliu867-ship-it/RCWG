import copy
import unittest
from collections import Counter
from rcwg_full.campaign.diagnostics import controls,control_slots,bind_control,inject_result,inject_journal,external_slots
from rcwg_full.campaign.transforms import transform, public_guidance
from rcwg_full.data.templates import f1
from rcwg_full.data.document_templates import f5
from rcwg_full.runtime.scheduling_profile import validate_profile
from rcwg_full.evidence import digest


class DiagnosticTests(unittest.TestCase):
    def test_exact_e5_pairs_and_repeat_counts(self):
        rows=list(controls());slots=list(control_slots())
        self.assertEqual(len(rows),120);self.assertEqual(len(slots),320)
        self.assertEqual(len({s['slot_id'] for s in slots}),320)
        pairs=Counter(r['pair_id'] for r in rows)
        self.assertEqual(len(pairs),60);self.assertEqual(set(pairs.values()),{2})
        self.assertEqual(Counter(r['family'] for r in rows),{f'F{i}':20 for i in range(1,7)})

    def test_e3_schedule_preserves_public_budget(self):
        built=f1('F1-01',0,'C0');task,plan=built['task'],built['plan'];original=copy.deepcopy((task,plan))
        result=transform(task,plan,'E3_S')
        self.assertEqual(result['status'],'TRANSFORMED');self.assertEqual((task,plan),original)
        self.assertEqual(result['execution_profile']['cpu_kernel_concurrency'],1)
        self.assertEqual(result['budget_hash'],digest(task['resources']))
        with self.assertRaisesRegex(ValueError,'RANGE'):
            validate_profile(task,{**result['execution_profile'],'cpu_kernel_concurrency':True})
        guide=public_guidance(task);self.assertEqual(guide['output_contract'],task['output_contract'])
        self.assertFalse(guide['uses_hidden_data'])

    def test_physical_transform_preserves_nodes_edges_params(self):
        built=f1('F1-01',0,'C0');plan=copy.deepcopy(built['plan'])
        next(n for n in plan['nodes'] if n['operator']=='top_k')['implementation']='full_sort'
        result=transform(built['task'],plan,'E3_P')
        self.assertEqual(result['status'],'TRANSFORMED')
        self.assertEqual([n['id'] for n in result['plan']['nodes']],[n['id'] for n in plan['nodes']])
        for left,right in zip(result['plan']['nodes'],plan['nodes']):
            self.assertEqual(left['inputs'],right['inputs']);self.assertEqual(left['params'],right['params'])

    def test_e4_not_applicable_preserved_and_windows_explicit(self):
        built=f1('F1-01',0,'C0')
        self.assertEqual(transform(built['task'],built['plan'],'E4_window512')['status'],'TRANSFORM_NOT_APPLICABLE')
        built=f5('F5-05',0,'C0')
        result=transform(built['task'],built['plan'],'E4_window512')
        self.assertEqual(result['status'],'TRANSFORMED')
        windows=[n for n in result['plan']['nodes'] if n['operator']=='split_documents']
        self.assertTrue(windows)
        self.assertTrue(all(n['params']['size']==512 and n['params']['overlap']==64 for n in windows))

    def test_control_result_injection_retains_parent_and_stage(self):
        definition=next(r for r in controls() if r['arm']=='control' and r['transform']=='result_corruption')
        source=[{'value':17}];altered,record=inject_result(source,definition)
        self.assertEqual(source,[{'value':17}]);self.assertNotEqual(source,altered)
        self.assertTrue(record['injected']);self.assertEqual(record['stage'],'independent_result_diagnostic')
        with self.assertRaisesRegex(ValueError,'NOT_DECLARED'):
            inject_result(source,{**definition,'arm':'parent'})

    def test_ledger_injection_is_explicit_separate_bytes(self):
        definition=next(r for r in controls() if r['arm']=='control' and r['transform']=='journal_event_loss')
        original=b'one\ntwo\nthree\n';altered,record=inject_journal(original,definition)
        self.assertEqual(altered,b'one\nthree\n');self.assertEqual(original,b'one\ntwo\nthree\n')
        self.assertEqual(record['stage'],'independent_ledger_diagnostic')

    def test_e8_exact_manifest_drives_repeats(self):
        tasks=[dict(task_id=f'{panel}-{i}',panel=panel,uses_semantics=panel!='SemBench_compatible',dataset_snapshot_hash='abc')
               for panel in ['SemBench_compatible','QASPER','reviewed_graph_text'] for i in range(60)]
        rows=list(external_slots(tasks));counts=Counter(r['slot_kind'] for r in rows)
        self.assertEqual(counts,{'generation':1440,'execution':3360})
        self.assertEqual(len(rows),len({r['slot_id'] for r in rows}))
        tasks[0]['uses_semantics']=None
        with self.assertRaisesRegex(ValueError,'MANIFEST_REQUIRED'):list(external_slots(tasks))
