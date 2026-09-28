"""Prospective finite attempts within the original recovery epoch and ledger.

The previous zero-retry trial stays terminal. Only complete archived capacity
rejections permit new physical attempts; uncertainty still fuses the task.
"""
from copy import deepcopy
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json,time,uuid
from rcwg_full.evidence import canonical,digest,read,sha
from rcwg_api.common import strict,ApiError
from rcwg_full.services.requests import parse_final
from rcwg_full.services.request3 import assemble_request3
from rcwg_full.services.quotes import assemble_quote
from .dispatch import DispatchGate
from .recovery import active_epoch

PROFILE='NEXT_LIVE_001_1'

def _exists(db):return db.execute("SELECT 1 FROM sqlite_master WHERE name='next_live_manifests'").fetchone() is not None
def _row(db,rid):
    if not _exists(db):return None
    r=db.execute('SELECT body FROM next_live_requests WHERE id=?',(rid,)).fetchone()
    return json.loads(r[0]) if r else None
def _put(db,row):db.execute('UPDATE next_live_requests SET body=? WHERE id=?',(canonical(row).decode(),row['id']))
def _event(db,event,value):db.execute('INSERT INTO next_live_events(at_ns,event,body) VALUES(?,?,?)',(time.time_ns(),event,canonical(value).decode()))
def _manifest(db,mid):
    r=db.execute('SELECT body,scope FROM next_live_manifests WHERE id=?',(mid,)).fetchone()
    return json.loads(r[0]),r[1]
def _rows(db,mid):return [json.loads(x[0]) for x in db.execute('SELECT body FROM next_live_requests WHERE manifest=? ORDER BY ordinal,attempt',(mid,))]
def archive_root(state):return state.root.parent/'private/requests'

def capacity_evidence(result,root):
    """Fail closed on incomplete/body-only/unbound/malformed evidence."""
    try:
        if (result.get('status')!='INFRA_FAILURE' or result.get('http_status')!=429 or
            result.get('sent') is not True or result.get('response_complete') is not True or
            type(result.get('response_headers')) is not dict):return False
        rid=result['request_id'];directory=root/rid
        if str(uuid.UUID(rid))!=rid:return False
        request=json.loads(read(directory/'request.json'))
        if request['request_id']!=rid or request['binding_hash']!=result['binding_hash']:return False
        if json.loads(read(directory/'infra_failure.json'))!=result:return False
        raw=read(directory/'response.raw')
        if sha(raw)!=result['response_raw_hash']:return False
        envelope=strict(raw)
        if type(envelope) is not dict or set(envelope)!={'error'}:return False
        error=envelope['error']
        if type(error) is not dict or error.get('code')!=429 or error.get('status')!='RESOURCE_EXHAUSTED':return False
        def suspect(value):
            if type(value) is dict:
                return any(k.lower() in {'candidates','candidate','usagemetadata','usage','content','parts','promptfeedback'} or suspect(v) for k,v in value.items())
            return type(value) is list and any(suspect(v) for v in value)
        return not suspect(error)
    except (OSError,ValueError,KeyError,TypeError,ApiError):return False

def delay_seconds(headers,retries_used,*,now=None):
    if retries_used not in (0,1):raise ValueError('CAPACITY_RETRY_LIMIT')
    delay=(5.0,15.0)[retries_used]
    values=[v for k,v in headers.items() if k.lower()=='retry-after']
    if len(values)>1:raise ValueError('INVALID_RETRY_AFTER')
    if values:
        value=values[0]
        if type(value) is not str:raise ValueError('INVALID_RETRY_AFTER')
        if value.isascii() and value.isdecimal():seconds=int(value)
        else:
            try:
                target=parsedate_to_datetime(value)
                if target.tzinfo is None:raise ValueError()
                seconds=max(0,(target-(now or datetime.now(timezone.utc))).total_seconds())
            except (ValueError,TypeError,OverflowError):raise ValueError('INVALID_RETRY_AFTER') from None
        delay=max(delay,seconds)
    return delay

