"""Incremental fsync journals; incomplete last bytes never count as an event."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
from rcwg_spec.common import canonical, digest
from .datasets import open_regular
from .errors import ExecFault

FIELDS={'version','sequence','previous_sha256','execution_key','manifest_hash',
        'origin','pid','monotonic_ns','event','status','payload','sha256'}


def read_json(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ExecFault('PERSISTED_DUPLICATE_KEY')
            result[key]=value
        return result
    try:
        with os.fdopen(open_regular(path),'rb') as stream:raw=stream.read()
        value=json.loads(raw,object_pairs_hook=pairs)
        if canonical(value)!=raw:raise ExecFault('PERSISTED_NONCANONICAL')
        return value
    except (ValueError,UnicodeError,RecursionError,TypeError,OverflowError):
        raise ExecFault('PERSISTED_JSON_INVALID') from None


class Journal:
    def __init__(self,path,*,execution_key,manifest_hash,origin):
        self.path=Path(path)
        self.execution_key=execution_key;self.manifest_hash=manifest_hash;self.origin=origin
        self.sequence=0;self.previous='0'*64
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        self.stream=os.fdopen(fd,'wb',buffering=0)

    def append(self,event,status,payload):
        record={'version':'EXEC001_JOURNAL_1.0','sequence':self.sequence,'previous_sha256':self.previous,
                'execution_key':self.execution_key,'manifest_hash':self.manifest_hash,
                'origin':self.origin,'pid':os.getpid(),'monotonic_ns':time.perf_counter_ns(),
                'event':event,'status':status,'payload':payload}
        record['sha256']=digest(record)
        data=canonical(record)+b'\n'
        position=0
        while position<len(data):position+=self.stream.write(data[position:])
        os.fsync(self.stream.fileno())
        self.previous=record['sha256'];self.sequence+=1
        return record

    def close(self):self.stream.close()


def read_journal(path,*,execution_key,manifest_hash,origin,pid=None,allow_partial=False):
    try:
        with os.fdopen(open_regular(path),'rb') as stream:raw=stream.read()
    except ExecFault:
        raise
    records=[];previous='0'*64;last=-1;partial=False
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b'\n'):
            if allow_partial:partial=True;break
            raise ExecFault('JOURNAL_PARTIAL')
        try:
            item=json.loads(line)
            if canonical(item)+b'\n'!=line:raise ExecFault('JOURNAL_CANONICAL')
        except (ValueError,UnicodeError,RecursionError,TypeError):raise ExecFault('JOURNAL_JSON') from None
        if type(item) is not dict or set(item)!=FIELDS:raise ExecFault('JOURNAL_SHAPE')
        if item['version']!='EXEC001_JOURNAL_1.0':raise ExecFault('JOURNAL_VERSION')
        if type(item['sequence']) is not int or item['sequence']!=len(records):raise ExecFault('JOURNAL_SEQUENCE')
        if item['previous_sha256']!=previous or item['sha256']!=digest({k:v for k,v in item.items() if k!='sha256'}):
            raise ExecFault('JOURNAL_CHAIN')
        if item['execution_key']!=execution_key or item['manifest_hash']!=manifest_hash or item['origin']!=origin:
            raise ExecFault('JOURNAL_IDENTITY')
        if type(item['pid']) is not int or item['pid']<=0 or (pid is not None and item['pid']!=pid):raise ExecFault('JOURNAL_PID')
        if type(item['monotonic_ns']) is not int or item['monotonic_ns']<last:raise ExecFault('JOURNAL_CLOCK')
        if type(item['event']) is not str or type(item['status']) is not str or type(item['payload']) is not dict:
            raise ExecFault('JOURNAL_SHAPE')
        last=item['monotonic_ns'];previous=item['sha256'];records.append(item)
    return {'events':records,'partial_tail':partial,'last_sha256':previous,
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw)}


def validate_node_events(events,plan,*,completed):
    """Actual pull requests and iterator intervals, not invented DAG scheduling."""
    nodes={'root/'+n['id']+'#0':n for n in plan['nodes']}
    states={}
    transitions={'node_queued':(None,'QUEUED'),'node_ready':('QUEUED','READY'),
                 'node_started':('READY','RUNNING'),'node_finished':('RUNNING',None)}
    for event in events:
        if event['event'] not in transitions:continue
        body=event['payload'];ident=body.get('node_instance_id')
        if ident not in nodes:raise ExecFault('JOURNAL_NODE_UNKNOWN')
        node=nodes[ident]
        if body.get('operator')!=node['operator'] or body.get('implementation')!=node['implementation']:
            raise ExecFault('JOURNAL_DISPATCH_MISMATCH')
        expected,target=transitions[event['event']]
        if states.get(ident)!=expected:raise ExecFault('JOURNAL_NODE_ORDER')
        if target is None:
            if event['status'] not in {'COMPLETED','FAILED'}:raise ExecFault('JOURNAL_NODE_STATUS')
            target=event['status']
        elif event['status']!=target:raise ExecFault('JOURNAL_NODE_STATUS')
        states[ident]=target
    if completed and (set(states)!=set(nodes) or any(s!='COMPLETED' for s in states.values())):
        raise ExecFault('JOURNAL_NODE_MISSING')
    return states
