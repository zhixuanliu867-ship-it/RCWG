"""Explicit offline CLI. Preparing dependencies and sending LIVE calls are separate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from rcwg_full.evidence import ROOT, canonical, digest, exclusive_directory, read, write


def parser():
    p = argparse.ArgumentParser(prog='python -m rcwg_full')
    commands = p.add_subparsers(dest='command', required=True)
    data = commands.add_parser('data').add_subparsers(dest='action', required=True)
    build = data.add_parser('build'); build.add_argument('--profile', choices=['engineering_tiny_v1'], required=True)
    build.add_argument('--templates', default='all'); build.add_argument('--out', required=True, type=Path)
    verify = commands.add_parser('verify-software'); verify.add_argument('--suite', choices=['all'], default='all')
    verify.add_argument('--out', required=True, type=Path); verify.add_argument('--native-build', type=Path)
    campaign = commands.add_parser('campaign').add_subparsers(dest='action', required=True)
    plan = campaign.add_parser('plan'); plan.add_argument('--spec', required=True, type=Path)
    plan.add_argument('--dry-run', required=True, action='store_true'); plan.add_argument('--out', required=True, type=Path)
    for action in ['admit', 'run', 'reconcile', 'seal', 'unseal']:
        sub = campaign.add_parser(action); sub.add_argument('--manifest', required=True, type=Path)
        if action == 'admit': sub.add_argument('--check-only', required=True, action='store_true')
        if action == 'run': sub.add_argument('--receipts', required=True, type=Path)
        if action == 'reconcile': sub.add_argument('--read-only', required=True, action='store_true')
        if action == 'unseal': sub.add_argument('--audit-receipt', required=True, type=Path)
    analyze = commands.add_parser('analyze'); analyze.add_argument('--sealed-manifest', required=True, type=Path)
    analyze.add_argument('--out', required=True, type=Path)
    return p


def dispatch(a):
    if a.command == 'data':
        from rcwg_full.data.templates import build
        catalog = json.loads(read(ROOT / 'specs/full001/templates.json'))['templates']
        selected = [r['template_id'] for r in catalog] if a.templates == 'all' else a.templates.split(',')
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= {r['template_id'] for r in catalog}:
            raise ValueError('TEMPLATE_SELECTION')
        out = exclusive_directory(a.out); identities = []
        for template in selected:
            for base in range(5):
                for condition in ['C0', 'C1', 'C2', 'C3']:
                    bundle = build(template, base, condition, out / f'{template}-b{base}-{condition}')
                    identities.append({'task_id': bundle['task']['task_id'], 'task_hash': digest(bundle['task']),
                                       'plan_hash': digest(bundle['plan']), 'compile_status': bundle['proof']['status']})
        result = {'phase': 'DATA_BUILD', 'status': 'PASS' if all(i['compile_status'] == 'IR_VALIDATED' for i in identities) else 'FAIL',
                  'profile': a.profile, 'instances': identities, 'formal_frozen': False, 'execution_performed': False}
        write(out / 'build-manifest.json', result)
        return (0 if result['status'] == 'PASS' else 1), {k: v for k, v in result.items() if k != 'instances'} | {'instances': len(identities)}
    if a.command == 'verify-software':
        build = a.native_build or (Path(os.environ['RCWG_FULL_BUILD']) if os.environ.get('RCWG_FULL_BUILD') else None)
        if build is None or not (build / 'BUILD.json').is_file():
            return 2, {'phase': 'SOFTWARE_TESTS', 'status': 'BLOCKED_BUILD_REQUIRED', 'blockers': ['SOURCE_BOUND_NATIVE_BUILD']}
        code = subprocess.run([sys.executable, str(ROOT / 'acceptance/full001/run_tests.py'), '--native-build', str(build.absolute()), '--output', str(a.out.absolute())], cwd=ROOT).returncode
        return code, {'phase': 'SOFTWARE_TESTS', 'status': 'PASS' if code == 0 else 'FAIL', 'full_acceptance': False}
    if a.command == 'analyze':
        from rcwg_full.analysis.rebuild import rebuild
        result = rebuild(a.sealed_manifest, a.out)
        return 0, {'phase': 'OFFLINE_ANALYSIS', 'status': 'PASS', 'numerical_tables_hash': result['numerical_tables_hash'], 'formal_ready': False}
    if a.action == 'plan':
        from rcwg_full.campaign.planning import materialize_expected
        result = materialize_expected(json.loads(read(a.spec)), a.out)
        return 0, {'phase': 'CAMPAIGN_PLAN', 'status': 'PLANNED_ONLY', 'manifest_hash': result['manifest_hash'],
                   'primary': result['primary']['counts'], 'execution_authorized': False, 'formal_ready': False}
    if a.action in {'admit', 'run'}:
        from rcwg_full.campaign.admission import admit
        receipts = json.loads(read(a.receipts)) if a.action == 'run' else None
        result = admit(a.manifest, receipts)
        if result['blockers']: return 2, result
        if a.action == 'admit': return 0, result
        # Reached only after actual external prerequisites. Until the managed
        # launcher integration is complete this is a software gap, never an
        # external permission problem or a claimed successful execution.
        return 1, {'phase': 'CAMPAIGN_EXECUTION', 'status': 'IMPLEMENTATION_GAP', 'blockers': ['MANAGED_CAMPAIGN_RUNNER'], 'launch_performed': False}
    if a.action == 'reconcile':
        from collections import Counter
        from rcwg_full.campaign.sealing import check_expected
        from rcwg_full.campaign.store import CampaignStore
        manifest = check_expected(a.manifest); db_path = a.manifest.parent / 'campaign.sqlite3'
        if not db_path.exists():
            return 0, {'phase': 'RECONCILE', 'status': 'NO_ATTEMPTS', 'new_actions': 0, 'manifest_hash': manifest['manifest_hash']}
        store = CampaignStore(db_path, read_only=True)
        try: rows = store.reconcile()
        finally: store.close()
        return 0, {'phase': 'RECONCILE', 'status': 'READ_ONLY_COMPLETE', 'new_actions': 0,
                   'states': dict(Counter(r['status'] for r in rows)), 'reconcile_required': [r['id'] for r in rows if r['coordination'] == 'RECONCILE_REQUIRED']}
    if a.action == 'seal':
        from rcwg_full.campaign.sealing import check_expected, seal_package, relative_file
        manifest = check_expected(a.manifest)
        expected = [json.loads(line) for line in read(relative_file(a.manifest.parent, manifest['primary']['file'])).splitlines()]
        payload = json.loads(read(a.manifest.parent / 'attempts.json'))
        out = exclusive_directory(a.manifest.parent / 'sealed')
        result = seal_package(out, expected_slots=expected, observations=payload['observations'], mode=payload['mode'], source_identity=payload['source_identity'])
        return 0, {'phase': 'CAMPAIGN_SEAL', 'status': 'SEALED', 'manifest_hash': result['manifest_hash'], 'audit_released': False}
    if a.action == 'unseal':
        from rcwg_full.campaign.sealing import unseal
        result = unseal(a.manifest, json.loads(read(a.audit_receipt)))
        return 0, {'phase': 'AUDIT_UNSEAL', 'status': 'AUDIT_RELEASED', 'sealed_manifest_hash': result['sealed_manifest_hash']}
    raise ValueError('COMMAND_UNRECOGNIZED')


def main(argv=None):
    try:
        try: a = parser().parse_args(argv)
        except SystemExit as exc: return 0 if exc.code == 0 else 3
        code, result = dispatch(a)
    except PermissionError as exc:
        code, result = 2, {'phase': 'COMMAND', 'status': 'NOT_AUTHORIZED', 'blockers': [str(exc)]}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        code, result = 3, {'phase': 'INPUT', 'status': 'INPUT_INVALID', 'blockers': [str(exc)]}
    print(canonical(result).decode('utf-8'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
