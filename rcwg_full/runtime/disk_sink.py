"""Incremental artifact commit. Partial files remain evidence after a failed write."""
import os
from rcwg_full.evidence import sha
from rcwg_full.runtime.values import validate_arrow
from rcwg_full.runtime.batching import arrow_batches


class DiskSink:
    def __init__(self,store,typ,schema,producer,format):
        import pyarrow as pa
        import pyarrow.parquet as pq
        if format not in {'arrow_ipc','parquet'}:raise ValueError('DISK_FORMAT')
        self.store=store;self.item=store.register(None,typ,producer,storage='disk',format=format)
        self.schema=schema;self.closed=False;self.temporary=store.directory/(self.item.artifact_id+'.partial')
        self.file=self.temporary.open('xb')
        try:
            self.writer=(pq.ParquetWriter(self.file,schema,compression='NONE',use_dictionary=False,write_statistics=False)
                         if format=='parquet' else pa.ipc.new_file(self.file,schema))
        except BaseException:self.file.close();raise
        self.item.schema_hash=sha(schema.serialize().to_pybytes());self.item.logical_rows=0

    def append(self,batch):
        import pyarrow as pa
        if self.closed:raise ValueError('DISK_SINK_CLOSED')
        validate_arrow(batch,self.item.type)
        # Nullability in the actual batch must be checked before restoring the
        # compiler's canonical field ordering and nullability metadata.
        table=pa.Table.from_batches([batch]) if isinstance(batch,pa.RecordBatch) else batch
        table=table.select(self.schema.names).cast(self.schema,safe=True)
        for piece in arrow_batches(table):self.writer.write_batch(piece)
        self.item.logical_rows+=table.num_rows
        self.store._emit('disk_batch_written',{'artifact_id':self.item.artifact_id,'rows':table.num_rows,'buffer_bytes':table.nbytes})

    def finish(self):
        if self.closed:raise ValueError('DISK_SINK_CLOSED')
        try:
            self.writer.close();self.file.flush();os.fsync(self.file.fileno());self.file.close()
            self.store._commit_file(self.item,self.temporary,'parquet' if self.item.format=='parquet' else 'arrow')
            self.closed=True;return self.item
        except BaseException:
            self.abort();raise

    def abort(self):
        if self.closed:return
        self.closed=True
        try:self.writer.close()
        finally:self.file.close()
        self.store._emit('artifact_commit_failed',{'artifact_id':self.item.artifact_id,'cause':'STREAM_INCOMPLETE'})
