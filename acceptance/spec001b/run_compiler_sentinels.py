#!/usr/bin/env python3
"""Independent integration sentinels for the future full compiler.

An absent compiler returns exit 2 / BLOCKED_IMPLEMENTATION_GAP. It is not counted
as a model failure and is not a successful complete SPEC-001B acceptance.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rcwg_spec.common import digest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    module = 'rcwg_spec.compiler'
    if importlib.util.find_spec(module) is None:
        report = {'status':'BLOCKED_IMPLEMENTATION_GAP','missing':module,
                  'full_spec001b_accepted':False,'formal_ready':False,'tested_cases':0}
        exit_code = 2
    else:
        implementation = importlib.import_module(module)
        validate = getattr(implementation, 'validate_workflow', None)
        if not callable(validate):
            report = {'status':'BLOCKED_IMPLEMENTATION_GAP','missing':module+'.validate_workflow',
                      'full_spec001b_accepted':False,'formal_ready':False,'tested_cases':0}
            exit_code = 2
        else:
            spec = json.loads((Path(__file__).parent/'compiler_cases.json').read_text(encoding='utf8'))
            results = []
            for case in spec['cases']:
                task, plan = deepcopy(case['task']), deepcopy(case['plan'])
                before = digest({'task':task,'plan':plan})
                try:
                    got = validate(task, plan, stage='primary_execution')
                    errors = []
                    if not isinstance(got, dict):
                        errors.append('REPORT_NOT_OBJECT')
                    else:
                        if got.get('status') != case['expected_status']:errors.append('STATUS_MISMATCH')
                        if got.get('formal_ready') is not False:errors.append('FORMAL_READY_OVERCLAIM')
                        if case['expected_code'] and not any(x.get('code')==case['expected_code'] for x in got.get('diagnostics',[]) if isinstance(x,dict)):
                            errors.append('DIAGNOSTIC_CODE_MISMATCH')
                        if got.get('status') == 'IR_VALIDATED' and got.get('canonical_plan_hash') != digest(plan):
                            errors.append('PLAN_HASH_MISSING_OR_REWRITTEN')
                    if digest({'task':task,'plan':plan}) != before:errors.append('INPUT_MUTATED')
                    results.append({'case_id':case['id'],'pass':not errors,'errors':errors})
                except Exception as exc:
                    # Never include exception messages: they may echo private input.
                    results.append({'case_id':case['id'],'pass':False,'errors':['UNHANDLED_'+type(exc).__name__]})
            all_pass = all(x['pass'] for x in results)
            report = {'status':'SPEC001B_SENTINELS_PASS' if all_pass else 'SPEC001B_SENTINELS_FAIL',
                      'full_spec001b_accepted':False,'formal_ready':False,'tested_cases':len(results),
                      'passed_cases':sum(x['pass'] for x in results),'results':results,
                      'notice':'These sentinels supplement, not replace, all-operator, control, P0/P1 and identity acceptance.'}
            exit_code = 0 if all_pass else 1
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report,indent=2))
    return exit_code


if __name__ == '__main__':raise SystemExit(main())
