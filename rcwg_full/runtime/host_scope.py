"""Receipt-bound finite FULL launches. No system writes happen in admission."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from rcwg_full.evidence import digest, safe_path, canonical
from rcwg_full.runtime.measurement import runtime_identity
from rcwg_full.campaign.sealing import validate_receipt


def run_identity(attempt_id):
    return 'f' + uuid.UUID(attempt_id).hex


class HostClaim:
    def __init__(self, scope, receipt, task, build, slot_id, attempt_id, *, identity_reader=runtime_identity):
        self.scope, self.task, self.build = scope, task, build
        self.identity_reader = identity_reader
        self.attempt_id = str(uuid.UUID(attempt_id)); self.run_id = run_identity(attempt_id)
        self.receipt_hash = validate_receipt(receipt, action='HOST', subject_hash=digest(scope), actor_role='Owner')
        if scope.get('revision') != 'FULL001_HOST_SCOPE_2': raise PermissionError('FINITE_FULL_SCOPE_REQUIRED')
        self.recheck()
        entries = scope.get('slots', [])
        if len({s['slot_id'] for s in entries}) != len(entries): raise PermissionError('HOST_DUPLICATE_SLOT')
        selected = [s for s in entries if s['slot_id'] == slot_id and s['task_hash'] == digest(task)]
        if len(selected) != 1: raise PermissionError('HOST_TASK_SLOT_NOT_APPROVED')
        limit = selected[0]['max_attempts']
        if type(limit) is not int or not 1 <= limit <= 2: raise PermissionError('HOST_FINITE_ATTEMPT_LIMIT')
        self.ledger = safe_path(scope['claim_ledger'])
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        binding = {'scope_hash': digest(scope), 'receipt_hash': self.receipt_hash,
                   'slot_id': slot_id, 'attempt_id': self.attempt_id, 'run_id': self.run_id,
                   'runtime_identity_hash': digest(scope['runtime_identity']), 'task_hash': digest(task)}
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS claims (run_id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL, scope_hash TEXT NOT NULL, slot_id TEXT NOT NULL, state TEXT NOT NULL, binding TEXT NOT NULL, evidence TEXT)')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM claims WHERE run_id=? OR attempt_id=?', (self.run_id, self.attempt_id)).fetchone():
                raise PermissionError('HOST_CLAIM_ALREADY_CONSUMED_OR_UNCERTAIN')
            used = db.execute('SELECT count(*) FROM claims WHERE scope_hash=? AND slot_id=?', (digest(scope), slot_id)).fetchone()[0]
            if used >= limit: raise PermissionError('HOST_FINITE_SCOPE_EXHAUSTED')
            db.execute('INSERT INTO claims VALUES (?,?,?,?,?,?,NULL)',
                       (self.run_id, self.attempt_id, digest(scope), slot_id, 'CLAIMED', canonical(binding).decode()))
        self.binding = binding

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.ledger, timeout=20)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db: yield db
        finally: db.close()

    def recheck(self):
        actual = self.identity_reader(self.task, self.build, affinity=self.scope['affinity'])
        if actual != self.scope.get('runtime_identity'): raise PermissionError('HOST_RUNTIME_APPLICABILITY_CHANGED')
        if actual['host'].get('system') != 'Linux' or any(actual['host'].get(k) in {None, 'UNAVAILABLE'} for k in ('machine_id_sha256','boot_id_sha256','kernel')):
            raise PermissionError('HOST_IDENTITY_REQUIRED')

    def activate(self):
        self.recheck()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE claims SET state='STARTING' WHERE run_id=? AND state='CLAIMED'", (self.run_id,)).rowcount
            if changed != 1: raise PermissionError('HOST_CLAIM_NOT_FRESH')

    def finish(self, report):
        # STARTING survives a crash; no lease expiry or automatic resend exists.
        clean = report.get('cleanup', {}).get('status') == 'REMOVED'
        with self.connect() as db:
            db.execute('UPDATE claims SET state=?,evidence=? WHERE run_id=?',
                       ('CONSUMED' if clean else 'UNCERTAIN', canonical(report).decode(), self.run_id))

    def snapshot(self):
        with self.connect() as db:
            row = db.execute('SELECT state,binding,evidence FROM claims WHERE run_id=?', (self.run_id,)).fetchone()
        return {'state': row[0], 'binding': json.loads(row[1]), 'evidence': json.loads(row[2]) if row[2] else None}