def _limits(state,db,cost):
    epoch=active_epoch(db)
    if epoch is None:raise PermissionError('NEXT_LIVE_REQUIRES_EXISTING_EPOCH')
    used=db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations').fetchone()[0]
    if used+cost-epoch['baseline_reserved_microusd']>epoch['maximum_additional_microusd']:raise PermissionError('NEXT_LIVE_RECOVERY_SUBCAP')
    if used+cost>state.authority['ceiling_microusd']-int(state.policy['budget']['cleanup_and_billing_lag_reserve']*1e6):raise PermissionError('NEXT_LIVE_ROOT_BUDGET')
    phase=db.execute("SELECT COALESCE(SUM(r.amount),0) FROM reservations r JOIN scopes s ON s.id=r.scope WHERE json_extract(s.body,'$.stage') IN ('B_DEVELOPMENT','B_REFERENCE','B_FORMAL')").fetchone()[0]
    if phase+cost>int(state.policy['budget']['remaining_live_and_reference_allocation']*1e6):raise PermissionError('NEXT_LIVE_PHASE_BUDGET')

def install(state,scope,manifest,*,old_capacity_result,original_block):
    state.validate_scope(scope,scope['identity'])
    if manifest.get('revision')!=PROFILE or manifest.get('root_sha256')!=digest(state.authority) or scope['stage']!='B_DEVELOPMENT':raise PermissionError('NEXT_LIVE_ROOT_PROFILE')
    if manifest.get('capacity_retry_profile')!='CAPACITY_RETRY_1' or manifest.get('retry_pool')!=2:raise PermissionError('NEXT_LIVE_RETRY_POLICY')
    if scope.get('capacity_retry_profile')!='CAPACITY_RETRY_1' or scope.get('retries')!=2 or scope.get('tranche_extra_attempt_pool')!=2:raise PermissionError('NEXT_LIVE_SCOPE_RETRY_POLICY')
    if manifest.get('user_authority_sha256') is None or scope['identity']['manifest']!=digest(manifest):raise PermissionError('NEXT_LIVE_MANIFEST_BINDING')
    jobs=manifest['block']['generations'];old=original_block['generations']
    if len(jobs)!=12 or len(old)!=12 or {(g['generator'],g['protocol']) for g in jobs}!={(f'G{i}',p) for i in range(6) for p in ('P0','P1')}:raise PermissionError('NEXT_LIVE_COMPLETE_COMPARISON')
    for a,b in zip(jobs,old):
        if any(a[k]!=b[k] for k in ('task_id','generator','protocol','trial_label','task_file_sha256')) or a['id']!='next-live-001-request3-'+b['id']:raise PermissionError('NEXT_LIVE_LINEAGE')
    requests=manifest['requests']
    if len({r['id'] for r in requests})!=len(requests):raise PermissionError('NEXT_LIVE_DUPLICATE_ID')
    expected_g={(g['id'],s) for g in jobs for s in (['physical'] if g['protocol']=='P0' else ['logical','physical'])}
    if {(r['logical_slot'],r['stage']) for r in requests if r['kind']=='G'}!=expected_g:raise PermissionError('NEXT_LIVE_COMPLETE_STAGE_SET')
    if len([r for r in requests if r['kind']=='G'])!=18:raise PermissionError('NEXT_LIVE_STAGE_COUNT')
    for r in requests:
        if r['kind'] not in {'G','E','COUNT'} or type(r['amount']) is not int or r['amount']<1:raise PermissionError('NEXT_LIVE_REQUEST_BOUND')
        if str(uuid.UUID(r['id']))!=r['id']:raise PermissionError('NEXT_LIVE_UUID')
        q=r['recipe']
        if r['model']!=q['binding']['slot'] or r['stage']!=q['stage']:raise PermissionError('NEXT_LIVE_RECIPE_LINEAGE')
        if r['kind']=='G':
            job=next(g for g in jobs if g['id']==r['logical_slot'])
            if (q['attempt_id']!=job['id'] or q['binding']['slot']!=job['generator'] or q['protocol']!=job['protocol'] or
                q['trial_label']!=job['trial_label'] or q['public_task_file_sha256']!=job['task_file_sha256'] or
                q['task']['task_id']!=job['task_id']):raise PermissionError('NEXT_LIVE_RECIPE_LINEAGE')
        if r['kind']!='COUNT':
            cid=str(uuid.uuid5(uuid.UUID(r['id']),'COUNT'))
            if sum(c['id']==cid and c['kind']=='COUNT' and c['recipe']==r['recipe'] for c in requests)!=1:raise PermissionError('NEXT_LIVE_COUNT_BINDING')
    cost=sum(r['amount'] for r in requests)+2*max(r['amount'] for r in requests)
    if cost!=manifest['complete_packet_upper_microusd'] or cost>scope['ceiling_microusd']:raise PermissionError('NEXT_LIVE_COMPLETE_PACKET_COST')
    gate=DispatchGate(state)
    with gate.locked(),state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if _exists(db):raise PermissionError('NEXT_LIVE_ALREADY_INSTALLED_NO_RESET')
        epoch=active_epoch(db)
        if epoch is None:raise PermissionError('NEXT_LIVE_REQUIRES_EXISTING_EPOCH')
        unresolved=db.execute("SELECT id FROM reservations WHERE kind IN ('G','E','COUNT') AND status IN ('UNKNOWN','SENT_UNCONFIRMED','RESERVED_BEFORE_IO')").fetchall()
        if {r[0] for r in unresolved}!=set(epoch['isolated_request_ids']):raise PermissionError('NEXT_LIVE_NEW_UNRESOLVED')
        current,detail=db.execute('SELECT status,detail FROM dispatch_control').fetchone();detail=json.loads(detail)
        if current!='FUSED' or detail.get('request_id')!=old_capacity_result['request_id'] or detail.get('result_sha256')!=digest(old_capacity_result):raise PermissionError('NEXT_LIVE_ONLY_OLD_CAPACITY_FUSE')
        if not capacity_evidence(old_capacity_result,archive_root(state)):raise PermissionError('NEXT_LIVE_OLD_CAPACITY_EVIDENCE')
        if any(db.execute('SELECT 1 FROM reservations WHERE id=?',(r['id'],)).fetchone() for r in requests):raise PermissionError('NEXT_LIVE_NO_REPLAY')
        _limits(state,db,cost)
        db.execute('CREATE TABLE next_live_manifests(id TEXT PRIMARY KEY,body TEXT,scope TEXT)')
        db.execute('CREATE TABLE next_live_requests(id TEXT PRIMARY KEY,manifest TEXT,ordinal INTEGER,attempt INTEGER,body TEXT)')
        db.execute('CREATE TABLE next_live_events(id INTEGER PRIMARY KEY,at_ns INTEGER,event TEXT,body TEXT)')
        db.execute('INSERT INTO next_live_manifests VALUES(?,?,?)',(digest(manifest),canonical(manifest).decode(),digest(scope)))
        for i,r in enumerate(requests):
            row={**r,'manifest':digest(manifest),'ordinal':i,'attempt':0,'parent_request_id':None,'root_request_id':r['id'],'state':'PENDING','bound_hash':None,'not_before':0}
            db.execute('INSERT INTO next_live_requests VALUES(?,?,?,?,?)',(r['id'],digest(manifest),i,0,canonical(row).decode()))
        _event(db,'INSTALL',{'old_capacity_request_id':old_capacity_result['request_id'],'old_result_unchanged':True,'scope':digest(scope)})
        gate._record(db,'OPEN',{'reason':'PROSPECTIVE_CAPACITY_RETRY_1_NEW_COMPLETE_PROFILE','manifest':digest(manifest),'provider_active_count':None,'epoch':1})

