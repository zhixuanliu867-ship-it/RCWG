"""Trusted local manifest resolver. WorkIR receives only symbolic source IDs."""
from pathlib import Path
import bisect
import json
import hashlib
import os
import stat
from rcwg_full.evidence import read,sha,digest,safe_path


class DataSource:
    def __init__(self,root,entry):self.root=root;self.entry=entry;self.index_id=entry.get('indexes',[{}])[0].get('id') if entry.get('indexes') else None
    def path(self,record):
        relative=Path(record['path'])
        if relative.is_absolute() or any(p in {'..','.'} for p in relative.parts):raise ValueError('DATA_PATH_INVALID')
        path=safe_path(self.root/relative)
        if not path.is_relative_to(self.root):raise ValueError('DATA_PATH_ESCAPE')
        return path
    def file(self,record):
        raw=read(self.path(record))
        if sha(raw)!=record['sha256']:raise ValueError('DATA_FILE_HASH')
        return raw
    def value(self):
        if self.entry['format'] in {'arrow_ipc','parquet'}:return self.table()
        files=self.entry['physical_files']
        if len(files)!=1:raise ValueError('JSON_SOURCE_FILES')
        return json.loads(self.file(files[0]))
    def table(self):
        import pyarrow as pa
        return pa.Table.from_batches(list(self.batches()))
    def batches(self,columns=None,*,expected_type=None,batch_size=1024,on_event=None):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from rcwg_full.runtime.values import validate_arrow,arrow_schema
        from rcwg_full.runtime.batching import arrow_batches
        if type(batch_size) is not int or batch_size<=0:raise ValueError('BATCH_SIZE')
        expected_type=expected_type or getattr(self,'expected_type',None)
        observed=on_event or (lambda *args:None);total=0;emitted=False;output_schema=None
        for record in self.entry['physical_files']:
            fd=os.open(self.path(record),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd,'rb') as raw:
                before=os.fstat(raw.fileno())
                if not stat.S_ISREG(before.st_mode):raise ValueError('REGULAR_FILE_REQUIRED')
                checksum=hashlib.sha256();verified=0
                while chunk:=raw.read(1024*1024):checksum.update(chunk);verified+=len(chunk)
                if checksum.hexdigest()!=record['sha256'] or verified!=record.get('bytes',verified):raise ValueError('DATA_FILE_HASH')
                observed('source_integrity_read',{'bytes':verified,'path':record['path']});raw.seek(0)
                source=pa.PythonFile(raw,mode='r')
                if self.entry['format']=='parquet':
                    reader=pq.ParquetFile(source);schema=reader.schema_arrow
                    get_batches=lambda:reader.iter_batches(batch_size=batch_size,columns=columns,use_threads=False)
                elif self.entry['format']=='arrow_ipc':
                    full=pa.ipc.open_file(source);schema=full.schema
                    fields=list(range(len(schema))) if columns is None else [schema.get_field_index(name) for name in columns]
                    if any(i<0 for i in fields):raise ValueError('DATA_SCHEMA_FIELDS')
                    source.seek(0);reader=pa.ipc.open_file(source,options=pa.ipc.IpcReadOptions(included_fields=fields,use_threads=False))
                    get_batches=lambda:(reader.get_batch(i) for i in range(reader.num_record_batches))
                else:raise ValueError('TABLE_FORMAT_REQUIRED')
                if expected_type is not None:
                    expected=arrow_schema(expected_type)
                    if set(schema.names)!=set(expected.names) or len(schema)!=len(expected):raise ValueError('DATA_SCHEMA_FIELDS')
                    if any(not schema.field(name).type.equals(expected.field(name).type) for name in expected.names):raise ValueError('DATA_SCHEMA_TYPE')
                selected=schema.names if columns is None else columns;output_schema=pa.schema([schema.field(name) for name in selected])
                for batch in get_batches():
                    batch=batch.select(selected)
                    if expected_type is not None:
                        typ=expected_type
                        while typ['kind'] in {'DatasetRef','ArtifactRef','Stream'}:typ=typ['item']
                        validate_arrow(batch,{'kind':'Table','schema':{name:typ['schema'][name] for name in selected}})
                    total+=batch.num_rows
                    for piece in arrow_batches(batch,max_rows=batch_size):
                        emitted=True
                        observed('source_batch',{'rows':piece.num_rows,'buffer_bytes':piece.nbytes,'columns':selected});yield piece
                after=os.fstat(raw.fileno())
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('DATA_CHANGED_DURING_READ')
        if total!=self.entry['logical_rows']:raise ValueError('DATA_ROW_COUNT')
        if not emitted:
            if output_schema is None:raise ValueError('DATA_SOURCE_FILES')
            yield pa.RecordBatch.from_arrays([pa.array([],type=f.type) for f in output_schema],schema=output_schema)
    def indexed_rows(self,predicate):
        indexes=self.entry.get('indexes',[])
        if not indexes:raise ValueError('INDEX_UNAVAILABLE')
        index=indexes[0];payload=json.loads(self.file(index))
        if payload['source_content_sha256']!=self.entry['content_sha256']:raise ValueError('INDEX_SOURCE_BINDING')
        values=payload['values'];ordinals=payload['ordinals']
        if len(values)!=len(ordinals) or values!=sorted(values) or len(set(ordinals))!=len(ordinals):raise ValueError('INDEX_INVALID')
        def bounds(ast):
            if ast is None:return 0,len(values),True
            if ast.get('op')=='and':
                ranges=[bounds(arg) for arg in ast['args']];return max(a for a,b,n in ranges),min(b for a,b,n in ranges),all(n for a,b,n in ranges)
            field=ast.get('left',{}).get('field');value=ast.get('right',{}).get('literal')
            if field!=payload['field'] or value is None:return 0,len(values),True
            lo=bisect.bisect_left(values,value);hi=bisect.bisect_right(values,value)
            return {'eq':(lo,hi,False),'ge':(lo,len(values),False),'gt':(hi,len(values),False),'le':(0,hi,False),'lt':(0,lo,False)}.get(ast.get('op'),(0,len(values),True))
        a,b,include_null=bounds(predicate)
        # Range lookup changes access cost, never first/last source ordinal semantics.
        return sorted(ordinals[a:max(a,b)]+(payload.get('null_ordinals',[]) if include_null else []))


