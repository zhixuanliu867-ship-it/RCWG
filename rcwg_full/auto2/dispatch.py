"""One durable task dispatch fuse, serialized across threads and processes.

An OS lock serializes clients; it is not evidence of provider completion.
An abandoned ACTIVE row or an unresolved reservation fails closed on restart.
"""
from contextlib import contextmanager
import json
import os
import time
from rcwg_full.evidence import canonical, digest, safe_path


class DispatchGate:
    revision = 'AUTO2_DISPATCH_FUSE_1'

    def __init__(self, state):
        self.state = state
        self.path = safe_path(state.root / 'provider-dispatch.lock')

    @contextmanager
    def locked(self, timeout=120):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        acquired = False
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'\0'); os.fsync(fd)
            deadline = time.monotonic() + timeout
            while not acquired:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise PermissionError('TASK_DISPATCH_LOCK_BUSY') from None
                    time.sleep(.02)
            with self.state.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS dispatch_control (id INTEGER PRIMARY KEY CHECK(id=1), root_hash TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS dispatch_events (id INTEGER PRIMARY KEY, at_ns INTEGER NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL)')
                db.execute('INSERT OR IGNORE INTO dispatch_control VALUES(1,?,?,?)',
                           (digest(self.state.authority), 'OPEN', '{}'))
                row = db.execute('SELECT root_hash FROM dispatch_control WHERE id=1').fetchone()
                if row[0] != digest(self.state.authority):
                    raise PermissionError('DISPATCH_ROOT_CANNOT_RESET')
            yield self
        finally:
            if acquired:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _record(self, db, status, detail):
        encoded = canonical({'revision': self.revision, **detail}).decode()
        db.execute('UPDATE dispatch_control SET status=?,detail=? WHERE id=1', (status, encoded))
        db.execute('INSERT INTO dispatch_events(at_ns,status,detail) VALUES(?,?,?)', (time.time_ns(), status, encoded))

    def admit(self, request_id, kind, *, body_hash=None, scope_hash=None):
        refusal = None
        with self.state.db() as db:
            db.execute('BEGIN IMMEDIATE')
            status, detail = db.execute('SELECT status,detail FROM dispatch_control WHERE id=1').fetchone()
            from .recovery import check_dispatch
            isolated=check_dispatch(db,request_id,kind,body_hash,scope_hash)
            unresolved = db.execute("SELECT id,status FROM reservations WHERE kind IN ('G','E','COUNT') AND status IN ('SENT_UNCONFIRMED','UNKNOWN','RESERVED_BEFORE_IO')").fetchall()
            unresolved=[r for r in unresolved if r[0] not in isolated]
            if status == 'ACTIVE':
                self._record(db, 'FUSED', {'reason': 'ABANDONED_CLIENT_PERMIT', 'prior': json.loads(detail)})
                refusal = 'TASK_DISPATCH_UNRESOLVED_ABANDONED_PERMIT'
            elif status == 'FUSED':
                refusal = 'TASK_DISPATCH_FUSED'
            elif unresolved:
                self._record(db, 'FUSED', {'reason': 'UNRESOLVED_PERSISTED_RESERVATION', 'requests': unresolved})
                refusal = 'TASK_DISPATCH_UNRESOLVED_RESERVATION'
            else:
                self._record(db, 'ACTIVE', {'request_id': request_id, 'kind': kind,
                             'provider_active_count': None, 'client_pid': os.getpid()})
        if refusal:
            raise PermissionError(refusal)

    def finish(self, request_id, result):
        status = result.get('status')
        fused = status in {'SENT_UNCONFIRMED', 'UNKNOWN', 'SERVICE_DRIFT', 'INFRA_FAILURE'}
        with self.state.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current, detail = db.execute('SELECT status,detail FROM dispatch_control WHERE id=1').fetchone()
            if current != 'ACTIVE' or json.loads(detail)['request_id'] != request_id:
                raise PermissionError('DISPATCH_PERMIT_MISMATCH')
            self._record(db, 'FUSED' if fused else 'OPEN', {'request_id': request_id,
                         'result_status': status, 'result_sha256': digest(result),
                         'provider_active_count': None})
