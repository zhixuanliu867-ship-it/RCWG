"""Append-only full event journal; partial writes never constitute a seal."""
from pathlib import Path
import os
import threading
import time
import uuid
import json
from rcwg_full.evidence import canonical,digest,sha,read,write,safe_path


class Journal:
    def __init__(self, path, run_id, *, attempt_id=None, source_id='full001-worker', clock_id='monotonic_ns'):
        self.path=safe_path(path);self.run_id=run_id;self.attempt_id=attempt_id or run_id
        self.source_id=source_id;self.clock_id=clock_id;self.previous=None;self.sequence=0
        self.lock=threading.Lock();self.closed=False
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
                os.fsync(self.fd)
            except BaseException:
                self.closed=True;os.close(self.fd);raise
            self.previous=event['event_hash'];self.sequence+=1
            return event

    def close(self):
        with self.lock:
            if not self.closed:os.fsync(self.fd);os.close(self.fd);self.closed=True

    def seal(self, path):
        self.close();events=verify_journal(self.path,run_id=self.run_id)
        manifest={'run_id':self.run_id,'event_count':len(events),'journal_sha256':sha(read(self.path)),
            'last_event_hash':self.previous,'status':'SEALED'}
        write(path,manifest);return manifest


def verify_journal(path, *, run_id=None, expected_sha256=None):
    raw=read(path)
    if expected_sha256 is not None and sha(raw)!=expected_sha256:raise ValueError('JOURNAL_HASH')
    if raw and not raw.endswith(b'\n'):raise ValueError('JOURNAL_PARTIAL_WRITE')
    previous=None;last=-1;events=[];ids=set();identity=None
    for i,line in enumerate(raw.splitlines()):
        event=json.loads(line);payload={k:v for k,v in event.items() if k!='event_hash'}
        if event['event_hash']!=digest(payload) or event['previous_hash']!=previous or event['sequence']!=i:raise ValueError('JOURNAL_CHAIN')
        if type(event['monotonic_ns']) is not int or event['monotonic_ns']<last:raise ValueError('JOURNAL_CLOCK')
        current=(event['run_id'],event['attempt_id'],event['source_id'],event['clock_id'])
        if identity is not None and identity!=current:raise ValueError('JOURNAL_IDENTITY')
        identity=current
        if (run_id is not None and event['run_id']!=run_id) or event['event_id'] in ids:raise ValueError('JOURNAL_IDENTITY')
        ids.add(event['event_id']);previous=event['event_hash'];last=event['monotonic_ns'];events.append(event)
    return events


def otel_projection(events):
    """A lossy observation view. The original journal remains authoritative."""
    return [{'name':e['event_kind'],'timestamp_ns':e['monotonic_ns'],'trace_id':e['run_id'],
        'span_id':e['node_instance'],'attributes':{'event_id':e['event_id'],'event_hash':e['event_hash'],
        'status':e['status'],**e['payload']}} for e in events]
