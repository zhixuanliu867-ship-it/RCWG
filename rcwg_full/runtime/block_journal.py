"""Lossless bounded blocks; identity is journal UUID plus verified sequence.

The public iterator expands records lazily. Block hashes bind every raw row,
the immutable identity header, and the preceding block. No event-ID RAM set.
"""
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from rcwg_full.evidence import canonical, digest, safe_path, write

REVISION = 'full001-block-events-2'
MAX_LINE = 1024 * 1024
TARGET = 64 * 1024


class BlockJournal:
    def __init__(self, path, run_id, *, attempt_id=None, source_id='full001-worker', clock_id='monotonic_ns'):
        self.path = safe_path(path)
        self.header = {'schema_version': REVISION, 'journal_id': str(uuid.uuid4()),
                       'run_id': run_id, 'attempt_id': attempt_id or run_id,
                       'source_id': source_id, 'clock_id': clock_id}
        self.run_id = run_id
        self.lock = threading.RLock()
        self.closed = self.failed = False
        self.sequence = self.batch_depth = self.size = 0
        self.rows = []
        self.previous = digest(self.header)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self._write(canonical(self.header) + b'\n')

    def _write(self, raw):
        try:
            view = memoryview(raw)
            while view:
                n = os.write(self.fd, view)
                if n <= 0: raise OSError('JOURNAL_SHORT_WRITE')
                view = view[n:]
        except BaseException:
            self.failed = self.closed = True
            os.close(self.fd)
            raise

    def _flush(self):
        if self.rows:
            block = {'previous_hash': self.previous, 'rows': self.rows}
            block['block_hash'] = digest(block)
            raw = canonical(block) + b'\n'
            if len(raw) > MAX_LINE: raise ValueError('JOURNAL_BLOCK_LIMIT')
            self._write(raw)
            self.previous = block['block_hash']
            self.rows = []; self.size = 0

    def append(self, kind, payload, *, node_instance=None, operation_id=None, status='OBSERVED'):
        with self.lock:
            if self.closed: raise RuntimeError('JOURNAL_CLOSED')
            row = [self.sequence, time.monotonic_ns(), kind, status, node_instance, operation_id, payload]
            size = len(canonical(row))
            if size > MAX_LINE - 1024: raise ValueError('JOURNAL_EVENT_LIMIT')
            if self.rows and self.size + size > TARGET: self._flush()
            self.rows.append(row); self.size += size + 1; self.sequence += 1
            if not self.batch_depth or self.size >= TARGET:
                self._flush(); self._sync()
            return expand(self.header, row)

    def _sync(self):
        try: os.fsync(self.fd)
        except BaseException:
            self.failed = self.closed = True
            os.close(self.fd)
            raise

    @contextmanager
    def batch(self):
        with self.lock:
            if self.closed: raise RuntimeError('JOURNAL_CLOSED')
            self.batch_depth += 1
        try: yield
        finally:
            with self.lock:
                self.batch_depth -= 1
                if not self.closed and not self.batch_depth:
                    self._flush(); self._sync()

    def close(self):
        with self.lock:
            if not self.closed:
                try: self._flush(); self._sync()
                finally:
                    if not self.closed: os.close(self.fd); self.closed = True

    def seal(self, path):
        self.close()
        if self.failed: raise ValueError('JOURNAL_WRITE_FAILED')
        from rcwg_full.runtime.events import journal_summary
        info = journal_summary(self.path, run_id=self.run_id)
        if info['event_count'] != self.sequence: raise ValueError('JOURNAL_COUNT')
        manifest = {'run_id': self.run_id, 'event_count': self.sequence,
                    'journal_sha256': info['journal_sha256'], 'last_event_hash': info['last']['event_hash'] if info['last'] else None,
                    'schema_version': REVISION, 'status': 'SEALED'}
        write(path, manifest)
        return manifest


def expand(header, row):
    sequence, ns, kind, status, node, operation, payload = row
    event = {**header, 'event_id': header['journal_id'] + ':' + str(sequence),
             'sequence': sequence, 'monotonic_ns': ns, 'event_kind': kind,
             'status': status, 'node_instance': node, 'operation_id': operation, 'payload': payload}
    event['event_hash'] = digest(event)
    return event


def iter_blocks(file, header, *, run_id=None):
    if set(header) != {'schema_version','journal_id','run_id','attempt_id','source_id','clock_id'}:
        raise ValueError('JOURNAL_IDENTITY')
    if str(uuid.UUID(header['journal_id'])) != header['journal_id'] or any(not isinstance(v,str) or not v for v in header.values()):
        raise ValueError('JOURNAL_IDENTITY')
    if run_id is not None and header['run_id'] != run_id: raise ValueError('JOURNAL_IDENTITY')
    previous = digest(header); sequence = 0; last = -1
    while True:
        raw = file.readline(MAX_LINE + 1)
        if not raw: break
        if len(raw) > MAX_LINE or not raw.endswith(b'\n'): raise ValueError('JOURNAL_PARTIAL_WRITE')
        block = json.loads(raw)
        if set(block) != {'previous_hash','rows','block_hash'} or not block['rows']:
            raise ValueError('JOURNAL_BLOCK')
        if block['previous_hash'] != previous or block['block_hash'] != digest({k:v for k,v in block.items() if k != 'block_hash'}):
            raise ValueError('JOURNAL_CHAIN')
        for row in block['rows']:
            if not isinstance(row,list) or len(row) != 7 or type(row[0]) is not int or row[0] != sequence: raise ValueError('JOURNAL_CHAIN')
            if type(row[1]) is not int or row[1] < last: raise ValueError('JOURNAL_CLOCK')
            if not isinstance(row[2],str) or not isinstance(row[3],str) or not isinstance(row[6],dict): raise ValueError('JOURNAL_EVENT')
            yield expand(header,row)
            sequence += 1; last = row[1]
        previous = block['block_hash']
