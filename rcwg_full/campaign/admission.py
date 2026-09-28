"""Check exact, versioned prerequisites before any host or paid-service action."""
from pathlib import Path
import json
from rcwg_full.evidence import digest, read, sha
from .sealing import check_expected, relative_file, validate_receipt

REQUIRED_GATES = ('software', 'host', 'data', 'services', 'references', 'statistics',
                  'licenses', 'permissions', 'source', 'binary', 'dependencies',
                  'prompts', 'operators', 'conditions', 'measurement')


def admit(manifest_path, receipts=None):
    manifest = check_expected(manifest_path)
    root = Path(manifest_path).parent
    blockers = []; evidence = {}
    freeze_path = root / 'freeze.json'
    if not freeze_path.exists():
        blockers.append('FREEZE_MANIFEST_MISSING')
    else:
        freeze = json.loads(read(freeze_path))
        if freeze.get('expected_manifest_hash') != manifest['manifest_hash'] or freeze.get('spec_hash') != manifest['spec_hash']:
            blockers.append('FREEZE_IDENTITY_MISMATCH')
        for name in REQUIRED_GATES:
            entry = freeze.get('gates', {}).get(name, {})
            if entry.get('status') != 'PASS':
                blockers.append('GATE_' + name.upper())
                continue
            try:
                raw = read(relative_file(root, entry['evidence_file']))
                if sha(raw) != entry['sha256']:
                    raise ValueError('hash')
                proof = json.loads(raw)
                if proof.get('status') != 'PASS' or proof.get('scope_hash') != entry['scope_hash']:
                    raise ValueError('scope')
                evidence[name] = entry['sha256']
            except (OSError, KeyError, ValueError, TypeError):
                blockers.append('GATE_EVIDENCE_' + name.upper())
        try:
            validate_receipt((receipts or {}).get('formal_launch', {}), action='FORMAL_LAUNCH',
                             subject_hash=digest(freeze), actor_role='Owner')
        except PermissionError as exc:
            blockers.append(str(exc))
        for scope in ['host', 'paid_services']:
            try:
                validate_receipt((receipts or {}).get(scope, {}), action=scope.upper(),
                                 subject_hash=freeze.get('authorization_scopes', {}).get(scope), actor_role='Owner')
            except PermissionError:
                blockers.append('EXACT_' + scope.upper() + '_RECEIPT_REQUIRED')
    return {'phase': 'FORMAL_ADMISSION', 'status': 'ADMITTED' if not blockers else 'BLOCKED_NOT_FROZEN',
            'blockers': blockers, 'expected_manifest_hash': manifest['manifest_hash'],
            'evidence': evidence, 'launch_performed': False, 'formal_ready': not blockers}