def _lookup_result(index,rid):
    with index.lock:r=index.db.execute('SELECT status,result FROM requests WHERE id=?',(rid,)).fetchone()
    return json.loads(r[1]) if r and r[1] else None

def _terminal_result(db,index,rid):
    rows=[r for r in _rows(db,_row(db,rid)['manifest']) if r['root_request_id']==rid]
    latest=max(rows,key=lambda r:r['attempt'])
    return _lookup_result(index,latest['id'])

def bind(state,request,kind,index):
    with state.db() as db:
        db.execute('BEGIN IMMEDIATE');row=_row(db,request['request_id'])
        if row is None or row['kind']!=kind or row['state'] in {'SKIPPED','DEFERRED'}:raise PermissionError('NEXT_LIVE_NOT_PREREGISTERED')
        q=row['recipe'];logical=None
        if q['category']=='G':
            if q['protocol']=='P1' and q['stage']=='physical':
                prior=_terminal_result(db,index,q['logical_request_id'])
                if not prior or prior['status']!='COMPLETED':raise PermissionError('NEXT_LIVE_LOGICAL_DEPENDENCY')
                logical=parse_final(prior['response']['text'].encode(),'logical')['value']
            expected=assemble_request3(q['task'],q['binding'],protocol=q['protocol'],stage=q['stage'],attempt_id=q['attempt_id'],
              request_id=q['request_id'],trial_label=q['trial_label'],logical=logical)
        else:expected=assemble_quote(q['semantic_request'],q['binding'],q['template'],q['request_id'],profile=q['profile'])
        body=expected['body'] if kind!='COUNT' else {k:v for k,v in expected['body'].items() if k in {'contents','systemInstruction'}}
        if request['body']!=body or request['body_hash']!=digest(body) or request['binding_hash']!=digest(q['binding']):raise PermissionError('NEXT_LIVE_BODY_RECIPE')
        if row['bound_hash'] not in {None,digest(body)}:raise PermissionError('NEXT_LIVE_BODY_CHANGED')
        if row['parent_request_id']:
            parent=_row(db,row['parent_request_id'])
            if parent['bound_hash']!=digest(body):raise PermissionError('NEXT_LIVE_RETRY_BODY_CHANGED')
        row.update(bound_hash=digest(body),state='BOUND' if row['state']=='PENDING' else row['state']);_put(db,row)

