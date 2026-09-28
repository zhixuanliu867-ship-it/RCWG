"""One explicit two-unknown isolation decision; no replay or new epoch."""
import json
from rcwg_full.evidence import digest,canonical,sha
from rcwg_full.services.timeout3 import PROFILE as TIMEOUT,validate
from .dispatch import DispatchGate
from .budget_extension import reservation_snapshot
from . import next_live as nl

PROFILE='INDEPENDENT_F2_F3_RESUME_1'
TERMINAL={'DONE','SKIPPED','DEFERRED','RETRIED'}

def active(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='independent_resume'").fetchone():return None
    body,checksum=db.execute('SELECT body,sha256 FROM independent_resume WHERE id=1').fetchone()
    value=json.loads(body)
    if digest(value)!=checksum or value['decision']['revision']!=PROFILE:raise PermissionError('RESUME_RECEIPT_CHANGED')
    return value

def eligible(db,index,mid,isolated):
    """A logical slot is fresh only if every physical stage is unattempted.

    P1 physical may depend on its own fresh logical stage, never another job.
    The attempted unknown slot and all its X/dependent stages stay excluded.
    """
    manifest,_=nl._manifest(db,mid);rows=nl._rows(db,mid)
    planned={r['id']:r for r in manifest['requests']};allowed=[];excluded=[]
    for job in manifest['block']['generations']:
        group=[r for r in rows if r['logical_slot']==job['id']]
        fresh=bool(group)
        for r in group:
            with index.lock:seen=index.db.execute('SELECT 1 FROM requests WHERE id=?',(r['id'],)).fetchone()
            if r['state']!='PENDING' or r['attempt']!=0 or r['bound_hash'] is not None or r['id'] in isolated or seen or db.execute('SELECT 1 FROM reservations WHERE id=?',(r['id'],)).fetchone():fresh=False
            if r['id'] in planned and any(r[k]!=v for k,v in planned[r['id']].items()):raise PermissionError('RESUME_RECIPE_CHANGED')
        if not fresh:excluded.append(job['id']);continue
        logical=[r for r in group if r['kind']=='G' and r['stage']=='logical']
        expected=2 if job['protocol']=='P0' else 4
        if len(group)!=expected:raise PermissionError('RESUME_STAGE_CLOSURE')
        for r in group:
            q=r['recipe']
            if q['category']!='G' or q['request_profile']!='FULL001_REQUEST_4' or q['attempt_id']!=job['id']:raise PermissionError('RESUME_REQUEST_PROFILE')
            if job['protocol']=='P1' and (len(logical)!=1 or q['logical_request_id']!=logical[0]['id'] or q['logical_request_id'] in isolated):raise PermissionError('RESUME_UNKNOWN_OR_CROSS_SLOT_DEPENDENCY')
        allowed.extend(r['id'] for r in group)
    return allowed,excluded

def install(state,index,scope,decision):
    from .recovery import active_epoch
    d=decision;validate(d.get('timeout_profile'))
    state.validate_scope(scope,scope['identity'])
    if (d.get('revision')!=PROFILE or not d.get('user_text') or not d.get('user_reference')
        or d.get('user_text_sha256')!=sha(d['user_text'].encode())
        or d.get('root_sha256')!=digest(state.authority) or d.get('client_concurrency')!=1
        or d.get('provider_active_count') is not None or d.get('accept_unknown_provider_activity') is not True
        or d.get('old_local_dispatchers_stopped') is not True or d.get('offline_acceptance_pass') is not True
        or d.get('new_unknown_stops') is not True or d.get('families')!=['F2','F3']):raise PermissionError('RESUME_EXPLICIT_AUTHORITY_REQUIRED')
    if (scope['stage']!='B_DEVELOPMENT' or scope.get('capacity_retry_profile')!='CAPACITY_RETRY_1'
        or scope['identity']!=d['execution_identity'] or scope['identity']['manifest']!=d['manifest_sha256']):raise PermissionError('RESUME_SCOPE_IDENTITY')
    with DispatchGate(state).locked() as gate,state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if active(db):raise PermissionError('RESUME_ALREADY_INSTALLED_NO_RESET')
        epoch=active_epoch(db);before=reservation_snapshot(db)
        if not epoch or digest(epoch)!=d['epoch_sha256'] or digest(before)!=d['prior_reservations_sha256']:raise PermissionError('RESUME_HISTORY_CHANGED')
        unknown=[r for r in before if r[2] in {'G','E','COUNT'} and r[4] in {'UNKNOWN','SENT_UNCONFIRMED','RESERVED_BEFORE_IO'}]
        isolated=d['isolated_holds']
        if len(isolated)!=2 or {r[0]:r[3] for r in unknown}!=isolated or any(r[4]=='RESERVED_BEFORE_IO' for r in unknown):raise PermissionError('RESUME_ISOLATION_SET')
        if not set(epoch['isolated_request_ids'])<set(isolated):raise PermissionError('RESUME_ORIGINAL_ISOLATION_CHANGED')
        control,detail=db.execute('SELECT status,detail FROM dispatch_control').fetchone();detail=json.loads(detail)
        if control!='FUSED' or detail.get('request_id') not in set(isolated)-set(epoch['isolated_request_ids']):raise PermissionError('RESUME_WRONG_FUSE')
        for rid in isolated:
            result=nl._lookup_result(index,rid)
            if not result or result['status'] not in {'UNKNOWN','SENT_UNCONFIRMED'} or digest(result)!=d['isolated_result_hashes'][rid]:raise PermissionError('RESUME_UNKNOWN_EVIDENCE_CHANGED')
        if detail.get('result_sha256')!=d['isolated_result_hashes'][detail['request_id']]:raise PermissionError('RESUME_FUSE_EVIDENCE_CHANGED')
        mid=d['manifest_sha256'];manifest,oldscope=nl._manifest(db,mid)
        if manifest['block']['generations'][0]['task_id'].split('-')[0]!='F2':raise PermissionError('RESUME_F2_ONLY')
        if db.execute('SELECT id FROM next_live_manifests ORDER BY rowid DESC LIMIT 1').fetchone()[0]!=mid:raise PermissionError('RESUME_LATEST_PACKET_ONLY')
        allowed,excluded=eligible(db,index,mid,set(isolated))
        if not allowed or allowed!=d['allowed_request_ids'] or excluded!=d['excluded_logical_slots']:raise PermissionError('RESUME_ELIGIBLE_SET_CHANGED')
        rows=nl._rows(db,mid);ids={r['id'] for r in rows};spent=[r for r in before if r[0] in ids]
        pool=manifest['retry_pool']-sum(r['attempt']>0 for r in rows)
        cost=sum(r['amount'] for r in rows if r['id'] in allowed)+pool*max(r['amount'] for r in rows)
        remaining=manifest['complete_packet_upper_microusd']-sum(r[3] for r in spent)
        limits={k:20-sum(r[2]==k for r in spent) for k in ['G','COUNT']};limits['E']=0
        if pool<0 or scope['ceiling_microusd']!=remaining or scope['limits']!=limits or cost>remaining or d['remaining_packet_upper_microusd']!=cost:raise PermissionError('RESUME_NO_BUDGET_RESET')
        nl._limits(state,db,cost)
        receipt={'decision':d,'old_scope_sha256':oldscope,'scope_sha256':digest(scope),'remaining_retry_pool':pool,
                 'unknown_results_unchanged':True,'old_reservations_sha256':digest(before)}
        db.execute('CREATE TABLE independent_resume(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)')
        db.execute('INSERT INTO independent_resume VALUES(1,?,?)',(canonical(receipt).decode(),digest(receipt)))
        db.execute('UPDATE next_live_manifests SET scope=? WHERE id=?',(digest(scope),mid))
        nl._event(db,'EXPLICIT_INDEPENDENT_F2_F3_RESUME',{'receipt_sha256':digest(receipt),'old_scope':oldscope,'new_scope':digest(scope)})
        gate._record(db,'OPEN',{'reason':PROFILE,'receipt_sha256':digest(receipt),'provider_active_count':None})
        if reservation_snapshot(db)!=before:raise PermissionError('RESUME_HISTORY_CHANGED')
        return receipt

def isolation_for(db,mid,scope_hash):
    """The extra isolation applies only to the exact F2 scope or its one F3."""
    a=active(db)
    if not a:return None
    d=a['decision']
    if mid==d['manifest_sha256']:
        if scope_hash!=a['scope_sha256']:return None
        return set(d['isolated_holds'])
    manifest,_=nl._manifest(db,mid)
    if manifest.get('previous_packet_sha256')!=d['manifest_sha256'] or manifest['block']['generations'][0]['task_id'].split('-')[0]!='F3':return None
    raw=db.execute('SELECT body FROM scopes WHERE id=?',(scope_hash,)).fetchone()
    if not raw:return None
    scope=json.loads(raw[0]);identity=scope['identity']
    if identity['source']!=d['execution_identity']['source'] or identity['dependencies']!=d['execution_identity']['dependencies'] or manifest.get('resume_decision_sha256')!=digest(d):raise PermissionError('RESUME_F3_PROFILE_IDENTITY')
    return set(d['isolated_holds'])

def check_allowed(db,row,scope_hash):
    a=active(db)
    if not a or row['manifest']!=a['decision']['manifest_sha256']:return
    if scope_hash!=a['scope_sha256'] or row['root_request_id'] not in a['decision']['allowed_request_ids']:raise PermissionError('RESUME_UNATTEMPTED_ALLOWLIST_ONLY')

def excluded_pending(db,row):
    a=active(db)
    return bool(a and row['manifest']==a['decision']['manifest_sha256'] and row['logical_slot'] in a['decision']['excluded_logical_slots'] and row['state']=='PENDING')