class DataCatalog:
    def __init__(self,path):
        path=safe_path(path);self.root=path.parent;self.manifest=json.loads(read(path));self.sources={}
        for entry in self.manifest['sources']:
            ident=entry['source_id']
            if ident in self.sources:raise ValueError('DATA_SOURCE_DUPLICATE')
            self.sources[ident]=DataSource(self.root,entry)
    def bind(self,task):
        from rcwg_full.compiler.public_task import validate_public_task
        from rcwg_full.compiler.typesystem import type_json
        checked=validate_public_task(task);expected={e['id']:e for e in checked['source_manifest']};public_descriptors={d['id']:d for d in checked['normalized_task']['datasets']}
        if set(expected)!=set(self.sources):raise ValueError('DATA_SOURCE_SET_MISMATCH')
        for ident,source in self.sources.items():
            actual=source.entry;public=expected[ident]
            if (actual['revision'],actual['schema_hash'],actual['content_sha256'],actual['kind'])!=(public['revision'],public['schema_hash'],public['data_sha256'],public['kind']):raise ValueError('DATA_PUBLIC_BINDING_MISMATCH')
            physical=digest([{k:r[k] for k in ['sha256','bytes']} for r in actual['physical_files']])
            if physical!=actual['content_sha256']:raise ValueError('DATA_CONTENT_MANIFEST_MISMATCH')
            source.expected_type=type_json(checked['input_types'][ident])
            source.public=public_descriptors[ident]
        return self
    def resolve(self,ident):
        if ident not in self.sources:raise ValueError('DATA_SOURCE_UNREGISTERED')
        return self.sources[ident]
    def bindings(self):
        return [{'id':e['source_id'],'revision':e['revision'],'content_sha256':e['content_sha256'],'schema_hash':e['schema_hash']} for e in self.manifest['sources']]
