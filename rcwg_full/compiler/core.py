"""Typed WorkIR validation; never execute, repair, reorder or optimize a plan.

The returned graph describes checked contracts and runtime obligations. It is
not a kernel implementation, an execution authorization or a resource estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256
from typing import Any

from rcwg_spec.common import ContractError, canonical, digest
from .structure import analyze_structure, parse_ir_bytes, _json_value
from .public_task import validate_public_task
from .typesystem import Type, check_declared, merge_types, same_type, type_json
from .operators import validate_operator, bind_parameters

PROFILE = "RCWG_FULL001_COMPAT1"
STAGES = {"primary_execution", "generation_probe"}


@dataclass(frozen=True)
class _Value:
    type: Type
    buffers: frozenset[str]


def _fail(code, path):
    raise ContractError(code, path, "Static contract requirement was not satisfied")


def _diagnostic(exc: ContractError, stage: str) -> dict:
    # Never expose exception text, user values or private provider response text.
    path = exc.path if type(exc.path) is str and (not exc.path or exc.path.startswith('/')) else ''
    return {"code": exc.code, "stage": stage, "path": path,
            "detail": "The input violates a checked static contract."}


def _base_report(status):
    return {"status": status, "profile": PROFILE, "diagnostics": [],
            "typed_graph": {}, "runtime_obligations": [],
            "static_implementation_gaps": [],
            "readiness": {"runtime_kernels": "REQUIRES_SOURCE_BOUND_DISPATCH_EVIDENCE"}, "formal_ready": False}


def _capabilities(typ):
    def encode(value):
        if isinstance(value, Type):
            return type_json(value)
        if type(value) is dict:
            return {key: encode(item) for key, item in value.items()}
        if type(value) in {tuple, list}:
            return [encode(item) for item in value]
        return deepcopy(value)
    return encode(typ.metadata)


def validate_workflow(task: dict, plan: dict, *, stage: str = "primary_execution") -> dict:
    """Validate all static contracts, returning sanitized diagnostics on errors.

    INPUT_INVALID identifies a public task or invocation defect. PLAN_INVALID
    is a deterministic violation by the submitted plan. Unexpected exceptions
    are INTERNAL_ERROR and must prevent acceptance; they are never model errors.
    """
    phase = 'input'
    try:
        if type(stage) is not str or stage not in STAGES:
            _fail('STAGE_INVALID', '/stage')
        _json_value(task)
        validated = validate_public_task(task)
        phase = 'structure'
        structure = analyze_structure(plan, task_id=task['task_id'],
                                      allowed_sources=set(validated['input_types']),
                                      cpu_slots=task['resources']['cpu_slots'])
        phase = 'contract'
        report = _compile(task, plan, validated, structure, stage)
        report['task_input_hash'] = digest(task)
        report['canonical_plan_hash'] = digest(plan)
        return report
    except ContractError as exc:
        status = ('INPUT_INVALID' if phase == 'input' else
                  'IMPLEMENTATION_GAP' if exc.code == 'IMPLEMENTATION_GAP' else 'PLAN_INVALID')
        result = _base_report(status)
        result['diagnostics'] = [_diagnostic(exc, phase)]
        if status == 'IMPLEMENTATION_GAP':
            result['static_implementation_gaps'] = [exc.code]
        return result
    except Exception as exc:
        result = _base_report('INTERNAL_ERROR')
        result['diagnostics'] = [{"code": "INTERNAL_ERROR", "stage": phase, "path": "",
                                  "detail": "Internal validation error; no plan attribution.",
                                  "exception_type": type(exc).__name__}]
        return result


def validate_workflow_bytes(task: dict, raw_plan: bytes, *, stage='primary_execution') -> dict:
    """Strict byte parser preserving the private raw-response identity separately."""
    try:
        plan = parse_ir_bytes(raw_plan)
    except ContractError as exc:
        result = _base_report('PLAN_INVALID')
        result['diagnostics'] = [_diagnostic(exc, 'parse')]
    else:
        result = validate_workflow(task, plan, stage=stage)
    if type(raw_plan) is bytes:
        result['raw_plan_hash'] = sha256(raw_plan).hexdigest()
    return result


def _compile(task, plan, public, structure, stage):
    scope_orders = {s['scope']: s['analysis_topological_order'] for s in structure['scopes']}
    typed_nodes, obligations, releases, uses = [], [], [], []
    limit = plan.get('limits', {}).get('max_node_instances', 4096)
    loop_cap = plan.get('limits', {}).get('max_loop_iterations', 16)
    if len(plan['nodes']) > limit:
        _fail('RESOURCE_LIMIT', '/limits/max_node_instances')
    externals = {alias: _Value(public['input_types'][source], frozenset({'input:' + source}))
                 for alias, source in plan['external_inputs'].items()}
    obligations.extend([
        {"code": "GLOBAL_CPU_SLOTS", "path": "/resources/cpu_slots",
         "scope": "run", "limit": task['resources']['cpu_slots']},
        {"code": "GLOBAL_INSTANCE_COUNTER", "path": "/limits/max_node_instances",
         "scope": "run", "limit": limit, "release_refunds_instances": False},
        {"code": "WORKER_MEMORY_LIMIT", "path": "/resources/worker_memory_limit_bytes",
         "scope": "run", "limit": task['resources']['worker_memory_limit_bytes']},
        {"code": "WALL_TIMEOUT", "path": "/resources/wall_timeout_s",
         "scope": "run", "limit": task['resources']['wall_timeout_s']},
    ])

    def visit(nodes, scope, pointer, bound, yield_map=None):
        by_id = {n['id']: (i, n) for i, n in enumerate(nodes)}
        values = {}

        def resolve(ref):
            if ref.startswith('$input.'):
                return externals[ref[7:]]
            if ref.startswith('$bound.'):
                return bound[ref[7:]]
            node, port = ref.split('.')
            return values[node][port]

        for name in scope_orders[scope]:
            position, node = by_id[name]
            path = pointer + '/' + str(position)
            qid = scope + '/' + name
            op = node['operator']
            inputs = {port: resolve(ref) for port, ref in node['inputs'].items()}
            for port, value in inputs.items():
                uses.append((scope, qid, value.buffers, path + '/inputs/' + port))
            checking_node, parameter_bindings = bind_parameters(node, resolve, path)
            for binding in parameter_bindings:
                value = resolve(binding['ref'])
                uses.append((scope, qid, value.buffers, path + '/param_bindings'))
            checked = validate_operator(checking_node, {k: v.type for k, v in inputs.items()},
                                        task=public['normalized_task'], stage=stage, path=path)
            outputs = checked['outputs']
            alias_inputs = checked.get('alias_inputs', {})
            output_buffers = {}
            for obligation in checked.get('runtime_obligations', []):
                obligations.append({**obligation, 'node_id': qid})
            if op in {'map', 'branch', 'loop'}:
                yielded = {}
                for label, region in node['regions'].items():
                    bindings = {}
                    for alias, ref in region['bindings'].items():
                        if ref == '$item':
                            source = inputs['rows']
                            if source.type.kind != 'Stream' or source.type.item is None or source.type.item.kind != 'Record':
                                _fail('TYPE_MISMATCH', path + '/inputs/rows')
                            bindings[alias] = _Value(source.type.item, source.buffers)
                        elif ref == '$state':
                            bindings[alias] = inputs['state']
                        else:
                            bindings[alias] = resolve(ref)
                        uses.append((scope, qid, bindings[alias].buffers,
                                     path + '/regions/' + label + '/bindings/' + alias))
                    rp = path + '/regions/' + label
                    yielded[label], _ = visit(region['nodes'], qid + ':' + label,
                                              rp + '/nodes', bindings, region['yield'])
                if op == 'map':
                    if set(yielded['body']) != {'rows'} or yielded['body']['rows'].type.kind != 'Record':
                        _fail('TYPE_MISMATCH', path + '/regions/body/yield')
                    row = yielded['body']['rows']
                    outputs = {'rows': Type('Stream', item=row.type, domain=row.type.domain,
                                             revision=row.type.revision, metadata=deepcopy(row.type.metadata))}
                    output_buffers['rows'] = row.buffers | frozenset({qid + '.rows'})
                    obligations.append({'code': 'DYNAMIC_MAP_INSTANCE_ADMISSION', 'node_id': qid,
                                        'path': path, 'scope': 'run', 'limit': limit,
                                        'max_parallelism': node.get('resources', {}).get('max_parallelism', 1)})
                elif op == 'branch':
                    left, right = yielded['then'], yielded['else']
                    if left.keys() != right.keys():
                        _fail('PORT_MISMATCH', path + '/regions')
                    outputs = {port: merge_types(left[port].type, right[port].type,
                                                 path + '/regions') for port in left}
                    output_buffers = {p: left[p].buffers | right[p].buffers for p in left}
                else:
                    if node['params']['max_iterations'] > loop_cap:
                        _fail('RESOURCE_LIMIT', path + '/params/max_iterations')
                    body = yielded['body']
                    if set(body) != {'state'} or not same_type(inputs['state'].type, body['state'].type):
                        _fail('TYPE_MISMATCH', path + '/regions/body/yield/state')
                    outputs = {'state': inputs['state'].type}
                    output_buffers['state'] = inputs['state'].buffers | body['state'].buffers
                    obligations.append({'code': 'CONTINUATION_AT_LIMIT', 'node_id': qid,
                                        'path': path + '/params/condition', 'max_iterations': node['params']['max_iterations'],
                                        'condition_semantics': 'continue_while_true',
                                        'check_initial': True, 'check_after_last_update': True,
                                        'false_at_cap': 'COMPLETED', 'true_at_cap': 'LOOP_LIMIT_REACHED'})
                obligations.append({'code': 'CONTROL_DEPENDENT_LIFETIME', 'node_id': qid,
                                    'path': path + '/regions', 'measured_peak_bytes': None})
            if set(outputs) != set(node['outputs']):
                _fail('PORT_MISMATCH', path + '/outputs')
            for port, typ in outputs.items():
                check_declared(typ, node['outputs'][port], path + '/outputs/' + port)
                if port not in output_buffers:
                    aliases = alias_inputs.get(port, [])
                    output_buffers[port] = (frozenset().union(*(inputs[p].buffers for p in aliases))
                                            if aliases else frozenset({qid + '.' + port}))
            values[name] = {p: _Value(t, output_buffers[p]) for p, t in outputs.items()}
            if op == 'release':
                releases.append((scope, qid, inputs['artifact'].buffers, path))
            typed_nodes.append({'id': qid, 'scope': scope, 'logical_id': name,
                                'serialization_position': position, 'operator': op,
                                'implementation': node['implementation'],
                                'dispatch_id': checked['dispatch_id'],
                                'input_references': dict(node['inputs']),
                                'params': deepcopy(node['params']), 'param_bindings': parameter_bindings, 'after': list(node.get('after', [])),
                                'regions': {label: {'scope': qid + ':' + label,
                                                    'bindings': deepcopy(region['bindings']),
                                                    'yield': deepcopy(region['yield'])}
                                            for label, region in node.get('regions', {}).items()},
                                'inputs': {p: type_json(v.type) for p, v in inputs.items()},
                                'outputs': {p: type_json(t) for p, t in outputs.items()},
                                'input_capabilities': {p: _capabilities(v.type) for p, v in inputs.items()},
                                'output_capabilities': {p: _capabilities(t) for p, t in outputs.items()},
                                'buffer_aliases': {p: sorted(b) for p, b in output_buffers.items()},
                                'resources': dict(node.get('resources', {})),
                                'storage': node.get('storage'), 'runtime_kernel_status': 'REQUIRES_SOURCE_BOUND_DISPATCH_EVIDENCE'})
        yielded = {p: resolve(r) for p, r in yield_map.items()} if yield_map is not None else {}
        for release_scope, _, buffers, release_path in releases:
            if release_scope == scope and any(buffers & value.buffers for value in yielded.values()):
                _fail('RELEASE_BEFORE_LAST_USE', release_path + '/inputs/artifact')
        return yielded, resolve

    _, resolve_root = visit(plan['nodes'], 'root', '/nodes', {})
    result = resolve_root(plan['result'])
    # The foundation permits a produced value as the result, with or without an
    # explicit emit. Check the same public contract without adding a plan node.
    if result.type.kind != 'Result' and not (stage=='generation_probe' and result.type.kind=='Stats'):
        output_contract = public['normalized_task']['output_contract']
        check_node = {'operator': 'emit', 'implementation': 'json_artifact',
                      'inputs': {'rows': plan['result']},
                      'params': {'output_contract': output_contract.get('id', output_contract['type'])},
                      'outputs': {'result': 'Result'}}
        try:
            checked_result = validate_operator(check_node, {'rows': result.type},
                                               task=public['normalized_task'], stage=stage, path='/result')
        except ContractError as exc:
            raise ContractError(exc.code, '/result', 'result violates public output contract') from None
        obligations.extend({**obligation, 'result_reference': plan['result']}
                           for obligation in checked_result['runtime_obligations'])
    # Root result must remain live through artifact sealing. This is an additional
    # use, so explicitly freeing its backing buffer is never accepted silently.
    for scope, release, buffers, path in releases:
        if scope == 'root' and buffers & result.buffers:
            _fail('RELEASE_BEFORE_LAST_USE', path + '/inputs/artifact')
    _check_lifetimes(structure['dependency_edges'], releases, uses, obligations)
    report = _base_report('IR_VALIDATED')
    report['full_static_validation'] = True
    report['original_plan'] = deepcopy(plan)
    report['implementation_profile'] = PROFILE
    original_positions = {n['id']: i for i, n in enumerate(structure['nodes'])}
    report['typed_graph'] = {
        'nodes': sorted(typed_nodes, key=lambda n: original_positions[n['id']]), 'dependency_edges': structure['dependency_edges'],
        'scopes': structure['scopes'], 'logical_node_count': structure['logical_node_count'],
        'input_bindings': {alias: {'source_id': plan['external_inputs'][alias], 'type': type_json(v.type),
                                  'public_source': deepcopy(next(d for d in public['normalized_task']['datasets']
                                                                 if d['id'] == plan['external_inputs'][alias]))}
                           for alias, v in externals.items()},
        'result': {'reference': plan['result'], 'type': type_json(result.type)},
        'serialization_preserved': True,
        'buffer_identity_kind': 'STATIC_SYMBOLIC_ROOTS_NOT_MEASURED_ALLOCATIONS',
    }
    report['runtime_obligations'] = obligations
    report['readiness']['input_metadata'] = public.get('readiness', {})
    report['readiness']['resource_measurements'] = 'NOT_COLLECTED'
    return report


def _check_lifetimes(edges, releases, uses, obligations):
    successors = {}
    for edge in edges:
        successors.setdefault(edge['source'], set()).add(edge['target'])

    def precedes(a, b):
        visited, pending = set(), list(successors.get(a, ()))
        while pending:
            current = pending.pop()
            if current == b:
                return True
            if current not in visited:
                visited.add(current)
                pending.extend(successors.get(current, ()))
        return False

    for scope, release, buffers, path in releases:
        for use_scope, consumer, used, _ in uses:
            if consumer == release or not (buffers & used):
                continue
            if scope == use_scope:
                if not precedes(consumer, release):
                    _fail('RELEASE_BEFORE_LAST_USE', path + '/inputs/artifact')
            else:
                obligations.append({'code': 'CROSS_REGION_LAST_CONSUMER_GUARD',
                                    'node_id': release, 'path': path, 'consumer': consumer,
                                    'physical_buffers_counted_once': True})
