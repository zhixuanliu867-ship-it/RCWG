"""One bounded independent SERVICE_ONLY epoch; the old trial remains unknown."""
import json
from .budget_extension import effective_recovery_cap
from rcwg_full.evidence import digest, canonical, sha
from .dispatch import DispatchGate


def active_epoch(db):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recovery_epoch'").fetchone()
    if not exists:return None
    row=db.execute('SELECT body FROM recovery_epoch WHERE id=1').fetchone()
    return json.loads(row[0]) if row else None


def install_epoch(state, amendment, scope):
    """Only explicitly frozen independent requests can pass the historical fuse."""
    a=amendment
    if a.get('revision')!='AUTO2_RECOVERY_POLICY_1' or a.get('epoch')!=1:
        raise PermissionError('RECOVERY_ONLY_ONE_EPOCH')
    if a.get('authority_kind')!='USER_TASK_DELEGATION' or a.get('root_sha256')!=digest(state.authority):
        raise PermissionError('RECOVERY_ROOT_MISMATCH')
    text=a.get('user_text','')
    if not text or a.get('user_text_sha256')!=sha(text.encode()):raise PermissionError('RECOVERY_USER_AUTHORITY')
    if a.get('measurement_profile')!='SERVICE_ONLY' or a.get('manual_signature') is not False:
        raise PermissionError('RECOVERY_PROFILE')
    if a.get('client_concurrency')!=1 or a.get('provider_active_count') is not None:
        raise PermissionError('RECOVERY_UNKNOWN_PROVIDER_STATE')
    if a.get('hard_provider_concurrency_required') is not False:
        raise PermissionError('RECOVERY_HARD_PROVIDER_LIMIT_UNPROVEN')
    if any(a.get(k) is not True for k in ['pure_generation_without_external_tools','old_dispatchers_stopped',
           'cleanup_complete','transport_tests_pass','independent_unstarted_jobs','original_initial_limits_cumulative']):
        raise PermissionError('RECOVERY_PREREQUISITE_MISSING')
    maximum=a.get('maximum_additional_microusd')
    if type(maximum) is not int or not 0<maximum<=5_000_000:raise PermissionError('RECOVERY_SUBCAP')
    if a.get('scope_sha256')!=digest(scope) or scope['stage']!='B_INITIAL':raise PermissionError('RECOVERY_SCOPE')
    state.validate_scope(scope,scope['identity'])
    planned=a.get('planned_requests',[])
    if not planned or len({p['request_id'] for p in planned})!=len(planned):raise PermissionError('RECOVERY_REQUEST_SET')
    if any(p['kind'] not in {'E','COUNT'} or type(p['microusd']) is not int or p['microusd']<0 or
           not isinstance(p.get('body_sha256'),str) or len(p['body_sha256'])!=64 for p in planned):
        raise PermissionError('RECOVERY_FIXED_E_ONLY')
    if sum(p['microusd'] for p in planned)>maximum:raise PermissionError('RECOVERY_COMPLETE_BLOCK_UNAFFORDABLE')
    gate=DispatchGate(state)
    with gate.locked():
        with state.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if active_epoch(db) is not None:raise PermissionError('RECOVERY_ONLY_ONE_EPOCH')
            current=db.execute('SELECT status FROM dispatch_control WHERE id=1').fetchone()[0]
            if current=='ACTIVE':raise PermissionError('RECOVERY_ACTIVE_CLIENT')
            rows=db.execute('SELECT id,kind,amount,status FROM reservations ORDER BY id').fetchall()
            if digest(rows)!=a.get('prior_reservation_rows_sha256'):raise PermissionError('RECOVERY_HISTORY_CHANGED')
            unknown=[r[0] for r in rows if r[1] in {'G','E','COUNT'} and r[3] in {'SENT_UNCONFIRMED','UNKNOWN','RESERVED_BEFORE_IO'}]
            if not unknown or sorted(unknown)!=a.get('isolated_request_ids'):
                raise PermissionError('RECOVERY_ISOLATION_SET')
            if any(r[3]=='RESERVED_BEFORE_IO' for r in rows):raise PermissionError('RECOVERY_UNFINISHED_LOCAL_RESERVATION')
            if {p['request_id'] for p in planned}&{r[0] for r in rows}:raise PermissionError('RECOVERY_NO_REPLAY')
            used=sum(r[2] for r in rows)
            if used!=a.get('baseline_reserved_microusd'):raise PermissionError('RECOVERY_BASELINE_AMOUNT')
            cleanup=int(state.policy['budget']['cleanup_and_billing_lag_reserve']*1_000_000)
            if used+sum(p['microusd'] for p in planned)>state.authority['ceiling_microusd']-cleanup:
                raise PermissionError('RECOVERY_CUMULATIVE_BUDGET')
            initial=db.execute("SELECT r.kind,r.amount FROM reservations r JOIN scopes s ON r.scope=s.id WHERE json_extract(s.body,'$.stage')='B_INITIAL'").fetchall()
            caps=state.policy['initial_live']
            for kind,key in [('G','max_g_requests'),('E','max_e_requests'),('COUNT','max_count_requests')]:
                if sum(k==kind for k,_ in initial)+sum(p['kind']==kind for p in planned)>caps[key]:
                    raise PermissionError('RECOVERY_INITIAL_COMPLETE_BLOCK_LIMIT')
            if (len(initial)+len(planned)>caps['max_total_requests'] or
                sum(v for _,v in initial)+sum(p['microusd'] for p in planned)>caps['cost_subcap_usd']*1_000_000):
                raise PermissionError('RECOVERY_INITIAL_COMPLETE_BLOCK_LIMIT')
            db.execute('CREATE TABLE recovery_epoch(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
            db.execute('INSERT INTO recovery_epoch VALUES(1,?)',(canonical(a).decode(),))
            gate._record(db,'OPEN',{'reason':'EXPLICIT_INDEPENDENT_RECOVERY_EPOCH','amendment_sha256':digest(a),
                'isolated_request_ids':unknown,'original_batch_status':'PAUSED_EXTERNAL','provider_active_count':None})


def check_dispatch(db, request_id, kind, body_hash, scope_hash):
    epoch=active_epoch(db)
    if epoch is None:return set()
    from .next_live import check
    if check(db,request_id,kind,body_hash,scope_hash):
        from .independent_resume import isolation_for
        from .next_live import _row
        return isolation_for(db,_row(db,request_id)['manifest'],scope_hash) or set(epoch['isolated_request_ids'])
    from .recovery_development import check_development
    if check_development(db,request_id,kind,body_hash,scope_hash):return set(epoch['isolated_request_ids'])
    planned=next((p for p in epoch['planned_requests'] if p['request_id']==request_id),None)
    if planned is None or planned['kind']!=kind or planned['body_sha256']!=body_hash or epoch['scope_sha256']!=scope_hash:
        raise PermissionError('RECOVERY_REQUEST_NOT_PREREGISTERED')
    reserved={r[0] for r in db.execute('SELECT id FROM reservations')}
    next_request=next((p for p in epoch['planned_requests'] if p['request_id'] not in reserved),None)
    if next_request is None or next_request['request_id']!=request_id:raise PermissionError('RECOVERY_FROZEN_ORDER')
    return set(epoch['isolated_request_ids'])


def check_reservation(db, request_id, kind, amount, scope_hash):
    epoch=active_epoch(db)
    if epoch is None:return
    from .recovery_development import check_development
    from .next_live import check
    development=check(db,request_id,kind,None,scope_hash,amount) or check_development(db,request_id,kind,None,scope_hash,amount)
    planned=next((p for p in epoch['planned_requests'] if p['request_id']==request_id),None)
    if not development and (planned is None or planned['kind']!=kind or planned['microusd']!=amount or scope_hash!=epoch['scope_sha256']):
        raise PermissionError('RECOVERY_RESERVATION_NOT_PREREGISTERED')
    total=db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations').fetchone()[0]
    if total+amount-epoch['baseline_reserved_microusd']>effective_recovery_cap(db,epoch):
        raise PermissionError('RECOVERY_CUMULATIVE_SUBCAP')
