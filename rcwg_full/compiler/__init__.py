"""Trusted profile selection; legacy callers retain their existing validator."""
from rcwg_spec.compiler import validate_workflow as legacy_validate
from rcwg_spec.ir_structure import parse_ir_bytes
from .core import validate_workflow, validate_workflow_bytes
from rcwg_full import PROFILE

class FullCompiler:
    def compile(self, public_task, raw_plan, implementation_profile=PROFILE):
        if implementation_profile == 'RCWG_WORKIR_1_0_SPEC001B':
            return legacy_validate(public_task, parse_ir_bytes(raw_plan) if isinstance(raw_plan, bytes) else raw_plan)
        if implementation_profile != PROFILE:
            return {'status':'INPUT_INVALID','diagnostics':[{'code':'PROFILE_UNKNOWN'}], 'formal_ready':False}
        if isinstance(raw_plan, bytes):
            return validate_workflow_bytes(public_task, raw_plan)
        return validate_workflow(public_task, raw_plan)
