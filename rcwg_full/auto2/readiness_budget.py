"""One prospective allocation amendment under the existing root and epoch.

No reservation is released or reimported. This authorizes local budget admission
only; formal API requests still need their separate frozen technical admission.
"""
import json
from datetime import datetime,timezone
from rcwg_full.evidence import digest,canonical,sha
from .dispatch import DispatchGate

REVISION='AUTO2_FORMAL_READINESS_BUDGET_1'


def amendment(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='formal_readiness_budget'").fetchone():return None
    row=db.execute('SELECT body,sha256 FROM formal_readiness_budget WHERE id=1').fetchone()
    if not row:raise PermissionError('READINESS_BUDGET_MISSING')
    value=json.loads(row[0])
    root=json.loads(db.execute('SELECT body FROM root WHERE id=1').fetchone()[0])
    from .recovery import active_epoch
    epoch=active_epoch(db)
    if (digest(value)!=row[1] or value.get('revision')!=REVISION or value.get('root_sha256')!=digest(root)
        or not epoch or value.get('epoch_sha256')!=digest(epoch)
        or value.get('user_text_sha256')!=sha(value.get('user_text','').encode())
        or value['new_epoch_cap_microusd']!=root['ceiling_microusd']-value['cleanup_microusd']-epoch['baseline_reserved_microusd']
        or value['cleanup_microusd']!=10_000_000 or value['allocation_a_microusd']+value['allocation_b_microusd']!=75_000_000
        or not 25_000_000<=value['allocation_a_microusd']<=30_000_000
        or value.get('manual_signature') is not False):
        raise PermissionError('READINESS_BUDGET_BINDING')
    return value


def install(state, *, user_text, attachment_sha256, expected_rows_sha256, expected_epoch_sha256, isolated_requests):
    from .budget_extension import reservation_snapshot,effective_recovery_cap
    from .recovery import active_epoch
    if not user_text.strip() or len(attachment_sha256)!=64:raise PermissionError('READINESS_AUTHORITY_REQUIRED')
    with DispatchGate(state).locked(),state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if amendment(db):raise PermissionError('READINESS_BUDGET_ALREADY_APPENDED')
        epoch=active_epoch(db)
        if not epoch or digest(epoch)!=expected_epoch_sha256:raise PermissionError('READINESS_EPOCH_CHANGED')
        if db.execute('SELECT status FROM dispatch_control WHERE id=1').fetchone()[0]!='OPEN':raise PermissionError('READINESS_DISPATCH_NOT_QUIESCENT')
        rows=reservation_snapshot(db)
        if digest(rows)!=expected_rows_sha256 or any(row[4]=='RESERVED_BEFORE_IO' for row in rows):raise PermissionError('READINESS_HISTORY_CHANGED')
        unknown={row[0]:row[3] for row in rows if row[2] in {'G','E','COUNT'} and row[4] in {'UNKNOWN','SENT_UNCONFIRMED'}}
        if unknown!=isolated_requests or len(unknown)!=2:raise PermissionError('READINESS_NEW_UNKNOWN')
        if (state.policy['budget']['phase_a_infrastructure_allocation']!=25 or
            state.policy['budget']['remaining_live_and_reference_allocation']!=50 or
            state.policy['budget']['cleanup_and_billing_lag_reserve']!=10):raise PermissionError('READINESS_POLICY_ALLOCATION')
        value={'revision':REVISION,'root_sha256':digest(state.authority),'epoch_sha256':digest(epoch),
            'user_text':user_text,'user_text_sha256':sha(user_text.encode()),'attachment_sha256':attachment_sha256,
            'prior_rows_sha256':expected_rows_sha256,'reserved_at_install_microusd':sum(row[3] for row in rows),
            'old_epoch_cap_microusd':effective_recovery_cap(db,epoch),
            'new_epoch_cap_microusd':state.authority['ceiling_microusd']-10_000_000-epoch['baseline_reserved_microusd'],
            'allocation_a_microusd':30_000_000,'allocation_b_microusd':45_000_000,'cleanup_microusd':10_000_000,
            'isolated_requests':unknown,'provider_active_count':None,'new_unknown_stops':True,
            'reservation_release':False,'root_reset':False,'epoch_reset':False,'manual_signature':False,
            'created_at':datetime.now(timezone.utc).isoformat()}
        db.execute('CREATE TABLE formal_readiness_budget(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)')
        db.execute('INSERT INTO formal_readiness_budget VALUES(1,?,?)',(canonical(value).decode(),digest(value)))
        amendment(db)
        return value


def register_host(state,scope,lease,request_id):
    """One frozen VM reservation; this is not a model dispatch exception."""
    from .cloud import validate_lease
    validate_lease(lease,state.policy);state.validate_scope(scope,scope['identity'])
    if (scope['stage']!='A_INFRA' or scope['limits']!={'VM':1} or lease['reserved_microusd']>5_000_000
        or lease['hours']>4 or scope['ceiling_microusd']!=lease['reserved_microusd']):raise PermissionError('READINESS_HOST_BOUND')
    with DispatchGate(state).locked(),state.db() as db:
        db.execute('BEGIN IMMEDIATE');value=amendment(db)
        if not value:raise PermissionError('READINESS_BUDGET_REQUIRED')
        if db.execute('SELECT 1 FROM reservations WHERE id=?',(request_id,)).fetchone():raise PermissionError('READINESS_NO_REPLAY')
        db.execute('CREATE TABLE IF NOT EXISTS formal_readiness_host(id INTEGER PRIMARY KEY CHECK(id=1),request_id TEXT UNIQUE,scope TEXT,amount INTEGER,lease TEXT)')
        if db.execute('SELECT 1 FROM formal_readiness_host').fetchone():raise PermissionError('READINESS_ONE_HOST')
        db.execute('INSERT INTO formal_readiness_host VALUES(1,?,?,?,?)',(request_id,digest(scope),lease['reserved_microusd'],canonical(lease).decode()))


def check_host(db,request_id,kind,amount,scope):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='formal_readiness_host'").fetchone():return False
    row=db.execute('SELECT request_id,scope,amount FROM formal_readiness_host WHERE id=1').fetchone()
    return bool(amendment(db) and row and (request_id,scope,amount)==row and kind=='VM')
