"""AUTO2 calibration admission retains actual evidence, without auditor signatures."""
import json,math
from pathlib import Path
from rcwg_full.evidence import read,sha,digest
from rcwg_full.campaign.sealing import relative_file


def validate_auto2_calibration(path,identity,*,authority_hash=None):
    from rcwg_full.runtime.calibration import REQUIRED
    path=Path(path);root=path.parent;package=json.loads(read(path))
    if package.get('revision')!='AUTO2_CALIBRATION_1' or package.get('runtime_identity')!=identity:
        raise PermissionError('CALIBRATION_RUNTIME_MISMATCH')
    authority=json.loads(read(relative_file(root,package['authority_file'])))
    if (authority.get('authority_kind')!='USER_TASK_DELEGATION' or package.get('manual_signature') is not False
        or sha(authority['user_text'].encode())!=authority['user_text_sha256']
        or digest(authority)!=package['authority_hash'] or (authority_hash and authority_hash!=digest(authority))):
        raise PermissionError('AUTO2_CALIBRATION_AUTHORITY')
    if set(package.get('checks',{}))!=REQUIRED:raise PermissionError('CALIBRATION_CHECK_COVERAGE')
    for name,entry in package['checks'].items():
        raw=read(relative_file(root,entry['file']))
        if sha(raw)!=entry['sha256']:raise PermissionError('CALIBRATION_EVIDENCE_HASH')
        evidence=json.loads(raw)
        if (evidence.get('check')!=name or evidence.get('status')!='PASS'
            or evidence.get('runtime_identity_hash')!=digest(identity)
            or evidence.get('environment')!='REAL_AUTO2_HOST' or not evidence.get('raw_files')):
            raise PermissionError('CALIBRATION_CHECK_NOT_APPLICABLE')
        for filename,expected in evidence['raw_files'].items():
            if sha(read(relative_file(root,filename)))!=expected:raise PermissionError('CALIBRATION_RAW_HASH')
        if name=='sampler_overhead':
            if evidence.get('sample_interval_ms')!=100 or set(evidence.get('families',{}))!={'cpu','short','graph','stream','shared','disk'}:
                raise PermissionError('CALIBRATION_SAMPLER_COVERAGE')
            for family,stat in evidence['families'].items():
                upper=stat.get('ci95_upper')
                if (stat.get('pairs')!=20 or type(upper) not in {int,float} or not math.isfinite(upper)
                    or upper>.03 or stat.get('off_batch_min_ns',0)<100_000_000):
                    raise PermissionError('CALIBRATION_OVERHEAD_NOT_PASSED')
    return sha(read(path))
