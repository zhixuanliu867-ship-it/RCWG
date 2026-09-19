"""Derive contract coverage from executed test identities and live dispatch."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from .common import ContractError
from .operators import REGISTRY, DISPATCH, validate_operator

ROOT = Path(__file__).resolve().parents[1]


def contract_coverage(passed_test_ids, *, failed_test_ids=(), skipped_test_ids=()):
    passed = set(passed_test_ids)
    if set(failed_test_ids) or set(skipped_test_ids):
        raise ContractError('COVERAGE_TEST_FAILURE', '', 'all required methods must execute and pass')
    required = json.loads((ROOT / 'specs/spec001b/coverage_required.json').read_text())
    mapping = json.loads((ROOT / 'specs/spec001b/operator_test_mapping.json').read_text())
    rows = mapping['branches']
    pairs = [(r['operator'], r['implementation']) for r in rows]
    expected = {(r['operator'], r['implementation']) for r in required['branches']}
    live = {(op, impl) for op, entry in REGISTRY.items() for impl in entry[0]}
    if len(pairs) != len(set(pairs)) or set(pairs) != expected or live != expected:
        raise ContractError('COVERAGE_REGISTRY_MISMATCH', '', 'worklist, dispatch and tested branches must agree')
    actual = []
    for row in rows:
        record = dict(row)
        for key in ('positive_test_ids', 'negative_test_ids', 'dispatch_test_ids'):
            ids = row.get(key)
            if type(ids) is not list or not ids or any(type(t) is not str or t not in passed for t in ids):
                raise ContractError('COVERAGE_TEST_NOT_EXECUTED', '', 'coverage requires a successful real test ID')
        validator = row.get('static_validator')
        if any(t not in passed for t in row.get('additional_contract_test_ids', [])):
            raise ContractError('COVERAGE_TEST_NOT_EXECUTED', '', 'overload and precondition tests must pass')
        dispatch_id = row['operator'] + ':' + row['implementation']
        if validator != 'rcwg_spec.operators.DISPATCH[' + dispatch_id + ']' or not callable(DISPATCH.get(dispatch_id)):
            raise ContractError('COVERAGE_VALIDATOR_MISMATCH', '', 'coverage must name the actual callable')
        record.update(executable_contract_status='VALIDATED_CONTRACT', runtime_kernel_status='NOT_IMPLEMENTED')
        actual.append(record)
    path = Path(inspect.getfile(validate_operator))
    return {'schema_version': 'SPEC001B_ACTUAL_COVERAGE_1.0', 'status': 'CONTRACT_COVERAGE_PASS',
            'operator_count': len(REGISTRY), 'implementation_branch_count': len(actual),
            'static_implementation_gaps': [], 'formal_ready': False,
            'validator_source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'branches': actual}


def acceptance_test_coverage(passed_test_ids):
    """Attach real executed methods to B00-B12; command/delivery gates are separate."""
    groups = {
        'B00': ('test_core.', 'test_spec001a.', 'test_spec001a_review.'),
        'B01': ('test_spec001b_inputs.', 'test_spec001b_composition.FamilyCompositionTests.test_f'),
        'B02': ('test_spec001b_foundation.TestStructure.',),
        'B03': ('test_spec001b_types.', 'test_spec001b_inputs.'),
        'B04': ('test_spec001b_operators.',),
        'B05': ('test_spec001b_regions.', 'test_spec001b_composition.'),
        'B06': ('test_spec001b_regions.TestCompilerControls.test_known_root',
                'test_spec001b_regions.TestCompilerControls.test_unknown_map',
                'test_spec001b_regions.TestCompilerControls.test_sequential_cpu',
                'test_spec001b_regions.TestCompilerControls.test_low_memory',
                'test_spec001b_regions.TestCompilerControls.test_loop',
                'test_spec001b_foundation.TestStructure.test_per_node_cpu_over_limit'),
        'B07': ('test_spec001b_regions.TestCompilerControls.test_release',
                'test_spec001b_regions.TestCompilerControls.test_unordered_release',
                'test_spec001b_regions.TestCompilerControls.test_two_indirect',
                'test_spec001b_regions.TestCompilerControls.test_shared_broadcast',
                'test_spec001b_regions.TestCompilerControls.test_region_cannot_yield',
                'test_spec001b_regions.TestCompilerControls.test_control_dependent'),
        'B08': ('test_spec001b_predicates.',),
        'B09': ('test_spec001b_generation.', 'test_spec001b_composition.FamilyCompositionTests.test_each_family_mock'),
        'B10': ('test_spec001b_generation.GenerationTests.test_private',
                'test_spec001b_generation.GenerationTests.test_provider',
                'test_spec001b_generation.GenerationTests.test_archive',
                'test_spec001b_generation.GenerationTests.test_tokenizer_failures'),
        'B11': ('test_spec001b_binding.', 'test_spec001b_foundation.TestIdentity.'),
        'B12': ('test_spec001b_foundation.TestBytes.',
                'test_spec001b_regions.TestCompilerControls.test_original_arrays',
                'test_spec001b_regions.TestCompilerControls.test_coherent_rename',
                'test_spec001b_regions.TestCompilerControls.test_raw_and_canonical',
                'test_spec001b_generation.GenerationTests.test_raw_canonical'),
    }
    rows = []
    for gate, prefixes in groups.items():
        ids = sorted(t for t in passed_test_ids if t.startswith(prefixes))
        if not ids:
            raise ContractError('ACCEPTANCE_GATE_NOT_EXECUTED', '', 'gate needs real passing methods')
        rows.append({'gate': gate, 'test_method_ids': ids, 'test_method_count': len(ids),
                     'status': 'TEST_EVIDENCE_PASS', 'counting': 'methods may support multiple gates'})
    return rows
