"""Validate an explicitly reviewed calibration package against final runtime.

This consumes evidence; it never performs calibration loads or reuses N4 slots.
"""
import json
from pathlib import Path
from rcwg_full.evidence import read, sha, digest, safe_path
from rcwg_full.campaign.sealing import relative_file, validate_receipt

REQUIRED = {'cpu_accounting', 'peak_memory', 'descendants', 'timeout', 'oom_attribution',
            'cleanup', 'counter_failure', 'sampler_overhead', 'full_worker_integration'}


def validate_calibration(path, identity):
    path = safe_path(path); package = json.loads(read(path)); root = path.parent
    if package.get('revision') != 'FULL001_CALIBRATION_1' or package.get('runtime_identity') != identity:
        raise PermissionError('CALIBRATION_RUNTIME_MISMATCH')
    body = {k: v for k, v in package.items() if k != 'audit_receipt'}
    validate_receipt(package.get('audit_receipt'), action='CALIBRATION', subject_hash=digest(body), actor_role='Auditor')
    checks = package.get('checks', {})
    if set(checks) != REQUIRED: raise PermissionError('CALIBRATION_CHECK_COVERAGE')
    for name, entry in checks.items():
        raw = read(relative_file(root, entry['file']))
        if sha(raw) != entry['sha256']: raise PermissionError('CALIBRATION_EVIDENCE_HASH')
        evidence = json.loads(raw)
        if (evidence.get('check') != name or evidence.get('status') != 'PASS' or
                evidence.get('runtime_identity_hash') != digest(identity) or
                evidence.get('environment') != 'REAL_APPROVED_FULL_HOST' or not evidence.get('raw_files')):
            raise PermissionError('CALIBRATION_CHECK_NOT_APPLICABLE')
        for filename, expected in evidence['raw_files'].items():
            if sha(read(relative_file(root, filename))) != expected: raise PermissionError('CALIBRATION_RAW_HASH')
    return sha(read(path))