def check(db,rid,kind,body_hash,scope_hash,amount=None):
    row=_row(db,rid)
    if row is None:return False
    manifest,scope=_manifest(db,row['manifest'])
    if row['kind']!=kind or scope!=scope_hash or row['state']!='BOUND' or (body_hash is not None and body_hash!=row['bound_hash']) or (amount is not None and amount!=row['amount']):raise PermissionError('NEXT_LIVE_BINDING')
    if time.time()<row['not_before']:raise PermissionError('NEXT_LIVE_BACKOFF_NOT_ELAPSED')
    # A capacity parent stays pending until retried or explicitly deferred.
    unresolved=[r for r in _rows(db,row['manifest']) if r['state'] not in {'DONE','SKIPPED','DEFERRED','RETRIED'}]
    if not unresolved or unresolved[0]['id']!=rid:raise PermissionError('NEXT_LIVE_FROZEN_ORDER')
    return True

def finish(state,db,rid,result):
    row=_row(db,rid)
    if row is None:return False
    capacity=capacity_evidence(result,archive_root(state))
    row.update(state='CAPACITY' if capacity else 'DONE',result_sha256=digest(result));_put(db,row)
    _event(db,'PHYSICAL_RESULT',{'request_id':rid,'result_sha256':digest(result),'capacity_confirmed':capacity})
    return capacity

def retry_or_defer(state,index,rid):
    gate=DispatchGate(state)
    with gate.locked(),state.db() as db:
        db.execute('BEGIN IMMEDIATE');row=_row(db,rid)
        if not row:raise PermissionError('NEXT_LIVE_NOT_PREREGISTERED')
        if row['state']=='RETRIED':
            child=next(r for r in _rows(db,row['manifest']) if r['parent_request_id']==rid)
            return child
        if row['state']=='DEFERRED':return None
        if row['state']!='CAPACITY' or db.execute('SELECT status FROM dispatch_control').fetchone()[0]!='OPEN':raise PermissionError('NEXT_LIVE_NOT_CAPACITY_OR_FUSED')
        result=_lookup_result(index,rid)
        if not result or not capacity_evidence(result,archive_root(state)) or digest(result)!=row['result_sha256']:raise PermissionError('NEXT_LIVE_CAPACITY_EVIDENCE_CHANGED')
        manifest,_=_manifest(db,row['manifest']);rows=_rows(db,row['manifest'])
        retries=sum(r['attempt']>0 for r in rows);delay=None;reason=None
        if row['attempt']>=2 or retries>=manifest['retry_pool']:reason='CAPACITY_RETRY_LIMIT'
        else:
            try:delay=delay_seconds(result['response_headers'],row['attempt'])
            except ValueError:
                gate._record(db,'FUSED',{'reason':'INVALID_RETRY_AFTER','request_id':rid,'provider_active_count':None})
                _event(db,'INVALID_RETRY_AFTER',{'request_id':rid});return None
            if delay>300:reason='CAPACITY_WAIT_EXCEEDS_WINDOW'
        if reason:
            for r in rows:
                if r['model']==row['model'] and r['state'] in {'PENDING','BOUND','CAPACITY'}:
                    r.update(state='DEFERRED',defer_reason=reason);_put(db,r)
            _event(db,'MODEL_DEFERRED',{'model':row['model'],'reason':reason,'request_id':rid});return None
        _limits(state,db,row['amount'])
        child={**row,'id':str(uuid.uuid5(uuid.UUID(rid),'CAPACITY_RETRY_1:'+str(row['attempt']+1))),
           'parent_request_id':rid,'attempt':row['attempt']+1,'state':'PENDING','not_before':time.time()+delay}
        child.pop('result_sha256',None)
        db.execute('INSERT INTO next_live_requests VALUES(?,?,?,?,?)',(child['id'],child['manifest'],child['ordinal'],child['attempt'],canonical(child).decode()))
        row['state']='RETRIED';_put(db,row);_event(db,'RETRY_REGISTERED',{'parent':rid,'child':child['id'],'delay_s':delay,'amount':child['amount']})
        return child

