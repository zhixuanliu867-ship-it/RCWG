from copy import deepcopy
from pathlib import Path
import unittest
from rcwg_full.evidence import canonical,digest,read
from rcwg_full.data.templates import build
from rcwg_full.campaign.planning import rebind_frozen
from rcwg_full.runtime.binding import build_context,freeze_execution
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.reference.confirmation import context_identity
from rcwg_full.compiler.public_task import validate_public_task
from rcwg_spec.binding import seal_events,make_sidecar,validate_evidence
from support import EvidenceDirectory


class FrozenEvidence(unittest.TestCase):
    def test_target_context_seals_original_plan_and_timing_reference_role(self):
        evidence=EvidenceDirectory(self.id());root=Path(evidence.name)
        try:
            a=build('F1-01',0,'C0',root/'a');b=build('F1-01',0,'C2',root/'b');before=canonical(a['plan'])
            common={'template_id':'F1-01','base_id':0,'generator':'G0','protocol':'P1','trial_label':17}
            frozen=rebind_frozen(a['plan'],{**common,'task_id':a['task']['task_id'],'condition':'C0'},{**common,'task_id':b['task']['task_id'],'condition':'C2'})
            meta={'revision':'OFFLINE_BOUNDARY_FIXTURE_NOT_NATIVE_EXECUTION'}
            ctx=build_context(b['task'],condition_id='C2',data_manifest=DataCatalog(b['manifest_path']).bind(b['task']).bindings(),
                runtime=meta,cache_policy=meta,verifier=meta,metric_spec=meta,operator_registry=meta,
                measurement_profile={**meta,'event_source_id':'fixture','clock_id':'monotonic_ns'},
                source_manifest={**meta,'public_sources':validate_public_task(b['task'])['source_manifest']})
            expected=freeze_execution(ctx,b['task'],a['plan'],b'fixture compiler identity','reference-1',frozen_binding=frozen,
                record_role='REFERENCE',repeat_role='TIMING_CONFIRMATION')
            record=expected.as_dict()['expected_records'][0]
            self.assertEqual(record['plan_hash'],digest(a['plan']));self.assertEqual(before,canonical(a['plan']))
            self.assertEqual(record['input_hash'],validate_public_task(b['task'])['task_input_hash'])
            self.assertEqual(context_identity(ctx)[1],ctx.comparison_context_hash)
            self.assertEqual(record['repeat_role'],'TIMING_CONFIRMATION')
            events=seal_events(expected,'reference-1',[{'event':'run_started','monotonic_ns':1,'status':'RUNNING','payload':{}},
                {'event':'run_finished','monotonic_ns':2,'status':'COMPLETED','payload':{}}])
            sidecar=make_sidecar(expected,'reference-1',events,terminal_status='COMPLETED',verification_status='PASS')
            validated=validate_evidence(expected,[],{'reference-1':events},reference_records=[sidecar])
            self.assertEqual(validated['status'],'EVIDENCE_BOUND')
            with self.assertRaisesRegex(ValueError,'FROZEN_CONTEXT_TASK_MISMATCH'):
                freeze_execution(ctx,a['task'],a['plan'],b'compiler','wrong',frozen_binding=frozen)
        finally:evidence.cleanup()
