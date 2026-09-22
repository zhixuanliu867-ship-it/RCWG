"""SQLite transactional logical slots. Lease expiry never authorizes duplication."""
import sqlite3
import time
import uuid
import json
from contextlib import contextmanager
from rcwg_full.evidence import canonical,digest,safe_path


class Conflict(RuntimeError):pass


class CampaignStore:
    def __init__(self,path,*,read_only=False):
        self.path=safe_path(path)
        self.read_only=read_only
        self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro' if read_only else self.path,uri=read_only,timeout=30,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        if read_only:
            self.db.execute('PRAGMA query_only=ON')
            return
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, response TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS slots(id TEXT PRIMARY KEY, definition TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'NOT_RUN', version INTEGER NOT NULL DEFAULT 0, owner TEXT, expires_ns INTEGER, active_attempt TEXT);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, slot_id TEXT NOT NULL REFERENCES slots(id), parent TEXT REFERENCES attempts(id), role TEXT NOT NULL, status TEXT NOT NULL, retry_index INTEGER NOT NULL, evidence TEXT);
        CREATE TABLE IF NOT EXISTS audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT, time_ns INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metadata(kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0, document TEXT NOT NULL, PRIMARY KEY(kind,id));
        ''')

    def close(self):self.db.close()

    @contextmanager
    def transaction(self):
        if self.read_only:raise PermissionError('READ_ONLY_STORE')
        self.db.execute('BEGIN IMMEDIATE')
        try:yield;self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise

    def _audit(self,action,payload):self.db.execute('INSERT INTO audit(time_ns,action,payload) VALUES(?,?,?)',(time.time_ns(),action,canonical(payload).decode()))

    def register(self,slots):
        with self.transaction():
            for slot in slots:
                raw=canonical(slot).decode();old=self.db.execute('SELECT definition FROM slots WHERE id=?',(slot['slot_id'],)).fetchone()
                if old and old['definition']!=raw:raise Conflict('SLOT_DEFINITION_CHANGED')
                self.db.execute('INSERT OR IGNORE INTO slots(id,definition) VALUES(?,?)',(slot['slot_id'],raw))

    def claim(self,slot_id,owner,idempotency_key, *, version=0, lease_seconds=60):
        if not owner or lease_seconds<=0:raise ValueError('CLAIM_INPUT')
        payload={'slot_id':slot_id,'owner':owner,'version':version,'lease_seconds':lease_seconds};h=digest(payload)
        with self.transaction():
            prior=self.db.execute('SELECT * FROM requests WHERE key=?',(idempotency_key,)).fetchone()
            if prior:
                if prior['payload_hash']!=h:raise Conflict('IDEMPOTENCY_PAYLOAD_CONFLICT')
                return json.loads(prior['response'])
            row=self.db.execute('SELECT * FROM slots WHERE id=?',(slot_id,)).fetchone()
            if row is None:raise ValueError('UNKNOWN_SLOT')
            if row['version']!=version or row['status']!='NOT_RUN':raise Conflict('SLOT_NOT_CLAIMABLE')
            attempt=str(uuid.uuid4());expires=time.time_ns()+int(lease_seconds*1e9)
            self.db.execute('UPDATE slots SET status=?,owner=?,expires_ns=?,active_attempt=?,version=version+1 WHERE id=?',('CLAIMED',owner,expires,attempt,slot_id))
            role=json.loads(row['definition']).get('ledger_role','PRIMARY')
            if role not in {'PRIMARY','DIAGNOSTIC','TIMING_CONFIRMATION','MANUAL_DEBUG','EXTERNAL_REPLICATION'}:raise ValueError('SLOT_ROLE')
            self.db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',(attempt,slot_id,None,role,'CLAIMED',0,None))
            result={'slot_id':slot_id,'attempt_id':attempt,'version':version+1,'expires_ns':expires}
            self.db.execute('INSERT INTO requests VALUES(?,?,?)',(idempotency_key,h,canonical(result).decode()));self._audit('claim',result)
            return result

    def mark(self,slot_id,attempt_id,owner,version,status,evidence):
        allowed={'RUNNING','COMPLETED','MODEL_FAILURE','PLAN_INVALID','INFRA_FAILURE','UNKNOWN','SENT_UNCONFIRMED','TIMEOUT','OOM','CANCELLED','TRANSFORM_NOT_APPLICABLE'}
        if status not in allowed:raise ValueError('ATTEMPT_STATUS')
        with self.transaction():
            row=self.db.execute('SELECT * FROM slots WHERE id=?',(slot_id,)).fetchone()
            if row is None or (row['active_attempt'],row['owner'],row['version'])!=(attempt_id,owner,version):raise Conflict('OPTIMISTIC_VERSION')
            if row['status'] not in {'CLAIMED','RUNNING','UNKNOWN','SENT_UNCONFIRMED'}:raise Conflict('TERMINAL_IMMUTABLE')
            if row['status'] in {'UNKNOWN','SENT_UNCONFIRMED'} and (evidence.get('reconciliation',{}).get('worker_stopped') is not True or evidence.get('reconciliation',{}).get('request_uncertain') is not False):raise Conflict('RECONCILIATION_INCOMPLETE')
            self.db.execute('UPDATE attempts SET status=?,evidence=? WHERE id=?',(status,canonical(evidence).decode(),attempt_id))
            self.db.execute('UPDATE slots SET status=?,version=version+1 WHERE id=?',(status,slot_id));self._audit('transition',{'slot_id':slot_id,'attempt_id':attempt_id,'status':status,'evidence':evidence})
            return version+1

    def reconcile(self,now_ns=None):
        now_ns=time.time_ns() if now_ns is None else now_ns
        rows=[dict(r) for r in self.db.execute('SELECT * FROM slots ORDER BY id')]
        for row in rows:
            row['coordination']='RECONCILE_REQUIRED' if row['expires_ns'] is not None and row['expires_ns']<now_ns and row['status'] in {'CLAIMED','RUNNING','UNKNOWN','SENT_UNCONFIRMED'} else 'NO_NEW_ACTION'
            row['launch_authorized']=False
        return rows

    def retry(self,slot_id,owner,version,*,reconciliation):
        # Only a proved stopped, definitely-unsent/completed facility attempt is retryable.
        if reconciliation.get('worker_stopped') is not True or reconciliation.get('request_uncertain') is not False:raise Conflict('RECONCILIATION_INCOMPLETE')
        with self.transaction():
            slot=self.db.execute('SELECT * FROM slots WHERE id=?',(slot_id,)).fetchone()
            if slot is None or slot['version']!=version or slot['status']!='INFRA_FAILURE':raise Conflict('RETRY_NOT_ALLOWED')
            old=self.db.execute('SELECT * FROM attempts WHERE id=?',(slot['active_attempt'],)).fetchone()
            if old['retry_index']>=1:raise Conflict('RETRY_LIMIT')
            attempt=str(uuid.uuid4())
            self.db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',(attempt,slot_id,old['id'],'INFRA_RETRY','CLAIMED',old['retry_index']+1,None))
            self.db.execute('UPDATE slots SET status=?,owner=?,active_attempt=?,version=version+1,expires_ns=? WHERE id=?',('CLAIMED',owner,attempt,time.time_ns()+60_000_000_000,slot_id))
            self._audit('retry',{'slot_id':slot_id,'parent':old['id'],'attempt':attempt,'reconciliation':reconciliation})
            return {'attempt_id':attempt,'version':version+1}

    def upstream_failure(self,generation_slot_id,cause):
        if cause not in {'MODEL_FAILURE','PLAN_INVALID'}:raise ValueError('UPSTREAM_FAILURE_NOT_CONFIRMED')
        with self.transaction():
            parent=self.db.execute('SELECT status FROM slots WHERE id=?',(generation_slot_id,)).fetchone()
            if parent is None or parent['status']!=cause:raise Conflict('UPSTREAM_FAILURE_NOT_TERMINAL')
            rows=list(self.db.execute("SELECT id,definition FROM slots WHERE status='NOT_RUN'"))
            for row in rows:
                definition=json.loads(row['definition'])
                if generation_slot_id in definition.get('expected_dependencies',[]):
                    self.db.execute("UPDATE slots SET status='NOT_RUN_UPSTREAM_PLAN_FAILURE',version=version+1 WHERE id=?",(row['id'],))
            self._audit('upstream_failure',{'generation_slot_id':generation_slot_id,'cause':cause})

    def slot(self,slot_id):
        row=self.db.execute('SELECT * FROM slots WHERE id=?',(slot_id,)).fetchone()
        if row is None:raise ValueError('UNKNOWN_SLOT')
        return {**dict(row),'definition':json.loads(row['definition'])}

    def cancel_pending(self,slot_id,version):
        with self.transaction():
            changed=self.db.execute("UPDATE slots SET status='CANCELLED',version=version+1 WHERE id=? AND version=? AND status='NOT_RUN'",(slot_id,version))
            if changed.rowcount!=1:raise Conflict('SLOT_NOT_PENDING')
            self._audit('cancel_before_launch',{'slot_id':slot_id,'physical_attempt':False})

    def observations(self,mode):
        """One row per actual attempt; explicit unrun dependents have no resources."""
        result=[]
        for row in self.db.execute('SELECT * FROM slots ORDER BY id'):
            definition=json.loads(row['definition'])
            attempts=list(self.db.execute('SELECT * FROM attempts WHERE slot_id=? ORDER BY retry_index,id',(row['id'],)))
            for attempt in attempts:
                evidence=json.loads(attempt['evidence']) if attempt['evidence'] else {}
                result.append({**definition,**evidence,'slot_id':row['id'],'attempt_id':attempt['id'],
                    'parent_attempt_id':attempt['parent'],'ledger_role':attempt['role'],'status':attempt['status'],'mode':mode})
            if not attempts and row['status'] in {'NOT_RUN_UPSTREAM_PLAN_FAILURE','CANCELLED'}:
                result.append({**definition,'attempt_id':'not-run-'+row['id'],'physical_attempt':False,
                    'status':row['status'],'mode':mode,'failure_class':'CONFIRMED_PLAN' if row['status']=='NOT_RUN_UPSTREAM_PLAN_FAILURE' else 'CANCELLED','exec_elapsed_ns':None,
                    'worker_memory_peak_bytes':None,'semantic':None,'budget':None,'evidence_valid':True})
        return result