def skip_failed_logical(state,index,attempt_id):
    with state.db() as db:
        db.execute('BEGIN IMMEDIATE')
        candidates=[json.loads(r[0]) for r in db.execute('SELECT body FROM next_live_requests')]
        rows=[r for r in candidates if r['logical_slot']==attempt_id and r['stage']=='physical' and r['state']=='PENDING']
        if not rows:return
        prior=_terminal_result(db,index,rows[0]['recipe']['logical_request_id'])
        if not prior or prior['status'] not in {'COMPLETED','MODEL_FAILURE'}:raise PermissionError('NEXT_LIVE_SKIP_UNRESOLVED')
        if prior['status']=='COMPLETED':
            try:parse_final(prior['response']['text'].encode(),'logical')
            except (ValueError,ApiError):pass
            else:raise PermissionError('NEXT_LIVE_SKIP_VALID_LOGICAL')
        for row in rows:row.update(state='SKIPPED',skip_reason='LOGICAL_MODEL_FAILURE');_put(db,row)
        _event(db,'DEPENDENCY_SKIPPED',{'logical_slot':attempt_id})

def model_deferred(state,model):
    with state.db() as db:
        return _exists(db) and any(json.loads(r[0])['model']==model and json.loads(r[0])['state']=='DEFERRED' for r in db.execute('SELECT body FROM next_live_requests'))

from .services import DelegatedClient,_PROVIDER_ADMISSION
class NextLiveClient(DelegatedClient):
    def measure(self,request,*,local_counter=None):
        if 'responseSchema' in request['body'].get('generationConfig',{}):raise PermissionError('RESPONSE_SCHEMA_FULL_INPUT_MEASUREMENT_NOT_VALIDATED')
        if self.binding['count_method']!='PROVIDER_COUNT':return super().measure(request,local_counter=local_counter)
        body={k:v for k,v in request['body'].items() if k in {'contents','systemInstruction'}}
        rid=str(uuid.uuid5(uuid.UUID(request['request_id']),'COUNT'))
        result=self.call({**request,'request_id':rid,'body':body,'body_hash':digest(body)},'COUNT')
        if result['status']!='COMPLETED':return None,result
        return {'method':'PROVIDER_COUNT','tokenizer':self.binding['tokenizer'],'tokens':result['response']['estimated_input_tokens'],
            'body_hash':request['body_hash'],'count_request_id':result['request_id'],'count_result_sha256':digest(result)},None
    def call(self,request,kind,*,input_measurement=None):
        physical=deepcopy(request)
        while True:
            bind(self.budget.state,physical,kind,self.index)
            with _PROVIDER_ADMISSION:
                with self.budget.state.db() as db:bound=_row(db,physical['request_id'])
                self.budget.config['reservation_microusd'][kind]=bound['amount']
                result=super().call(physical,kind,input_measurement=input_measurement)
            with self.budget.state.db() as db:row=_row(db,physical['request_id'])
            if row['state'] not in {'CAPACITY','RETRIED','DEFERRED'}:return result
            child=retry_or_defer(self.budget.state,self.index,physical['request_id'])
            if child is None:
                with self.budget.state.db() as db:fused=db.execute('SELECT status FROM dispatch_control').fetchone()[0]=='FUSED'
                return {**result,'status':'INFRA_FAILURE' if fused else 'CAPACITY_UNAVAILABLE','last_physical_result_sha256':digest(result),'logical_request_id':request['request_id']}
            # No lock during the bounded delay. Recheck authority and the durable
            # fuse at dispatch, including after a process restart.
            while time.time()<child['not_before']:
                time.sleep(min(.25,child['not_before']-time.time()))
            self.authorize_live()
            physical={**physical,'request_id':child['id'],'parent_request_id':child['parent_request_id'],
                'logical_request_id':child['root_request_id'],'capacity_attempt':child['attempt']}
