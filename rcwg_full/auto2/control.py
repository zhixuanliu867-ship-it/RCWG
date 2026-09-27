"""Persistent task authority, cumulative reservations and evidence-bound transitions.

An automatic scope is a delegated execution record, never an Owner signature.
Unknown sends and reservations survive process crashes and resumed invocations.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sqlite3
import time
import uuid
from rcwg_full.evidence import canonical, digest, read, sha, safe_path, write

STATES = {'PREPARING','PREP_READY_FOR_LIVE','LIVE_RUNNING','RESULTS_SEALED',
          'PAUSED_EXTERNAL','PAUSED_BUDGET','FAILED_SOFTWARE'}
IDENTITIES = {'source','build','dependencies','host','boot','data','models','manifest'}


def positive(value, name, maximum=None):
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(name)
    return value


def validate_policy(policy):
    if policy.get('policy_id') != 'RCWG-FULL-001-AUTO2' or policy.get('version') != '1.0.0':
        raise ValueError('AUTO2_POLICY_VERSION')
    if policy.get('phases') != ['A_PREPARATION','B_LIVE_TESTING']:
        raise ValueError('AUTO2_TWO_PHASES')
    b = policy['budget']
    if type(b['planning_ceiling']) not in (int,float) or not 0 < b['planning_ceiling'] <= 100:
        raise ValueError('AUTO2_CUMULATIVE_CEILING')
    if b['reset_on_resume'] or b['unknown_send_releases_reservation']:
        raise ValueError('AUTO2_UNSAFE_BUDGET')
    if policy['authority']['kind'] != 'USER_TASK_DELEGATION':
        raise ValueError('AUTO2_AUTHORITY_KIND')
    caps = policy['initial_live']
    for key, maximum in [('max_g_requests',24),('max_e_requests',4),('max_count_requests',28),('max_total_requests',56)]:
        positive(caps[key], key, maximum)
    if caps['provider_retries'] != 0 or caps['concurrency'] != 1 or caps['cost_subcap_usd'] > 15:
        raise ValueError('AUTO2_INITIAL_BOUND')
    expected={'generators':6,'operators':32,'implementation_branches':56,'templates':72,
              'development_conditions':480,'test_conditions':960,'main_generation_slots':23040,
              'main_execution_slots':61440,'historical_total_planned_slots':150880}
    if any(policy['research_design'].get(k)!=v for k,v in expected.items()):
        raise ValueError('AUTO2_RESEARCH_DESIGN')
    if policy['auto_transition']['human_confirmation_required']:
        raise ValueError('AUTO2_NO_REAPPROVAL')
    return deepcopy(policy)


def delegation(policy, user_text, project, historical_accounting, *, lower_limit_microusd=None):
    validate_policy(policy)
    if not user_text.strip() or not project or not historical_accounting.get('reconciled_upper_bound'):
        raise ValueError('AUTO2_ROOT_EVIDENCE_REQUIRED')
    cap = int(policy['budget']['planning_ceiling'] * 1_000_000)
    if lower_limit_microusd is not None:
        cap = min(cap, positive(lower_limit_microusd,'EXISTING_LIMIT'))
    holds = historical_accounting['holds']
    if len({h['id'] for h in holds}) != len(holds):raise ValueError('HISTORY_DUPLICATE')
    for h in holds:
        positive(h['microusd'],'HISTORY_AMOUNT')
        if not h.get('evidence_sha256') or not h.get('reason'):raise ValueError('HISTORY_EVIDENCE')
    return {'revision':'AUTO2_DELEGATION_1','task_id':'RCWG-FULL-001','profile':'AUTO2',
            'authority_kind':'USER_TASK_DELEGATION','user_text':user_text,
            'user_text_sha256':sha(user_text.encode('utf8')),'policy_sha256':digest(policy),
            'project_id':project,'ceiling_microusd':cap,'historical_accounting':historical_accounting,
            'manual_signature':False,'scope_generated_by':'CODEX'}


class TaskState:
    """One task DB; binding or imports cannot change on resume."""
    def __init__(self, root, policy, authority):
        self.root=safe_path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.policy=validate_policy(policy);self.authority=deepcopy(authority)
        if authority['policy_sha256']!=digest(policy) or authority['authority_kind']!='USER_TASK_DELEGATION':
            raise PermissionError('ROOT_POLICY_BINDING')
        if authority['user_text_sha256']!=sha(authority['user_text'].encode('utf8')):
            raise PermissionError('ROOT_TEXT_BINDING')
        if not 0<authority['ceiling_microusd']<=int(policy['budget']['planning_ceiling']*1_000_000):
            raise PermissionError('ROOT_CEILING')
        self.path=self.root/'auto2.sqlite3'
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS root(id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scopes(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, scope TEXT, kind TEXT, amount INTEGER NOT NULL, status TEXT NOT NULL, evidence TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL);''')
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT hash FROM root WHERE id=1').fetchone()
            if old and old[0]!=digest(authority):raise PermissionError('CUMULATIVE_ROOT_CANNOT_RESET')
            if not old:
                db.execute('INSERT INTO root VALUES(1,?,?)',(digest(authority),canonical(authority).decode()))
                for hold in authority['historical_accounting']['holds']:
                    db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',('history:'+hold['id'],None,'HISTORY',hold['microusd'],'HISTORICAL_HOLD',canonical(hold).decode()))
                db.execute('INSERT INTO events(at,state,detail) VALUES(?,?,?)',(time.time_ns(),'PREPARING','{}'))
        rootfile=self.root/'ROOT_DELEGATION_RECORD.json'
        if not rootfile.exists():write(rootfile,authority)
        elif json.loads(read(rootfile))!=authority:raise PermissionError('ROOT_FILE_CONFLICT')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:yield db
        finally:db.close()

    def derive_scope(self, *, stage, identity, limits, ceiling_microusd, expires_at):
        if set(identity)!=IDENTITIES or any(not isinstance(v,str) or not v for v in identity.values()):
            raise ValueError('SCOPE_IDENTITIES_REQUIRED')
        if stage not in {'A_INFRA','B_INITIAL','B_DEVELOPMENT','B_REFERENCE','B_FORMAL'}:raise ValueError('SCOPE_STAGE')
        positive(ceiling_microusd,'SCOPE_CEILING',self.authority['ceiling_microusd'])
        if not limits or set(limits)-{'G','E','COUNT','VM','BUILD','STORAGE','HOST'}:raise ValueError('SCOPE_KINDS')
        for k,v in limits.items():positive(v,'SCOPE_LIMIT')
        if stage=='B_INITIAL':
            initial=self.policy['initial_live']
            if ceiling_microusd>initial['cost_subcap_usd']*1_000_000:raise PermissionError('INITIAL_BUDGET')
            for kind,key in [('G','max_g_requests'),('E','max_e_requests'),('COUNT','max_count_requests')]:
                if limits.get(kind,0)>initial[key]:raise PermissionError('INITIAL_REQUEST_LIMIT')
            if set(limits)-{'G','E','COUNT'} or sum(limits.values())>initial['max_total_requests']:raise PermissionError('INITIAL_REQUEST_LIMIT')
        expires=datetime.fromisoformat(expires_at)
        if expires.tzinfo is None or not 0<(expires-datetime.now(timezone.utc)).total_seconds()<=86400:
            raise PermissionError('SCOPE_LEASE_MAX_24H')
        scope={'revision':'AUTO2_EXECUTION_SCOPE_1','authority_kind':'USER_TASK_DELEGATION','scope_generated_by':'CODEX',
               'root_sha256':digest(self.authority),'policy_sha256':digest(self.policy),'project_id':self.authority['project_id'],
               'stage':stage,'identity':identity,'limits':limits,'ceiling_microusd':ceiling_microusd,'expires_at':expires_at,
               'retries':0,'concurrency':1,'manual_signature':False}
        sid=digest(scope)
        with self.db() as db:db.execute('INSERT OR IGNORE INTO scopes VALUES(?,?)',(sid,canonical(scope).decode()))
        path=self.root/('scope-'+sid+'.json')
        if not path.exists():write(path,scope)
        return scope

    def validate_scope(self,scope,identity):
        if scope['root_sha256']!=digest(self.authority) or scope['project_id']!=self.authority['project_id']:
            raise PermissionError('SCOPE_ROOT_MISMATCH')
        with self.db() as db:row=db.execute('SELECT body FROM scopes WHERE id=?',(digest(scope),)).fetchone()
        if row is None or json.loads(row[0])!=scope:raise PermissionError('SCOPE_NOT_DERIVED')
        if scope['identity']!=identity:raise PermissionError('SCOPE_APPLICABILITY_CHANGED')
        if datetime.now(timezone.utc)>=datetime.fromisoformat(scope['expires_at']):raise PermissionError('SCOPE_EXPIRED')

    def reserve(self,scope,request_id,kind,amount,identity):
        self.validate_scope(scope,identity);positive(amount,'RESERVATION_AMOUNT')
        if not isinstance(request_id,str) or not request_id:raise ValueError('REQUEST_ID')
        sid=digest(scope)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM reservations WHERE id=?',(request_id,)).fetchone():raise PermissionError('REQUEST_ALREADY_RESERVED_NO_REPLAY')
            used=db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations').fetchone()[0]
            scope_used=db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations WHERE scope=?',(sid,)).fetchone()[0]
            count=db.execute('SELECT COUNT(*) FROM reservations WHERE scope=? AND kind=?',(sid,kind)).fetchone()[0]
            cleanup=int(self.policy['budget']['cleanup_and_billing_lag_reserve']*1_000_000)
            if used+amount>self.authority['ceiling_microusd']-cleanup or scope_used+amount>scope['ceiling_microusd']:
                raise PermissionError('NO_AFFORDABLE_NEXT_COMPLETE_BLOCK')
            if count>=scope['limits'].get(kind,0):raise PermissionError('SCOPE_REQUEST_LIMIT')
            stages=['A_INFRA'] if scope['stage']=='A_INFRA' else ['B_DEVELOPMENT','B_REFERENCE','B_FORMAL'] if scope['stage']!='B_INITIAL' else []
            if stages:
                rows=db.execute('SELECT s.body,r.amount FROM reservations r JOIN scopes s ON r.scope=s.id').fetchall()
                used_phase=sum(value for body,value in rows if json.loads(body)['stage'] in stages)
                allocation=self.policy['budget']['phase_a_infrastructure_allocation' if scope['stage']=='A_INFRA' else 'remaining_live_and_reference_allocation']
                if used_phase+amount>int(allocation*1_000_000):raise PermissionError('CUMULATIVE_PHASE_ALLOCATION')
            if scope['stage']=='B_INITIAL':
                # A new scope or boot must not reset B1's task-wide allowance.
                rows=db.execute('SELECT r.kind,r.amount FROM reservations r JOIN scopes s ON r.scope=s.id WHERE json_extract(s.body,\'$.stage\')=\'B_INITIAL\'').fetchall()
                initial=self.policy['initial_live'];key={'G':'max_g_requests','E':'max_e_requests','COUNT':'max_count_requests'}[kind]
                if sum(r[0]==kind for r in rows)>=initial[key] or len(rows)>=initial['max_total_requests'] or sum(r[1] for r in rows)+amount>initial['cost_subcap_usd']*1_000_000:
                    raise PermissionError('INITIAL_CUMULATIVE_LIMIT')
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,NULL)',(request_id,sid,kind,amount,'RESERVED_BEFORE_IO'))
        return amount

    def observe(self,request_id,status,evidence):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            n=db.execute("UPDATE reservations SET status=?,evidence=? WHERE id=? AND status='RESERVED_BEFORE_IO'",(status,canonical(evidence).decode(),request_id)).rowcount
            if n!=1:raise PermissionError('RESERVATION_ALREADY_OBSERVED')

    def transition(self,state,detail):
        if state not in STATES:raise ValueError('AUTO2_STATE')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT state FROM events ORDER BY id DESC LIMIT 1').fetchone()[0]
            if prior=='PREP_READY_FOR_LIVE' and state!='LIVE_RUNNING':raise PermissionError('NEXT_ACTION_MUST_BE_LIVE')
            if state=='RESULTS_SEALED' and prior not in {'LIVE_RUNNING','PAUSED_EXTERNAL','PAUSED_BUDGET'}:raise PermissionError('NO_LIVE_RESULTS_TO_SEAL')
            db.execute('INSERT INTO events(at,state,detail) VALUES(?,?,?)',(time.time_ns(),state,canonical(detail).decode()))

    def affordable(self,amount):
        positive(amount,'BLOCK_RESERVATION')
        return self.summary()['remaining_microusd']-int(self.policy['budget']['cleanup_and_billing_lag_reserve']*1_000_000)>=amount

    def summary(self):
        with self.db() as db:
            rows=[dict(zip(('request_id','scope','kind','microusd','status','evidence'),r)) for r in db.execute('SELECT * FROM reservations ORDER BY rowid')]
            events=[{'at_ns':at,'state':state,'detail':json.loads(detail)} for at,state,detail in db.execute('SELECT at,state,detail FROM events ORDER BY id')]
        total=sum(r['microusd'] for r in rows)
        return {'state':events[-1]['state'],'root_hash':digest(self.authority),'events':events,'reservations':rows,
                'ceiling_microusd':self.authority['ceiling_microusd'],'reserved_microusd':total,
                'remaining_microusd':self.authority['ceiling_microusd']-total,'invoice_cost_usd':None,
                'invoice_reason':'RESERVATIONS_ARE_CONSERVATIVE_ADMISSION_NOT_PROVIDER_INVOICE'}


def verify_evidence(ref,identity,required_status='PASS'):
    raw=read(ref['path'])
    if sha(raw)!=ref['sha256']:raise PermissionError('EVIDENCE_BYTES_CHANGED')
    evidence=json.loads(raw)
    if evidence.get('status')!=required_status or evidence.get('identity')!=identity:
        raise PermissionError('EVIDENCE_STATUS_OR_APPLICABILITY')
    return evidence


def preparation_gate(evidence,identity,profile):
    required={'software','data','isolation','cloud','pricing','preregistration'}
    if profile=='FORMAL_RESOURCE':required.add('calibration')
    elif profile!='SERVICE_ONLY':raise ValueError('MEASUREMENT_PROFILE')
    if required-set(evidence):raise PermissionError('PREPARATION_EVIDENCE_MISSING:'+','.join(sorted(required-set(evidence))))
    checked={k:verify_evidence(evidence[k],identity) for k in required}
    if checked['software'].get('mock_only') or checked['cloud'].get('actual_account_verified') is not True:
        raise PermissionError('ACTUAL_PREPARATION_REQUIRED')
    # No returned model revision or E-reference dependency: only B can observe it.
    return {'status':'PASS','measurement_profile':profile,'budget_success_comparable':profile=='FORMAL_RESOURCE',
            'checked_evidence':{k:evidence[k]['sha256'] for k in required}}


def advance_to_live(state,scope,evidence,identity,profile,provider_action):
    gate=preparation_gate(evidence,identity,profile)
    state.validate_scope(scope,identity)
    if getattr(provider_action,'mode',None)!='LIVE':raise PermissionError('ACTUAL_PROVIDER_ADAPTER_REQUIRED')
    state.transition('PREP_READY_FOR_LIVE',gate)
    # No report/no-op return is permitted between these states and dispatch.
    state.transition('LIVE_RUNNING',{'scope_hash':digest(scope),'measurement_profile':profile})
    return provider_action()


def formal_gate(evidence,identity,*,scope,state):
    """A policy, software pass, or successful HTTP response cannot admit formal work."""
    preparation_gate(evidence,identity,'FORMAL_RESOURCE')
    checked={key:verify_evidence(evidence[key],identity) for key in ['frozen_data','model_coverage','reference_coverage','analysis_freeze']}
    if checked['frozen_data'].get('test_conditions')!=960:raise PermissionError('TEST_DATA_NOT_COMPLETE')
    models=checked['model_coverage'].get('observed_generator_identities',[])
    if len(models)!=6 or len(set(models))!=6:raise PermissionError('SIX_DISTINCT_OBSERVED_GENERATORS_REQUIRED')
    if checked['reference_coverage'].get('next_block_common_coverage') is not True:raise PermissionError('REFERENCE_BLOCK_MISSING')
    if scope['stage']!='B_FORMAL':raise PermissionError('FORMAL_SCOPE_REQUIRED')
    state.validate_scope(scope,identity)
    if not state.affordable(scope['ceiling_microusd']):raise PermissionError('NO_AFFORDABLE_NEXT_COMPLETE_BLOCK')
    return {'status':'ADMITTED','profile':'AUTO2','new_freeze_hash':digest(checked),'manual_signature':False}
