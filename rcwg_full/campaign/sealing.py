"""Immutable artifact manifests, explicit audit release and offline integrity checks."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from rcwg_full.evidence import digest, read, sha, write, safe_path
import json


def relative_file(root, name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('MANIFEST_PATH')
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in {'..', '.'} for p in path.parts):
        raise ValueError('MANIFEST_PATH')
    target = safe_path(Path(root) / name)
    if not target.is_relative_to(Path(root).absolute()):
        raise ValueError('MANIFEST_PATH')
    return target


def read_manifest(path):
    path = safe_path(path)
    result = json.loads(read(path))
    claimed = result.get('manifest_hash')
    if not isinstance(claimed, str) or claimed != digest({k: v for k, v in result.items() if k != 'manifest_hash'}):
        raise ValueError('MANIFEST_HASH')
    return result


def check_expected(path):
    manifest = read_manifest(path)
    if manifest.get('schema_version') != 'FULL001_EXPECTED_1':
        raise ValueError('EXPECTED_MANIFEST_VERSION')
    root = Path(path).parent
    from collections import Counter
    identities = set(); files = [manifest['primary'], *manifest['diagnostics'].values()]
    for entry in files:
        raw = read(relative_file(root, entry['file']))
        if sha(raw) != entry['sha256'] or raw and not raw.endswith(b'\n'):
            raise ValueError('EXPECTED_FILE_HASH_OR_PARTIAL')
        counts = Counter()
        for line in raw.splitlines():
            row = json.loads(line)
            if row['slot_id'] in identities:
                raise ValueError('DUPLICATE_EXPECTED_SLOT')
            identities.add(row['slot_id']); counts[row['slot_kind']] += 1
        if dict(counts) != entry['counts'] or sum(counts.values()) != entry['total']:
            raise ValueError('EXPECTED_FILE_COUNTS')
    return manifest


def validate_receipt(receipt, *, action, subject_hash, actor_role, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if (receipt.get('approved') is not True or receipt.get('action') != action or
            receipt.get('subject_hash') != subject_hash or receipt.get('actor_role') != actor_role or
            not receipt.get('actor_id') or not receipt.get('receipt_id')):
        raise PermissionError('EXACT_RECEIPT_REQUIRED')
    try:
        start = datetime.fromisoformat(receipt['valid_from'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(receipt['valid_until'].replace('Z', '+00:00'))
        if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
            raise ValueError('expiry')
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError('RECEIPT_TIME_INVALID') from exc
    return digest(receipt)


def seal_package(root, *, expected_slots, observations, mode, source_identity, extra_files=()):
    """Seal already persisted observations; never synthesize absent slot outcomes."""
    root = safe_path(root)
    if mode not in {'ENGINEERING_NATIVE', 'ENGINEERING_REPLAY', 'FORMAL'}:
        raise ValueError('SEAL_MODE')
    expected_ids = [s['slot_id'] for s in expected_slots]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError('DUPLICATE_EXPECTED_SLOT')
    known = set(expected_ids); observed = set(); attempts = set()
    active = {'RUNNING', 'CLAIMED', 'UNKNOWN', 'SENT_UNCONFIRMED', 'NOT_RUN'}
    for row in observations:
        if row['slot_id'] not in known or row['attempt_id'] in attempts or row['mode'] != mode:
            raise ValueError('SEAL_OBSERVATION_IDENTITY')
        if row['status'] in active:
            raise ValueError('CORE_NOT_TERMINAL')
        observed.add(row['slot_id']); attempts.add(row['attempt_id'])
    if known != observed:
        raise ValueError('CORE_RECORDS_MISSING')
    files = {'expected.json': write(root / 'expected.json', expected_slots),
             'observations.json': write(root / 'observations.json', observations)}
    for name in extra_files:
        if name in files or name in {'sealed-manifest.json', 'audit-release.json'}:
            raise ValueError('SEAL_FILE_COLLISION')
        files[name] = sha(read(relative_file(root, name)))
    manifest = {'schema_version': 'FULL001_SEALED_1', 'mode': mode, 'status': 'SEALED',
                'core_complete': True, 'expected_count': len(known), 'attempt_count': len(attempts),
                'files': files, 'source_identity': source_identity, 'formal_ready': False}
    manifest['manifest_hash'] = digest(manifest)
    write(root / 'sealed-manifest.json', manifest)
    return manifest


def verify_seal(path):
    manifest = read_manifest(path)
    if manifest.get('schema_version') != 'FULL001_SEALED_1' or manifest.get('status') != 'SEALED' or manifest.get('core_complete') is not True:
        raise ValueError('SEALED_COMPLETE_PACKAGE_REQUIRED')
    for name, expected in manifest['files'].items():
        if sha(read(relative_file(Path(path).parent, name))) != expected:
            raise ValueError('SEALED_ARTIFACT_CHANGED:' + name)
    return manifest


def unseal(path, receipt):
    manifest = verify_seal(path)
    receipt_hash = validate_receipt(receipt, action='AUDIT_UNSEAL', subject_hash=manifest['manifest_hash'], actor_role='Auditor')
    release = {'schema_version': 'FULL001_AUDIT_RELEASE_1', 'sealed_manifest_hash': manifest['manifest_hash'],
               'receipt_hash': receipt_hash, 'actor_id': receipt['actor_id'], 'actor_role': 'Auditor',
               'receipt_id': receipt['receipt_id'], 'action': 'AUDIT_UNSEAL', 'formal_ready': False}
    write(Path(path).parent / 'audit-release.json', release)
    return release


def authorized_package(path):
    manifest = verify_seal(path)
    release = json.loads(read(Path(path).parent / 'audit-release.json'))
    if (release.get('schema_version') != 'FULL001_AUDIT_RELEASE_1' or release.get('action') != 'AUDIT_UNSEAL' or
            release.get('sealed_manifest_hash') != manifest['manifest_hash'] or release.get('actor_role') != 'Auditor'):
        raise PermissionError('AUDIT_RELEASE_REQUIRED')
    return manifest, release
