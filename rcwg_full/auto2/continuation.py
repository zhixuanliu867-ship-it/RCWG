"""Append one preregistered F2/F3/F4 REQUEST_4 packet; never reset prior work.

This is a prospective development registration API. The trusted controller must
read the original frozen block and revalidate actual source/host/data identities
before calling. Registration itself neither starts work nor changes a fuse.
"""
import json
import uuid
from rcwg_full.evidence import canonical, digest
from .dispatch import DispatchGate
from . import next_live as nl
from .recovery import active_epoch

PROFILE = 'NEXT_LIVE_002_PACKET_1'


def append_packet(state, scope, manifest, *, original_block):
    state.validate_scope(scope, scope['identity'])
    if (manifest.get('revision') != PROFILE or manifest.get('root_sha256') != digest(state.authority)
        or manifest.get('measurement_profile') != 'SERVICE_ONLY'
        or manifest.get('request_profile') != 'FULL001_REQUEST_4'
        or manifest.get('original_block_sha256') != digest(original_block)
        or scope['stage'] != 'B_DEVELOPMENT' or scope['identity']['manifest'] != digest(manifest)):
        raise PermissionError('CONTINUATION_PROFILE_OR_IDENTITY')
    if (manifest.get('capacity_retry_profile') != 'CAPACITY_RETRY_1' or manifest.get('retry_pool') != 2
        or scope.get('capacity_retry_profile') != 'CAPACITY_RETRY_1'
        or scope.get('retries') != 2 or scope.get('tranche_extra_attempt_pool') != 2):
        raise PermissionError('CONTINUATION_RETRY_POLICY')
    jobs = manifest['block']['generations']; old_jobs = original_block['generations']
    if len(jobs) != 12 or len(old_jobs) != 12:
        raise PermissionError('CONTINUATION_COMPLETE_BLOCK')
    pairs = {(f'G{i}', p) for i in range(6) for p in ('P0','P1')}
    if {(g['generator'],g['protocol']) for g in jobs} != pairs:
        raise PermissionError('CONTINUATION_COMPLETE_BLOCK')
    if len({g['task_id'] for g in jobs}) != 1 or jobs[0]['task_id'].split('-')[0] not in {'F2','F3','F4'}:
        raise PermissionError('CONTINUATION_NONSEMANTIC_BLOCK')
    for job, old in zip(jobs, old_jobs):
        if (job['id'] != 'next-live-002-request4-'+old['id'] or
            any(job[k] != old[k] for k in ('task_id','generator','protocol','trial_label','task_file_sha256'))):
            raise PermissionError('CONTINUATION_LINEAGE_OR_ORDER')
    requests = manifest['requests']; expected = []
    if len(requests) != 36 or len({r['id'] for r in requests}) != 36:
        raise PermissionError('CONTINUATION_REQUEST_COUNT')
    for job in jobs:
        logical_id = None
        for stage in (['physical'] if job['protocol']=='P0' else ['logical','physical']):
            selected = [r for r in requests if r['kind']=='G' and r['logical_slot']==job['id'] and r['stage']==stage]
            if len(selected) != 1:
                raise PermissionError('CONTINUATION_STAGE_SET')
            g = selected[0]; q = g['recipe']; rid = g['id']
            if str(uuid.UUID(rid)) != rid:
                raise PermissionError('CONTINUATION_REQUEST_UUID')
            if stage == 'logical': logical_id = rid
            if (q.get('category') != 'G' or q.get('request_profile') != 'FULL001_REQUEST_4'
                or q['request_id'] != rid or q['attempt_id'] != job['id']
                or q['protocol'] != job['protocol'] or q['stage'] != stage
                or q['trial_label'] != job['trial_label']
                or q['binding']['slot'] != job['generator'] or g['model'] != job['generator']
                or q['task']['task_id'] != job['task_id']
                or q['public_task_file_sha256'] != job['task_file_sha256']):
                raise PermissionError('CONTINUATION_RECIPE_LINEAGE')
            if job['protocol']=='P1' and stage=='physical' and q.get('logical_request_id') != logical_id:
                raise PermissionError('CONTINUATION_P1_DEPENDENCY')
            cid = str(uuid.uuid5(uuid.UUID(rid),'COUNT'))
            selected_count = [r for r in requests if r['id']==cid and r['kind']=='COUNT']
            if len(selected_count) != 1:
                raise PermissionError('CONTINUATION_COUNT_BINDING')
            c = selected_count[0]
            if (c['recipe'] != q or c['logical_slot'] != job['id'] or c['stage'] != stage
                or c['model'] != job['generator']):
                raise PermissionError('CONTINUATION_COUNT_BINDING')
            expected.extend([c,g])
    if expected != requests or any(type(r['amount']) is not int or r['amount'] < 1 for r in requests):
        raise PermissionError('CONTINUATION_ORDER_OR_RATE')
    cost = sum(r['amount'] for r in requests) + 2*max(r['amount'] for r in requests)
    if (cost != manifest['complete_packet_upper_microusd'] or cost > scope['ceiling_microusd']
        or scope['limits'].get('G',0) < 20 or scope['limits'].get('COUNT',0) < 20
        or scope['limits'].get('E',0) != 0):
        raise PermissionError('CONTINUATION_PACKET_BOUND')
    mid = digest(manifest)
    with DispatchGate(state).locked(), state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not nl._exists(db):
            raise PermissionError('CONTINUATION_PREVIOUS_PACKET_REQUIRED')
        existing = db.execute('SELECT body,scope FROM next_live_manifests WHERE id=?',(mid,)).fetchone()
        if existing:
            if json.loads(existing[0]) != manifest or existing[1] != digest(scope):
                raise PermissionError('CONTINUATION_ALREADY_BOUND')
            return mid
        parent = db.execute('SELECT id,body FROM next_live_manifests ORDER BY rowid DESC LIMIT 1').fetchone()
        if not parent or parent[0] != manifest.get('previous_packet_sha256'):
            raise PermissionError('CONTINUATION_PARENT_CHANGED')
        parent_jobs = json.loads(parent[1]).get('block', {}).get('generations', [])
        prior_family = parent_jobs[0]['task_id'].split('-')[0] if parent_jobs else None
        expected_family = {'F1': 'F2', 'F2': 'F3', 'F3': 'F4'}.get(prior_family)
        if jobs[0]['task_id'].split('-')[0] != expected_family:
            raise PermissionError('CONTINUATION_FROZEN_FAMILY_ORDER')
        epoch = active_epoch(db)
        if epoch is None or db.execute('SELECT status FROM dispatch_control WHERE id=1').fetchone()[0] != 'OPEN':
            raise PermissionError('CONTINUATION_FUSED_OR_NO_EPOCH')
        from .independent_resume import excluded_pending,active as resume_active,PROFILE as RESUME_PROFILE
        prior_rows = [json.loads(row[0]) for row in db.execute('SELECT body FROM next_live_requests')]
        if any(r['state'] not in {'DONE','SKIPPED','DEFERRED','RETRIED'} and not excluded_pending(db,r) for r in prior_rows):
            raise PermissionError('CONTINUATION_PREVIOUS_PACKET_INCOMPLETE')
        unresolved = db.execute("SELECT id,status FROM reservations WHERE kind IN ('G','E','COUNT') AND status IN ('UNKNOWN','SENT_UNCONFIRMED','RESERVED_BEFORE_IO')").fetchall()
        isolated=set(epoch['isolated_request_ids']);resume=resume_active(db)
        if resume and parent[0]==resume['decision']['manifest_sha256'] and expected_family=='F3':
            d=resume['decision']
            if (manifest.get('resume_decision_sha256')!=digest(d) or scope['identity']['source']!=d['execution_identity']['source']
                or scope['identity']['dependencies']!=d['execution_identity']['dependencies']):raise PermissionError('CONTINUATION_RESUME_PROFILE')
            isolated=set(d['isolated_holds'])
        if ({rid for rid,status in unresolved} != isolated
            or any(status=='RESERVED_BEFORE_IO' for _,status in unresolved)):
            raise PermissionError('CONTINUATION_NEW_UNRESOLVED')
        if any(db.execute('SELECT 1 FROM reservations WHERE id=?',(r['id'],)).fetchone() or
               db.execute('SELECT 1 FROM next_live_requests WHERE id=?',(r['id'],)).fetchone() for r in requests):
            raise PermissionError('CONTINUATION_NO_REPLAY')
        # A block may be appended only once. This prevents new UUIDs or parent
        # names from recreating a completed comparison under this profile.
        for body, in db.execute('SELECT body FROM next_live_manifests'):
            before = json.loads(body)
            if before.get('original_block_sha256') == digest(original_block):
                raise PermissionError('CONTINUATION_BLOCK_ALREADY_REGISTERED')
        nl._limits(state, db, cost)
        db.execute('INSERT INTO next_live_manifests VALUES(?,?,?)',(mid,canonical(manifest).decode(),digest(scope)))
        for i,r in enumerate(requests):
            row={**r,'manifest':mid,'ordinal':i,'attempt':0,'parent_request_id':None,
                 'root_request_id':r['id'],'state':'PENDING','bound_hash':None,'not_before':0}
            db.execute('INSERT INTO next_live_requests VALUES(?,?,?,?,?)',(r['id'],mid,i,0,canonical(row).decode()))
        nl._event(db,'CONTINUATION_PACKET_INSTALLED',{'manifest':mid,'previous':parent[0],
            'old_results_changed':False,'request_profile':'FULL001_REQUEST_4','formal_ready':False})
    return mid
