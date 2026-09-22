"""Trusted profile selection; legacy callers retain their existing validator."""
from rcwg_spec.compiler import validate_workflow as legacy_validate
from rcwg_spec.ir_structure import parse_ir_bytes
from .core import validate_workflow, validate_workflow_bytes
from rcwg_full import PROFILE

class FullCompiler:
    def compile(self, public_task, raw_plan, implementation_profile=PROFILE, *, frozen_binding=None):
        if frozen_binding is not None:
            from copy import deepcopy
            from rcwg_full.evidence import digest
            plan=parse_ir_bytes(raw_plan) if isinstance(raw_plan,bytes) else raw_plan
            source=frozen_binding['source_binding'];target=frozen_binding['target_binding']
            if (implementation_profile!=PROFILE or frozen_binding.get('experiment_id')!='E2' or
                frozen_binding.get('source_plan_hash')!=digest(plan) or source['condition']!='C0' or target['condition'] not in {'C1','C2','C3'} or
                source['task_id']!=plan['task_id'] or target['task_id']!=public_task['task_id'] or
                any(source[k]!=target[k] for k in ['template_id','base_id','generator','protocol','trial_label'])):
                raise ValueError('FROZEN_TARGET_BINDING')
            bound=deepcopy(public_task);bound['task_id']=source['task_id']
            report=validate_workflow(bound,plan)
            report.update(task_input_hash=digest(public_task),frozen_binding_hash=digest(frozen_binding),
                          source_task_id=source['task_id'],target_task_id=target['task_id'],plan_rewritten=False)
            return report
        if implementation_profile == 'RCWG_WORKIR_1_0_SPEC001B':
            return legacy_validate(public_task, parse_ir_bytes(raw_plan) if isinstance(raw_plan, bytes) else raw_plan)
        if implementation_profile != PROFILE:
            return {'status':'INPUT_INVALID','diagnostics':[{'code':'PROFILE_UNKNOWN'}], 'formal_ready':False}
        if isinstance(raw_plan, bytes):
            return validate_workflow_bytes(public_task, raw_plan)
        return validate_workflow(public_task, raw_plan)
