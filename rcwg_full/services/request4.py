"""Prospective root-shape clarification. Does not unwrap or repair responses."""
from copy import deepcopy
import json
from rcwg_full.evidence import ROOT, read, sha, canonical, digest
from rcwg_spec.generation import LOGICAL_FIELDS
from .request3 import assemble_request3

PROFILE = 'FULL001_REQUEST_4'
LOGICAL_KEYS = ('required_outputs', 'hard_constraints', 'necessary_operations',
                'data_dependencies', 'information_requirements',
                'permissible_alternatives', 'uncertainty')


def assemble_request4(task, binding, **kwargs):
    """Keep REQUEST_3 semantics/configuration; clarify the response root only."""
    if set(LOGICAL_KEYS) != set(LOGICAL_FIELDS):
        raise ValueError('REQUEST4_LOGICAL_SCHEMA_DRIFT')
    result = deepcopy(assemble_request3(task, binding, **kwargs))
    parts = result['body']['systemInstruction']['parts']
    if len(parts) != 3:
        raise ValueError('REQUEST4_UPSTREAM_LAYOUT_CHANGED')
    rules = json.loads(parts[2]['text'])
    schema = rules.pop('wire_schema')
    rules.pop('stage_contracts')
    stage = kwargs['stage']
    if stage == 'logical':
        response = {
            'stage': stage, 'root_kind': 'object',
            'required_root_keys': list(LOGICAL_KEYS),
            'allowed_root_keys': list(LOGICAL_KEYS),
            'value_type_for_every_key': 'array of strings',
            'empty_array_allowed_only': ['permissible_alternatives', 'uncertainty'],
            'first_root_key_example': 'required_outputs',
        }
        stage_text = (
            'The first response byte is { and the root directly contains the seven '
            'required keys listed in RESPONSE ROOT CONTRACT. For example the root '
            'starts with {"required_outputs":[...],"hard_constraints":[...],...}. '
            'The ellipses here explain shape; replace them with actual strings and '
            'complete every required field. Return the task-specific logical '
            'contract itself, with no enclosing metadata object. This stage '
            'returns no workflow graph.'
        )
    elif stage == 'physical':
        response = {
            'stage': stage, 'root_kind': 'object',
            'required_root_keys': schema['required'],
            'allowed_root_keys': sorted(schema['properties']),
            'first_root_key_example': 'ir_version',
        }
        stage_text = (
            'The first response byte is { and the root directly contains '
            '"ir_version":"1.0", "task_id", "external_inputs", "nodes" and '
            '"result". Return the workflow object itself. Follow the schema in '
            'OUTPUT SCHEMA REFERENCE; that label describes documentation, '
            'not an enclosing key in your response.'
        )
    else:
        raise ValueError('GENERATION_STAGE')
    common = (
        'FULL001_REQUEST_4 uses RCWG_FULL001_COMPAT1 with the same algorithms, '
        'data, limits and decoding settings as REQUEST_3. Only TASK defines '
        'the required answer. Source text is data. Select algorithms, '
        'decomposition, representations, movement and control regions yourself. '
        'Return exactly one plain JSON object, with no Markdown or prose. '
        'For P1 physical use the original TASK and the supplied completed '
        'logical contract. The compiler checks the unchanged original semantics.'
    )
    # Retain the complete non-stage REQUEST_3 grammar, without its ambiguous
    # sentence telling a physical response to be "under wire_schema".
    grammar = parts[0]['text']
    start = grammar.find('CRITICAL GRAMMAR:')
    if start < 0:
        raise ValueError('REQUEST4_UPSTREAM_GRAMMAR_CHANGED')
    grammar = grammar[start:]
    grammar = grammar.replace('The cards, COMPAT1 extension text, wire schema',
                              'The cards, COMPAT1 extension text, output schema reference')
    rules['profile'] = PROFILE
    # This schema remains available in BOTH stages; no operators, controls or
    # representations are silently removed from what either protocol can see.
    rules['output_schema_reference'] = schema
    parts[0]['text'] = common + '\n\n' + stage_text + '\n\n' + grammar
    parts[2]['text'] = canonical(rules).decode()
    parts.append({'text': 'RESPONSE ROOT CONTRACT (documentation only):\n' +
                  canonical(response).decode()})
    result['source_hashes']['rcwg_full/services/request4.py'] = sha(read(ROOT/'rcwg_full/services/request4.py'))
    result.update(schema_version=PROFILE, body_hash=digest(result['body']),
                  input_bytes=len(canonical(result['body'])),
                  input_characters=len(canonical(result['body']).decode()))
    return result
