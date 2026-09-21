"""Trusted local manifest resolver. WorkIR receives only symbolic source IDs."""
from pathlib import Path
import bisect
import json
from rcwg_full.evidence import read,sha,digest,safe_path


class DataSource:
    def __init__(self,root,entry):self.root=root;self.entry=entry;self.index_id=entry.get('indexes',[{}])[0].get('id') if entry.get('indexes') else None
    def file(self,record):
        relative=Path(record['path'])
        if relative.is_absolute() or any(p in {'..','.'} for p in relative.parts):raise ValueError('DATA_PATH_INVALID')
        path=safe_path(self.root/relative)
        if not path.is_relative_to(self.root):raise ValueError('DATA_PATH_ESCAPE')
        raw=read(path)
        if sha(raw)!=record['sha256']:raise ValueError('DATA_FILE_HASH')
        return raw
    def value(self):
        if self.entry['format'] in {'arrow_ipc','parquet'}:return self.table()
        files=self.entry['physical_files']
        if len(files)!=1:raise ValueError('JSON_SOURCE_FILES')
        return json.loads(self.file(files[0]))
    def table(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        tables=[]
        for record in self.entry['physical_files']:
            source=pa.BufferReader(self.file(record))
            tables.append(pq.read_table(source,use_threads=False) if self.entry['format']=='parquet' else pa.ipc.open_file(source).read_all())
        result=pa.concat_tables(tables)
        if result.num_rows!=self.entry['logical_rows']:raise ValueError('DATA_ROW_COUNT')
        return result
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
    def resolve(self,ident):
        if ident not in self.sources:raise ValueError('DATA_SOURCE_UNREGISTERED')
        return self.sources[ident]
    def bindings(self):
        return [{'id':e['source_id'],'revision':e['revision'],'content_sha256':e['content_sha256'],'schema_hash':e['schema_hash']} for e in self.manifest['sources']]
