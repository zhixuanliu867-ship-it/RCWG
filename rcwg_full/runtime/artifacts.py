"""Actual Arrow storage and buffer leases, separate from cgroup accounting."""
from dataclasses import dataclass,field
from pathlib import Path
import os
import time
import uuid
import json
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
        self.copy_bytes=0;self.read_bytes=0

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
                            self.buffers[bid]={'buffer_id':bid,'key':key,'value':buf,'capacity_bytes':buf.size,
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
        for bid in ids:self.buffers[bid]['artifacts'].add(aid)
        self._emit('artifact_created',{'artifact_id':aid,'buffer_ids':sorted(ids),'producer':producer,'schema_hash':item.schema_hash})
        return item

    def check(self,item):
        if not isinstance(item,Artifact) or item.run_id!=self.run_id or self.artifacts.get(item.artifact_id) is not item:raise ValueError('CAPABILITY_INVALID')
        if item.release_status!='LIVE':raise ValueError('ARTIFACT_RELEASED')

    def acquire(self,item,holder):
        self.check(item)
        for bid in item.buffer_ids:self.buffers[bid]['leases'].add((item.artifact_id,holder))
        self._emit('lease_acquired',{'artifact_id':item.artifact_id,'holder':holder})

    def drop_lease(self,item,holder):
        self.check(item)
        for bid in item.buffer_ids:
            lease=(item.artifact_id,holder)
            if lease not in self.buffers[bid]['leases']:raise ValueError('LEASE_UNKNOWN')
            self.buffers[bid]['leases'].remove(lease)
        self._emit('lease_dropped',{'artifact_id':item.artifact_id,'holder':holder})

    def release(self,item):
        self.check(item)
        if any(self.buffers[bid]['leases'] for bid in item.buffer_ids):raise ValueError('RELEASE_BEFORE_LAST_USE')
        # Any still-live view is a real lifetime owner, irrespective of content hash.
        if any(self.buffers[bid]['artifacts']-{item.artifact_id} for bid in item.buffer_ids):raise ValueError('RELEASE_HAS_LIVE_ALIAS')
        for bid in item.buffer_ids:
            buf=self.buffers[bid];buf['artifacts'].discard(item.artifact_id);buf['released_ns']=time.monotonic_ns()
            self.addresses.pop(buf['key']);buf['value']=None
            self._emit('buffer_released',{'buffer_id':bid,'released_ns':buf['released_ns']})
        if item.storage=='disk' and item.path is not None:
            item.path.unlink()  # failure leaves the artifact live and recorded
        item.value=None;item.release_status='RELEASED'
        self._emit('artifact_released',{'artifact_id':item.artifact_id})

    def drop_view(self,item):
        self.check(item)
        if any((item.artifact_id,h) in b['leases'] for b in self.buffers.values() for _,h in b['leases']):raise ValueError('LIVE_VIEW_LEASE')
        for bid in item.buffer_ids:self.buffers[bid]['artifacts'].discard(item.artifact_id)
        item.value=None;item.release_status='VIEW_DROPPED'

    def seal(self,item):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.check(item)
        if item.sealed_ns is not None:return item
        path=self.directory/(item.artifact_id+'.'+('parquet' if item.format=='parquet' else 'arrow' if isinstance(item.value,(pa.Table,pa.RecordBatch)) else 'json'))
        temporary=self.directory/(item.artifact_id+'.partial')
        try:
            if isinstance(item.value,(pa.Table,pa.RecordBatch)):
                with temporary.open('xb') as f:
                    if item.format=='parquet':pq.write_table(item.value,f,compression='NONE',use_dictionary=False,write_statistics=False)
                    else:
                        with pa.ipc.new_file(f,item.value.schema) as writer:
                            writer.write_table(item.value) if isinstance(item.value,pa.Table) else writer.write_batch(item.value)
                    f.flush();os.fsync(f.fileno())
            else:write(temporary,item.value)
            raw=read(temporary);item.content_sha256=sha(raw);item.serialized_bytes=len(raw)
            if path.exists():raise ValueError('ARTIFACT_ALREADY_EXISTS')
            os.rename(temporary,path);item.path=path;item.sealed_ns=time.monotonic_ns()
            if item.storage=='disk':item.value=None
            metadata={k:v for k,v in vars(item).items() if k not in {'value','buffer_ids','path'}}
            metadata.update(buffer_ids=sorted(item.buffer_ids),filename=path.name)
            write(self.directory/(item.artifact_id+'.metadata.json'),metadata)
            self._emit('artifact_sealed',metadata)
        except BaseException as exc:
            self._emit('artifact_commit_failed',{'artifact_id':item.artifact_id,'cause':type(exc).__name__})
            raise
        return item

    def batches(self,item,batch_size=1024):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.check(item)
        if item.value is not None:
            for b in item.value.to_batches(max_chunksize=batch_size):
                self.read_bytes+=b.nbytes;yield b
        elif item.path is not None:
            if item.format=='parquet':
                for b in pq.ParquetFile(item.path).iter_batches(batch_size=batch_size,use_threads=False):self.read_bytes+=b.nbytes;yield b
            else:
                with pa.memory_map(str(item.path),'r') as f:
                    reader=pa.ipc.open_file(f)
                    for i in range(reader.num_record_batches):
                        b=reader.get_batch(i)
                        for j in range(0,b.num_rows,batch_size):
                            part=b.slice(j,batch_size);self.read_bytes+=part.nbytes;yield part
        else:raise ValueError('ARTIFACT_UNAVAILABLE')

    def lifetime_metrics(self,at_ns=None):
        at_ns=at_ns or time.monotonic_ns();events=[]
        for b in self.buffers.values():
            events.extend([(b['created_ns'],1,b['capacity_bytes']),(b['released_ns'] or at_ns,0,-b['capacity_bytes'])])
        live=peak=area=0;previous=events[0][0] if events else at_ns
        for ns,_,delta in sorted(events):area+=live*(ns-previous);live+=delta;peak=max(peak,live);previous=ns
        return {'registered_buffer_peak_bytes':peak,'registered_buffer_byte_seconds':area/1e9,
            'worker_cgroup_memory_peak':None,'worker_cgroup_status':'NOT_CALIBRATED','node_ram_status':'NOT_ATTRIBUTABLE'}
