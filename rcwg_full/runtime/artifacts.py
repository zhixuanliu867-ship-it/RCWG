"""Actual Arrow storage and buffer leases, separate from cgroup accounting."""
from dataclasses import dataclass,field
from pathlib import Path
import os
import time
import uuid
import json
import hashlib
import threading
from rcwg_full.evidence import canonical,digest,sha,write,read,safe_path


@dataclass
class Artifact:
    artifact_id:str
    run_id:str
    producer_instance:str
    value:object
    type:dict
    domain:str|None
    source_refs:list
    buffer_ids:set=field(default_factory=set)
    storage:str='memory'
    format:str='arrow_ipc'
    path:Path|None=None
    content_sha256:str|None=None
    schema_hash:str|None=None
    logical_rows:int|None=None
    serialized_bytes:int|None=None
    created_ns:int=field(default_factory=time.monotonic_ns)
    sealed_ns:int|None=None
    release_status:str='LIVE'


class ArtifactStore:
    def __init__(self, directory, run_id, journal):
        self.directory=safe_path(directory);self.directory.mkdir(mode=0o700,exist_ok=False)
        self.run_id=run_id;self.journal=journal;self.artifacts={};self.buffers={};self.addresses={}
        self.copy_bytes=0;self.read_bytes=0;self.leases={};self.lock=threading.RLock()

    def _emit(self,kind,payload):return self.journal.append(kind,payload)

    def register(self, value, typ, producer, *, source_refs=(), storage='memory', format='arrow_ipc', parents=()):
        import pyarrow as pa
        aid=str(uuid.uuid4());ids=set()
        if isinstance(value,(pa.Table,pa.RecordBatch)):
            for col in value.columns:
                chunks=col.chunks if isinstance(col,pa.ChunkedArray) else [col]
                for chunk in chunks:
                    for buf in chunk.buffers():
                        if buf is None:continue
                        while buf.parent is not None:buf=buf.parent
                        key=(buf.address,buf.size)
                        bid=self.addresses.get(key)
                        if bid is None:
                            bid=str(uuid.uuid4());self.addresses[key]=bid
                            self.buffers[bid]={'buffer_id':bid,'run_id':self.run_id,'allocation_instance':producer,
                                'storage_kind':'arrow_memory','parent_buffer_id':None,'view_ranges':[],
                                'backing_file_id':None,'replica_id':bid,'key':key,'value':buf,'capacity_bytes':buf.size,
                                'created_ns':time.monotonic_ns(),'released_ns':None,'leases':set(),'artifacts':set()}
                            self._emit('buffer_created',{'buffer_id':bid,'capacity_bytes':buf.size,'storage_kind':'arrow_memory'})
                        ids.add(bid)
        for parent in parents:
            self.check(parent);ids.update(parent.buffer_ids)
        item=Artifact(aid,self.run_id,producer,value,typ,typ.get('domain'),list(source_refs),ids,storage,format)
        if isinstance(value,(pa.Table,pa.RecordBatch)):
            item.schema_hash=sha(value.schema.serialize().to_pybytes());item.logical_rows=value.num_rows
        else:item.schema_hash=digest(typ)
        self.artifacts[aid]=item
        self.leases[aid]=set()
        for bid in ids:self.buffers[bid]['artifacts'].add(aid)
        self._emit('artifact_created',{'artifact_id':aid,'buffer_ids':sorted(ids),'producer':producer,'schema_hash':item.schema_hash})
        return item

    def check(self,item):
        if not isinstance(item,Artifact) or item.run_id!=self.run_id or self.artifacts.get(item.artifact_id) is not item:raise ValueError('CAPABILITY_INVALID')
        if item.release_status!='LIVE':raise ValueError('ARTIFACT_RELEASED')

    def acquire(self,item,holder):
        self.check(item)
        if holder in self.leases[item.artifact_id]:raise ValueError('LEASE_DUPLICATE')
        self.leases[item.artifact_id].add(holder)
        for bid in item.buffer_ids:self.buffers[bid]['leases'].add((item.artifact_id,holder))
        self._emit('lease_acquired',{'artifact_id':item.artifact_id,'holder':holder})

    def drop_lease(self,item,holder):
        self.check(item)
        if holder not in self.leases[item.artifact_id]:raise ValueError('LEASE_UNKNOWN')
        self.leases[item.artifact_id].remove(holder)
        for bid in item.buffer_ids:
            lease=(item.artifact_id,holder)
            if lease not in self.buffers[bid]['leases']:raise ValueError('LEASE_UNKNOWN')
            self.buffers[bid]['leases'].remove(lease)
        self._emit('lease_dropped',{'artifact_id':item.artifact_id,'holder':holder})

    def _detach_buffers(self,item):
        for bid in item.buffer_ids:
            buf=self.buffers[bid];buf['artifacts'].discard(item.artifact_id)
            if not buf['artifacts'] and not buf['leases']:
                buf['released_ns']=time.monotonic_ns()
                if buf['key'] is not None:self.addresses.pop(buf['key'],None)
                buf['value']=None
                self._emit('buffer_released',{'buffer_id':bid,'released_ns':buf['released_ns']})

    def release(self,item):
        self.check(item)
        if self.leases[item.artifact_id] or any(self.buffers[bid]['leases'] for bid in item.buffer_ids):raise ValueError('RELEASE_BEFORE_LAST_USE')
        if any(self.buffers[bid]['artifacts']-{item.artifact_id} for bid in item.buffer_ids):raise ValueError('RELEASE_HAS_LIVE_ALIAS')
        # An unlink failure must preserve the actual lifetime and original result.
        try:
            if item.path is not None:item.path.unlink()
        except OSError as exc:
            self._emit('artifact_cleanup_failed',{'artifact_id':item.artifact_id,'cause':type(exc).__name__})
            raise
        self._detach_buffers(item)
        item.value=None;item.release_status='RELEASED'
        self._emit('artifact_released',{'artifact_id':item.artifact_id})

    def drop_view(self,item):
        self.check(item)
        if self.leases[item.artifact_id]:raise ValueError('LIVE_VIEW_LEASE')
        if item.path is not None:return self.release(item)
        self._detach_buffers(item)
        item.value=None;item.release_status='VIEW_DROPPED'
        self._emit('artifact_view_dropped',{'artifact_id':item.artifact_id})

    def seal(self,item):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.check(item)
        if item.sealed_ns is not None:return item
        if item.storage=='disk' and self.leases[item.artifact_id]:raise ValueError('SEAL_WITH_LIVE_LEASE')
        extension='parquet' if item.format=='parquet' else 'arrow' if isinstance(item.value,(pa.Table,pa.RecordBatch)) else 'json'
        temporary=self.directory/(item.artifact_id+'.partial')
        try:
            if isinstance(item.value,(pa.Table,pa.RecordBatch)):
                with temporary.open('xb') as f:
                    if item.format=='parquet':pq.write_table(pa.Table.from_batches([item.value]) if isinstance(item.value,pa.RecordBatch) else item.value,f,compression='NONE',use_dictionary=False,write_statistics=False)
                    else:
                        with pa.ipc.new_file(f,item.value.schema) as writer:
                            writer.write_table(item.value) if isinstance(item.value,pa.Table) else writer.write_batch(item.value)
                    f.flush();os.fsync(f.fileno())
            else:write(temporary,item.value)
            self._commit_file(item,temporary,extension)
        except BaseException as exc:
            self._emit('artifact_commit_failed',{'artifact_id':item.artifact_id,'cause':type(exc).__name__})
            raise
        return item

    def _commit_file(self,item,temporary,extension):
        with temporary.open('rb') as f:item.content_sha256=hashlib.file_digest(f,'sha256').hexdigest()
        item.serialized_bytes=temporary.stat().st_size
        path=self.directory/(item.content_sha256+'.'+item.artifact_id+'.'+extension)
        if path.exists():raise ValueError('ARTIFACT_ALREADY_EXISTS')
        os.rename(temporary,path);item.path=path
        if item.storage=='disk':
            self._detach_buffers(item);item.value=None
            bid=str(uuid.uuid4());now=time.monotonic_ns()
            self.buffers[bid]={'buffer_id':bid,'run_id':self.run_id,'allocation_instance':item.producer_instance,
                'storage_kind':'disk','parent_buffer_id':None,'view_ranges':[],
                'backing_file_id':path.name,'replica_id':bid,'key':None,'value':None,
                'capacity_bytes':item.serialized_bytes,'created_ns':now,'released_ns':None,
                'leases':set(),'artifacts':{item.artifact_id}}
            item.buffer_ids={bid}
            self._emit('buffer_created',{'buffer_id':bid,'capacity_bytes':item.serialized_bytes,'storage_kind':'disk'})
        committed_ns=time.monotonic_ns()
        metadata={k:v for k,v in vars(item).items() if k not in {'value','buffer_ids','path'}}
        metadata.update(buffer_ids=sorted(item.buffer_ids),filename=path.name,sealed_ns=committed_ns)
        write(self.directory/(item.artifact_id+'.metadata.json'),metadata)
        self._emit('artifact_sealed',metadata)
        item.sealed_ns=committed_ns

    def verify_file(self,item):
        self.check(item)
        if item.sealed_ns is None or item.path is None:raise ValueError('ARTIFACT_UNSEALED')
        path=safe_path(item.path)
        with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=item.content_sha256 or path.stat().st_size!=item.serialized_bytes:raise ValueError('ARTIFACT_HASH')

    def load(self,item):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.check(item)
        if item.value is not None:return item.value
        self.verify_file(item)
        self.read_bytes+=item.serialized_bytes
        if item.path.suffix=='.json':return json.loads(read(item.path))
        if item.format=='parquet':return pq.read_table(item.path,use_threads=False)
        with pa.memory_map(str(item.path),'r') as f:return pa.ipc.open_file(f).read_all()

    def batches(self,item,batch_size=1024):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from rcwg_full.runtime.batching import arrow_batches
        self.check(item)
        if type(batch_size) is not int or batch_size<1:raise ValueError('BATCH_SIZE')
        if item.value is not None:
            table=pa.Table.from_batches([item.value]) if isinstance(item.value,pa.RecordBatch) else item.value
            for b in arrow_batches(table,max_rows=batch_size):
                self.read_bytes+=b.nbytes;yield b
        elif item.path is not None:
            self.verify_file(item)
            if item.format=='parquet':
                for b in pq.ParquetFile(item.path).iter_batches(batch_size=batch_size,use_threads=False):self.read_bytes+=b.nbytes;yield b
            else:
                with pa.memory_map(str(item.path),'r') as f:
                    reader=pa.ipc.open_file(f)
                    for i in range(reader.num_record_batches):
                        b=reader.get_batch(i)
                        for part in arrow_batches(b,max_rows=batch_size):
                            self.read_bytes+=part.nbytes;yield part
        else:raise ValueError('ARTIFACT_UNAVAILABLE')

    def lifetime_metrics(self,at_ns=None):
        at_ns=at_ns or time.monotonic_ns();events=[]
        for b in self.buffers.values():
            if b['storage_kind']!='arrow_memory':continue
            events.extend([(b['created_ns'],1,b['capacity_bytes']),(b['released_ns'] or at_ns,0,-b['capacity_bytes'])])
        events.sort();live=peak=area=0;previous=events[0][0] if events else at_ns
        for ns,_,delta in events:area+=live*(ns-previous);live+=delta;peak=max(peak,live);previous=ns
        return {'registered_buffer_peak_bytes':peak,'registered_buffer_byte_seconds':area/1e9,
            'worker_cgroup_memory_peak':None,'worker_cgroup_status':'NOT_CALIBRATED','node_ram_status':'NOT_ATTRIBUTABLE'}
