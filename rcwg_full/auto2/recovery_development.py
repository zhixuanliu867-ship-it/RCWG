"""Append complete independent development blocks to the existing recovery epoch.

Dynamic P1 physical bodies are bound only to a completed, parsed logical response.
The original epoch, unknown reservation and task-wide fuse are never reset.
"""
import json
import uuid
from .dispatch import DispatchGate
from .budget_extension import effective_recovery_cap
from .recovery import active_epoch
from rcwg_full.evidence import canonical,digest
from rcwg_full.services.requests import assemble_recovery2,parse_final
from rcwg_api.common import ApiError


def rows(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_development_requests'").fetchone():return []
    return [dict(zip(('sequence','id','scope','kind','amount','body_hash','recipe','state'),r)) for r in
            db.execute('SELECT * FROM recovery_development_requests ORDER BY sequence')]


def next_request(db):
    used={r[0] for r in db.execute('SELECT id FROM reservations')}
    return next((r for r in rows(db) if r['id'] not in used and r['state']!='SKIPPED'),None)


def install_block(state,scope,block,recipes,*,original_blocks,original_manifest_sha256):
    """Recipes contain only public tasks; block order comes from the frozen plan."""
    state.validate_scope(scope,scope['identity'])
    if scope['stage']!='B_DEVELOPMENT' or block['max_E_requests']!=0:
        raise PermissionError('RECOVERY_DEVELOPMENT_SCOPE')
    old=next((b for b in original_blocks if b['id']==block['original_block_id']),None)
    if old is None or len(recipes)!=12 or len(old['generations'])!=12:
        raise PermissionError('RECOVERY_COMPLETE_COMPARISON_REQUIRED')
    if {(g['generator'],g['protocol']) for g in old['generations']}!={(g,p) for g in ['G0','G1','G2','G3','G4','G5'] for p in ['P0','P1']}:
        raise PermissionError('RECOVERY_COMPLETE_COMPARISON_REQUIRED')
    planned=[]
    for before,job,recipe in zip(old['generations'],block['generations'],recipes):
        expected='recovery-r1-request2-'+before['id']
        if (job['id']!=expected or recipe['attempt_id']!=expected or recipe['binding']['slot']!=before['generator']
            or any(job[k]!=before[k] for k in ['task_id','generator','protocol','trial_label','task_file_sha256'])
            or recipe['protocol']!=before['protocol'] or recipe['trial_label']!=before['trial_label']
            or recipe['public_task_file_sha256']!=before['task_file_sha256']):
            raise PermissionError('RECOVERY_DEVELOPMENT_LINEAGE')
        for stage in (['physical'] if before['protocol']=='P0' else ['logical','physical']):
            rid=str(uuid.uuid5(uuid.NAMESPACE_URL,digest(state.authority)+':'+expected+':'+stage))
            item={**recipe,'stage':stage,'request_id':rid}
            for kind,ident in [('COUNT',str(uuid.uuid5(uuid.UUID(rid),'COUNT'))),('G',rid)]:
                amount=recipe['rates'][kind]
                if type(amount) is not int or amount<0:raise PermissionError('RECOVERY_RATE')
                planned.append((ident,digest(scope),kind,amount,canonical(item).decode()))
    if len(planned)!=36 or sum(p[3] for p in planned)!=block['reserved_upper_microusd']:
        raise PermissionError('RECOVERY_COMPLETE_BLOCK_BOUND')
    gate=DispatchGate(state)
    with gate.locked():
        with state.db() as db:
            db.execute('BEGIN IMMEDIATE');epoch=active_epoch(db)
            if epoch is None or db.execute('SELECT status FROM dispatch_control').fetchone()[0]!='OPEN':
                raise PermissionError('RECOVERY_DEVELOPMENT_FUSED_OR_NO_EPOCH')
            reserved={r[0]:r[1] for r in db.execute('SELECT id,status FROM reservations')}
            if any(reserved.get(p['request_id']) not in {'COMPLETED','MODEL_FAILURE'} for p in epoch['planned_requests']):
                raise PermissionError('RECOVERY_FIXED_E_UNRESOLVED')
            if any(s in {'SENT_UNCONFIRMED','UNKNOWN','RESERVED_BEFORE_IO'} and rid not in epoch['isolated_request_ids'] for rid,s in reserved.items()):
                raise PermissionError('RECOVERY_NEW_UNRESOLVED')
            if next_request(db) is not None:raise PermissionError('RECOVERY_PREVIOUS_BLOCK_INCOMPLETE')
            db.execute('CREATE TABLE IF NOT EXISTS recovery_development_blocks(sequence INTEGER PRIMARY KEY, id TEXT UNIQUE, body TEXT NOT NULL)')
            previous=db.execute('SELECT body FROM recovery_development_blocks ORDER BY sequence').fetchall()
            if len(previous)>=len(original_blocks) or original_blocks[len(previous)]['id']!=old['id']:
                raise PermissionError('RECOVERY_DEVELOPMENT_BLOCK_ORDER')
            if any(json.loads(p[0])['original_manifest_sha256']!=original_manifest_sha256 for p in previous):
                raise PermissionError('RECOVERY_DEVELOPMENT_MANIFEST_CHANGED')
            used=db.execute('SELECT SUM(amount) FROM reservations').fetchone()[0]
            cost=sum(p[3] for p in planned)
            if used+cost-epoch['baseline_reserved_microusd']>effective_recovery_cap(db,epoch):
                raise PermissionError('RECOVERY_COMPLETE_BLOCK_UNAFFORDABLE')
            cleanup=int(state.policy['budget']['cleanup_and_billing_lag_reserve']*1e6)
            if used+cost>state.authority['ceiling_microusd']-cleanup or cost>scope['ceiling_microusd']:
                raise PermissionError('RECOVERY_CUMULATIVE_BUDGET')
            phase=db.execute("SELECT SUM(r.amount) FROM reservations r JOIN scopes s ON s.id=r.scope WHERE json_extract(s.body,'$.stage') IN ('B_DEVELOPMENT','B_REFERENCE','B_FORMAL')").fetchone()[0] or 0
            if phase+cost>int(state.policy['budget']['remaining_live_and_reference_allocation']*1e6):
                raise PermissionError('RECOVERY_PHASE_BUDGET')
            if scope['limits'].get('G',0)<18 or scope['limits'].get('COUNT',0)<18:raise PermissionError('RECOVERY_BLOCK_LIMIT')
            db.execute('CREATE TABLE IF NOT EXISTS recovery_development_requests(sequence INTEGER PRIMARY KEY,id TEXT UNIQUE,scope TEXT,kind TEXT,amount INTEGER,body_hash TEXT,recipe TEXT,state TEXT)')
            if any(p[0] in reserved for p in planned):raise PermissionError('RECOVERY_NO_REPLAY')
            db.execute('INSERT INTO recovery_development_blocks(id,body) VALUES(?,?)',(block['id'],canonical({'block':block,'scope_sha256':digest(scope),'original_manifest_sha256':original_manifest_sha256,'original_epoch_sha256':digest(epoch)}).decode()))
            for rid,scope_hash,kind,amount,recipe in planned:
                db.execute('INSERT INTO recovery_development_requests(id,scope,kind,amount,recipe,state) VALUES(?,?,?,?,?,?)',(rid,scope_hash,kind,amount,recipe,'PENDING'))


def bind_request(state,request,kind,index):
    """Validate actual bytes against the precommitted public recipe before dispatch."""
    with state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=next((r for r in rows(db) if r['id']==request['request_id']),None)
        if row is None:raise PermissionError('RECOVERY_REQUEST_NOT_PREREGISTERED')
        if row['kind']!=kind or row['state']=='SKIPPED':raise PermissionError('RECOVERY_REQUEST_KIND_OR_SKIPPED')
        recipe=json.loads(row['recipe']);logical=None
        if recipe['stage']=='physical' and recipe['protocol']=='P1':
            rid=str(uuid.uuid5(uuid.NAMESPACE_URL,digest(state.authority)+':'+recipe['attempt_id']+':logical'))
            with index.lock:prior=index.db.execute('SELECT status,result FROM requests WHERE id=?',(rid,)).fetchone()
            if not prior or prior[0]!='COMPLETED':raise PermissionError('RECOVERY_LOGICAL_DEPENDENCY_UNRESOLVED')
            logical=parse_final(json.loads(prior[1])['response']['text'].encode(),'logical')['value']
        expected=assemble_recovery2(recipe['task'],recipe['binding'],protocol=recipe['protocol'],stage=recipe['stage'],
            attempt_id=recipe['attempt_id'],request_id=recipe['request_id'],trial_label=recipe['trial_label'],logical=logical)
        body=expected['body'] if kind=='G' else {k:v for k,v in expected['body'].items() if k in {'contents','systemInstruction'}}
        if request['body']!=body or request['body_hash']!=digest(body) or request['binding_hash']!=digest(recipe['binding']):
            raise PermissionError('RECOVERY_BODY_RECIPE_MISMATCH')
        if row['body_hash'] not in {None,digest(body)}:raise PermissionError('RECOVERY_BOUND_BODY_CHANGED')
        db.execute("UPDATE recovery_development_requests SET body_hash=?,state='BOUND' WHERE id=?",(digest(body),row['id']))


def skip_failed_physical(state,attempt_id,index):
    """Skip only a P1 physical dependency whose completed logical text cannot parse."""
    rid=str(uuid.uuid5(uuid.NAMESPACE_URL,digest(state.authority)+':'+attempt_id+':logical'))
    with index.lock:prior=index.db.execute('SELECT status,result FROM requests WHERE id=?',(rid,)).fetchone()
    if not prior or prior[0] not in {'COMPLETED','MODEL_FAILURE'}:raise PermissionError('RECOVERY_SKIP_UNRESOLVED')
    if prior[0]=='COMPLETED':
        try:parse_final(json.loads(prior[1])['response']['text'].encode(),'logical')
        except (ValueError,ApiError):pass
        else:raise PermissionError('RECOVERY_SKIP_VALID_LOGICAL')
    with state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for r in rows(db):
            recipe=json.loads(r['recipe'])
            if recipe['attempt_id']==attempt_id and recipe['stage']=='physical' and recipe['protocol']=='P1':
                if db.execute('SELECT 1 FROM reservations WHERE id=?',(r['id'],)).fetchone():raise PermissionError('RECOVERY_SKIP_ALREADY_SENT')
                db.execute("UPDATE recovery_development_requests SET state='SKIPPED' WHERE id=?",(r['id'],))


def check_development(db,rid,kind,body_hash,scope_hash,amount=None):
    row=next((r for r in rows(db) if r['id']==rid),None)
    if row is None:return False
    if row['kind']!=kind or row['scope']!=scope_hash or row['state']!='BOUND' or (body_hash is not None and row['body_hash']!=body_hash) or (amount is not None and row['amount']!=amount):
        raise PermissionError('RECOVERY_DEVELOPMENT_BINDING')
    pending=next_request(db)
    if pending is None or pending['id']!=rid:raise PermissionError('RECOVERY_FROZEN_ORDER')
    return True
