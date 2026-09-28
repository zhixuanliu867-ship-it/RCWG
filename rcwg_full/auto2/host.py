"""Finite delegated host claims; the legacy Owner-receipt path remains separate."""
from copy import deepcopy
from pathlib import Path
import json,sqlite3,uuid
from rcwg_full.evidence import read,write,canonical,digest,sha,source_hashes
from rcwg_full.runtime.host_scope import HostClaim,run_identity
from rcwg_full.runtime.measurement import runtime_identity
from rcwg_full.runtime.launch import FullDriver,FullLimits
from rcwg_native.metrology import LinuxFS


class DelegatedHostClaim(HostClaim):
    def __init__(self,scope,authority,task,build,attempt_id,*,identity_reader=runtime_identity):
        self.scope=deepcopy(scope);self.authority=deepcopy(authority);self.task=deepcopy(task);self.build=build
        self.identity_reader=identity_reader;self.attempt_id=str(uuid.UUID(attempt_id));self.run_id=run_identity(attempt_id)
        if (scope.get('revision')!='AUTO2_HOST_SCOPE_1' or authority.get('authority_kind')!='USER_TASK_DELEGATION'
            or scope.get('authority_hash')!=digest(authority) or scope.get('manual_signature') is not False):raise PermissionError('AUTO2_HOST_AUTHORITY')
        if authority['user_text_sha256']!=sha(authority['user_text'].encode('utf8')):raise PermissionError('AUTO2_ROOT_TEXT')
        self.recheck();self.ledger=Path(scope['claim_ledger']);self.ledger.parent.mkdir(parents=True,exist_ok=True)
        self.binding={'scope_hash':digest(scope),'authority_hash':digest(authority),'attempt_id':self.attempt_id,
            'run_id':self.run_id,'runtime_identity_hash':digest(scope['runtime_identity']),'task_hash':digest(task),'manual_signature':False}
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS claims (run_id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL, scope_hash TEXT NOT NULL, slot_id TEXT NOT NULL, state TEXT NOT NULL, binding TEXT NOT NULL, evidence TEXT)')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM claims WHERE attempt_id=?',(self.attempt_id,)).fetchone():raise PermissionError('HOST_CLAIM_ALREADY_CONSUMED_OR_UNCERTAIN')
            count=db.execute('SELECT count(*) FROM claims WHERE scope_hash=?',(digest(scope),)).fetchone()[0]
            if count>=scope['max_attempts']:raise PermissionError('HOST_FINITE_SCOPE_EXHAUSTED')
            if db.execute("SELECT 1 FROM claims WHERE scope_hash=? AND state!='CONSUMED'",(digest(scope),)).fetchone():raise PermissionError('HOST_PREVIOUS_CLAIM_UNRECONCILED')
            db.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,NULL)',(self.run_id,self.attempt_id,digest(scope),self.attempt_id,'CLAIMED',canonical(self.binding).decode()))

    def recheck(self):
        from datetime import datetime,timezone
        if datetime.now(timezone.utc)>=datetime.fromisoformat(self.scope['expires_at']):raise PermissionError('HOST_SCOPE_EXPIRED')
        observation=self.scope.get('observation_profile')
        actual=self.identity_reader(self.task,self.build,affinity=self.scope['affinity'],**({'observation_profile':observation} if observation else {}))
        if actual!=self.scope['runtime_identity']:raise PermissionError('HOST_RUNTIME_APPLICABILITY_CHANGED')
        if digest(self.task) not in self.scope['task_hashes']:raise PermissionError('HOST_TASK_NOT_IN_FINITE_SCOPE')
        if not 0<self.scope['max_attempts']<=6114:raise PermissionError('HOST_ATTEMPT_BOUND')
        if actual['host']['system']!='Linux' or actual['host']['boot_id_sha256']=='UNAVAILABLE':raise PermissionError('REAL_HOST_REQUIRED')


def delegated_driver(scope,authority,task,build,attempt_id,*,fs_factory=None,identity_reader=runtime_identity):
    claim=DelegatedHostClaim(scope,authority,task,build,attempt_id,identity_reader=identity_reader)
    r=task['resources'];affinity=tuple(scope['affinity'])
    if len(affinity)!=r['cpu_slots']:raise PermissionError('HOST_CPU_SLOT_BINDING')
    limits=FullLimits(memory_max=r['worker_memory_limit_bytes'],cpu_quota_us=100000*r['cpu_slots'],
        affinity=affinity,threads=r['cpu_slots'],timeout_s=r['wall_timeout_s']);limits.validate()
    root=Path(scope['delegated_root'])
    fs=(fs_factory or LinuxFS)(root,approval={'approved':True,'delegated_root':str(root),'permission':'NATIVE001_N4_PER_RUN_CGROUP'})
    calibration=scope.get('calibration_package')
    if calibration:
        from .calibration import validate_auto2_calibration
        validate_auto2_calibration(calibration,scope['runtime_identity'],authority_hash=digest(authority))
    driver=FullDriver(fs,claim.run_id,limits);driver.claim=claim;driver.calibration=calibration
    driver.full001_authorization={**claim.binding,'pids_max':scope['pids_max'],'output_file_max_bytes':scope['output_file_max_bytes'],
                                 'per_run_total_output_bytes':scope['per_run_total_output_bytes']}
    return driver
