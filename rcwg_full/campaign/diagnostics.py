"""Predeclared E5 pairs and E8 panels; all identities precede observations."""
from copy import deepcopy
from itertools import product
from rcwg_full.evidence import digest


def controls():
    for family in range(1, 7):
        for pair in range(10):
            transform = 'alpha_rename' if pair < 5 else 'result_corruption' if pair < 8 else 'journal_event_loss'
            base = {'family': f'F{family}', 'template_id': f'F{family}-{5 + pair % 8:02d}',
                    'base_id': pair % 5, 'condition': f'C{pair % 4}', 'pair_ordinal': pair,
                    'transform': transform, 'injection_stage': 'before_execution' if pair < 5 else
                    'independent_result_diagnostic' if pair < 8 else 'independent_ledger_diagnostic'}
            base['pair_id'] = digest(base)
            for arm in ['parent', 'control']:
                row = {**base, 'arm': arm, 'expected_verification': 'PASS' if arm == 'parent' or pair < 5 else 'FAIL',
                       'experiment_id': 'E5', 'ledger_role': 'DIAGNOSTIC',
                       'status': 'NOT_RUN', 'plan_source': 'PREDECLARED_REFERENCE_CONTROL'}
                row['control_plan_id'] = digest(row)
                yield row


def control_slots():
    for control in controls():
        for repeat in range(3 if control['family'] in {'F1', 'F2', 'F3', 'F4'} else 2):
            row = {**control, 'slot_kind': 'execution', 'execution_repeat': repeat,
                   'generation_stage': None, 'generator': 'CONTROL', 'protocol': 'CONTROL',
                   'task_id':f"{control['template_id']}-b{control['base_id']}-{control['condition']}",
                   'generation_slot_id':control['control_plan_id'],
                   'trial_label': None, 'expected_dependencies': [control['control_plan_id']]}
            yield {'slot_id': digest(row), **row}


def bind_control(definition, task, plan):
    if definition not in list(controls()):
        raise ValueError('CONTROL_NOT_PREDECLARED')
    from .transforms import transform
    result = {'definition': deepcopy(definition), 'parent_plan_hash': digest(plan),
              'source_task_hash': digest(task), 'plan': deepcopy(plan), 'injected': False}
    if definition['arm'] == 'control' and definition['transform'] == 'alpha_rename':
        transformed = transform(task, plan, 'alpha_rename')
        if transformed['status'] != 'TRANSFORMED':
            raise ValueError('CONTROL_RENAME_NOT_APPLICABLE')
        result['plan'] = transformed['plan']
    result['plan_hash'] = digest(result['plan'])
    return result


def inject_result(result, definition):
    if definition['arm'] != 'control' or definition['transform'] != 'result_corruption':
        raise ValueError('RESULT_INJECTION_NOT_DECLARED')
    original = deepcopy(result)
    def corrupt(value):
        if type(value) is bool: return not value
        if type(value) in {float, int}: return value + 1000003
        if type(value) is str: return value + '__E5_DECLARED_DEFECT__'
        if value is None: return '__E5_DECLARED_DEFECT__'
        if isinstance(value, list):
            return [corrupt(value[0]), *value[1:]] if value else ['__E5_DECLARED_DEFECT__']
        if isinstance(value, dict):
            if not value: return {'__E5_DECLARED_DEFECT__': True}
            key = next(iter(value)); return {**value, key: corrupt(value[key])}
        raise ValueError('CONTROL_RESULT_TYPE')
    altered = corrupt(deepcopy(result))
    return altered, {'stage': definition['injection_stage'], 'injected': True,
                     'original_sha256': digest(original), 'altered_sha256': digest(altered),
                     'control_plan_id': definition['control_plan_id']}


def inject_journal(raw, definition):
    if definition['arm'] != 'control' or definition['transform'] != 'journal_event_loss':
        raise ValueError('JOURNAL_INJECTION_NOT_DECLARED')
    lines = raw.splitlines(keepends=True)
    if len(lines) < 3:
        raise ValueError('JOURNAL_TOO_SHORT_FOR_INJECTION')
    from rcwg_full.evidence import sha
    altered = b''.join(lines[:1] + lines[2:])
    return altered, {'stage': definition['injection_stage'], 'injected': True,
                     'original_sha256': sha(raw), 'altered_sha256': sha(altered),
                     'control_plan_id': definition['control_plan_id']}


def external_slots(tasks):
    panels = {'SemBench_compatible', 'QASPER', 'reviewed_graph_text'}
    if len(tasks) != 180 or len({t['task_id'] for t in tasks}) != 180:
        raise ValueError('E8_TASK_IDENTITIES')
    if any(sum(t['panel'] == p for t in tasks) != 60 for p in panels):
        raise ValueError('E8_PANEL_COUNTS')
    for task in tasks:
        if type(task.get('uses_semantics')) is not bool or not task.get('dataset_snapshot_hash'):
            raise ValueError('E8_FROZEN_TASK_MANIFEST_REQUIRED')
    for task, model, protocol, trial in product(tasks, ['G2', 'G5'], ['P0', 'P1'], [17, 29]):
        row = {**task, 'experiment_id': 'E8', 'generator': model, 'protocol': protocol,
               'trial_label': trial, 'ledger_role': 'EXTERNAL_REPLICATION', 'status': 'NOT_RUN',
               'plan_source': 'GENERATED', 'slot_kind': 'generation', 'execution_repeat': None,
               'generation_stage': 'P0_PHYSICAL' if protocol == 'P0' else 'P1_LOGICAL_THEN_PHYSICAL',
               'expected_dependencies': []}
        generation_id = digest(row)
        yield {'slot_id': generation_id, **row}
        for repeat in range(2 if task['uses_semantics'] else 3):
            execution = {**row, 'slot_kind': 'execution', 'execution_repeat': repeat,
                         'generation_slot_id':generation_id,
                         'generation_stage': None, 'expected_dependencies': [generation_id]}
            yield {'slot_id': digest(execution), **execution}
