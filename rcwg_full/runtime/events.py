"""Append-only full event journal; partial writes never constitute a seal."""
from pathlib import Path
import os
import threading
import time
import uuid
import json
import hashlib
import sqlite3
import tempfile
from contextlib import contextmanager
from rcwg_full.evidence import canonical,digest,sha,read,write,safe_path


class Journal:
    def __init__(self, path, run_id, *, attempt_id=None, source_id='full001-worker', clock_id='monotonic_ns'):
        self.path=safe_path(path);self.run_id=run_id;self.attempt_id=attempt_id or run_id
        self.source_id=source_id;self.clock_id=clock_id;self.previous=None;self.sequence=0
        self.lock=threading.RLock();self.closed=False;self.batch_depth=0;self.pending_bytes=0
        self.fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)

    def append(self, kind, payload, *, node_instance=None, operation_id=None, status='OBSERVED'):
        with self.lock:
            if self.closed:raise RuntimeError('JOURNAL_CLOSED')
            event={'schema_version':'full001-events-1','event_id':str(uuid.uuid4()),'sequence':self.sequence,
                'source_id':self.source_id,'clock_id':self.clock_id,'run_id':self.run_id,
                'attempt_id':self.attempt_id,'node_instance':node_instance,'operation_id':operation_id,
                'monotonic_ns':time.monotonic_ns(),'event_kind':kind,'status':status,
                'payload':payload,'previous_hash':self.previous}
            event['event_hash']=digest(event);raw=canonical(event)+b'\n';view=memoryview(raw)
            try:
                while view:
                    n=os.write(self.fd,view)
                    if n<=0:raise OSError('JOURNAL_SHORT_WRITE')
                    view=view[n:]
                self.pending_bytes+=len(raw)
                if not self.batch_depth or self.pending_bytes>=1024*1024:
                    os.fsync(self.fd);self.pending_bytes=0
            except BaseException:
                self.closed=True;os.close(self.fd);raise
            self.previous=event['event_hash'];self.sequence+=1
            return event

    @contextmanager
    def batch(self):
        """Durable operation boundary; at most 1 MiB between syncs.

        Events retain individual IDs, times and chain hashes. The caller holds
        no in-memory list of events; writes happen immediately, with bounded
        sync coalescing. A crash leaves an unsealed journal, never accepted PASS.
        """
        with self.lock:
            if self.closed:raise RuntimeError('JOURNAL_CLOSED')
            self.batch_depth+=1
        # A scope can span asyncio scheduling or a native worker future. Never
        # retain a thread lock across that boundary: append still serializes
        # each chain update and the shared 1 MiB durability bound.
        try:yield
        finally:
            with self.lock:
                self.batch_depth-=1
                if not self.closed and not self.batch_depth and self.pending_bytes:
                    try:os.fsync(self.fd);self.pending_bytes=0
                    except BaseException:
                        self.closed=True;os.close(self.fd);raise

    def close(self):
        with self.lock:
            if not self.closed:os.fsync(self.fd);os.close(self.fd);self.closed=True

    def seal(self, path):
        self.close();info=journal_summary(self.path,run_id=self.run_id)
        manifest={'run_id':self.run_id,'event_count':info['event_count'],'journal_sha256':info['journal_sha256'],
            'last_event_hash':self.previous,'status':'SEALED'}
        write(path,manifest);return manifest


def iter_journal(path, *, run_id=None, expected_sha256=None, summary=None):
    """Validate lazily; consume to exhaustion before treating any data as trusted.

    Legacy UUID uniqueness uses a disk-backed SQLite index with bounded cache.
    Version 2 derives identity from a verified header and contiguous sequence.
    Raw SHA256 is accumulated in the same read pass for both encodings.
    """
    from rcwg_full.runtime.block_journal import REVISION, MAX_LINE, iter_blocks
    hasher=hashlib.sha256()
    class Hashed:
        def __init__(self,file):self.file=file
        def readline(self,limit):
            raw=self.file.readline(limit);hasher.update(raw);return raw
    count=0;first=last_event=None
    with safe_path(path).open('rb') as raw_file:
        file=Hashed(raw_file);line=file.readline(MAX_LINE+1)
        if line and (len(line)>MAX_LINE or not line.endswith(b'\n')):raise ValueError('JOURNAL_PARTIAL_WRITE')
        initial=json.loads(line) if line else None
        def legacy():
            previous=None;last=-1;identity=None;event=initial;i=0
            with tempfile.TemporaryDirectory(prefix='rcwg-journal-') as directory:
                db=sqlite3.connect(str(Path(directory)/'ids.sqlite3'))
                try:
                    db.execute('PRAGMA cache_size=-1024');db.execute('PRAGMA journal_mode=OFF')
                    db.execute('CREATE TABLE ids(id TEXT PRIMARY KEY) WITHOUT ROWID')
                    while event is not None:
                        payload={k:v for k,v in event.items() if k!='event_hash'}
                        if event['event_hash']!=digest(payload) or event['previous_hash']!=previous or type(event['sequence']) is not int or event['sequence']!=i:raise ValueError('JOURNAL_CHAIN')
                        if type(event['monotonic_ns']) is not int or event['monotonic_ns']<last:raise ValueError('JOURNAL_CLOCK')
                        current=(event['run_id'],event['attempt_id'],event['source_id'],event['clock_id'])
                        if identity is not None and identity!=current:raise ValueError('JOURNAL_IDENTITY')
                        identity=current
                        if run_id is not None and event['run_id']!=run_id:raise ValueError('JOURNAL_IDENTITY')
                        try:db.execute('INSERT INTO ids VALUES (?)',(event['event_id'],))
                        except sqlite3.IntegrityError:raise ValueError('JOURNAL_IDENTITY') from None
                        yield event
                        previous=event['event_hash'];last=event['monotonic_ns'];i+=1
                        line=file.readline(MAX_LINE+1)
                        if line and (len(line)>MAX_LINE or not line.endswith(b'\n')):raise ValueError('JOURNAL_PARTIAL_WRITE')
                        event=json.loads(line) if line else None
                finally:db.close()
        iterator=iter_blocks(file,initial,run_id=run_id) if initial and initial.get('schema_version')==REVISION else legacy()
        for event in iterator:
            if first is None:first=event
            last_event=event;count+=1
            yield event
    actual=hasher.hexdigest()
    if expected_sha256 is not None and actual!=expected_sha256:raise ValueError('JOURNAL_HASH')
    if summary is not None:summary.update(event_count=count,journal_sha256=actual,first=first,last=last_event)


def journal_summary(path, **kwargs):
    result={}
    for _ in iter_journal(path,summary=result,**kwargs):pass
    return result


def verify_journal(path, **kwargs):
    """Compatibility analysis API: explicitly materializes the complete stream."""
    return list(iter_journal(path,**kwargs))


def otel_projection(events):
    """A lossy observation view. The original journal remains authoritative."""
    return [{'name':e['event_kind'],'timestamp_ns':e['monotonic_ns'],'trace_id':e['run_id'],
        'span_id':e['node_instance'],'attributes':{'event_id':e['event_id'],'event_hash':e['event_hash'],
        'status':e['status'],**e['payload']}} for e in events]
