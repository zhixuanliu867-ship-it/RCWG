"""Load only a source-bound native build; importing never builds or installs."""
from pathlib import Path
import ctypes
import importlib.util
import importlib.metadata
import json
import platform
import sysconfig
from contextlib import contextmanager,ExitStack
from contextvars import ContextVar
from rcwg_full.evidence import ROOT,read,sha,canonical,safe_path


class Native:
    def __init__(self,directory,mode='performance'):
        if mode not in {'performance','diagnostic'}:raise ValueError('NATIVE_MODE')
        directory=safe_path(directory);manifest=json.loads(read(directory/'BUILD.json'))
        if manifest['status']!='BUILD_PASS':raise ValueError('BUILD_NOT_PASSED')
        if platform.python_version()!=manifest['python'] or sysconfig.get_config_var('SOABI')!=manifest['soabi']:raise ValueError('BUILD_ABI_MISMATCH')
        for path,expected in manifest['source'].items():
            if path.startswith('native_full001/') or path in {'native001/json.hpp','environments/full001/requirements.lock','scripts/build_full001.py'}:
                if sha(read(ROOT/path))!=expected:raise ValueError('BUILD_SOURCE_MISMATCH:'+path)
        import pyarrow as pa
        import pyarrow.compute
        if importlib.metadata.version('pyarrow')!='21.0.0':raise ValueError('DEPENDENCY_VERSION_MISMATCH')
        lib=Path(pa.get_library_dirs()[0]);self.libraries=[]
        for name,expected in manifest['dependencies'].items():
            path=lib/name
            if sha(read(path))!=expected:raise ValueError('BUILD_DEPENDENCY_MISMATCH:'+name)
            self.libraries.append(ctypes.CDLL(str(path),mode=ctypes.RTLD_GLOBAL))
        binary=manifest['binaries'][mode]
        if Path(binary['name']).name!=binary['name']:raise ValueError('BUILD_BINARY_PATH')
        path=directory/binary['name']
        if sha(read(path))!=binary['sha256']:raise ValueError('BUILD_BINARY_HASH')
        spec=importlib.util.spec_from_file_location('_full001_'+mode,path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        if self.module.diagnostic!=(mode=='diagnostic'):raise ValueError('BUILD_COUNTER_MODE')
        self.manifest=manifest;self.mode=mode;self._allocation_store=ContextVar('full001_native_allocations',default=None)

    @property
    def allocation_store(self):return self._allocation_store.get()

    @contextmanager
    def allocation_context(self,store):
        token=self._allocation_store.set(store)
        try:yield
        finally:self._allocation_store.reset(token)

    @contextmanager
    def codec(self):
        """Observe real boundary objects/copies, without estimating C++ heap/RSS."""
        with ExitStack() as stack:
            def observe(value,label):
                if self.allocation_store is not None:
                    stack.enter_context(self.allocation_store.transient(value,'native-json:'+label))
                return value
            def encode(value):
                raw=observe(canonical(value),'utf8');text=observe(raw.decode(),'text')
                if self.allocation_store is not None:self.allocation_store.copied(raw,'native-json',scope='JSON_UTF8_ENCODING_BYTES')
                return text
            def decode(raw):
                observe(raw,'returned-text')
                return observe(json.loads(raw),'decoded-objects')
            yield encode,decode

    def relational(self,op,impl,data,params,right=None,directory=''):
        if (op,impl)==('top_k','streaming_heap'):
            from .batching import arrow_batches
            import pyarrow as pa
            state=self.topk_begin(data.schema,params)
            for batch in arrow_batches(data):state.consume(pa.Table.from_batches([batch]))
            return self.aggregate_finish(state)
        if (op,impl) in {('sort','external_merge'),('aggregate','sorted_group'),('join','sort_merge')}:
            from .batching import arrow_batches
            from .spilled import SpilledTable
            import pyarrow as pa
            import tempfile
            import uuid
            owner=tempfile.TemporaryDirectory(prefix='full001-native-') if not directory else None
            root=Path(owner.name if owner else directory);counts={};intermediates=[]
            def add(values):
                for k,v in values.items():counts[k]=max(counts.get(k,0),v) if k.startswith('peak_') else counts.get(k,0)+v
            def sort(table,keys):
                scratch=root/('sort-'+str(uuid.uuid4()));scratch.mkdir()
                state=self.sort_begin(table.schema,{'keys':keys},scratch)
                for batch in arrow_batches(table):state.consume(pa.Table.from_batches([batch]))
                path,rows,c=self.sort_finish(state);add(c);return path,rows
            try:
                if op=='sort':path,rows=sort(data,params['keys'])
                elif op=='aggregate':
                    inp,_=sort(data,[{'field':k,'direction':'asc','nulls':'last'} for k in params['group_by']]);intermediates.append(Path(inp))
                    path,rows,c=self.sorted_group(inp,params,root);add(c)
                else:
                    left,_=sort(data,[{'field':k['left'],'direction':'asc','nulls':'last'} for k in params['keys']]);intermediates.append(Path(left))
                    other,_=sort(right,[{'field':k['right'],'direction':'asc','nulls':'last'} for k in params['keys']]);intermediates.append(Path(other))
                    path,rows,c=self.sorted_join(left,other,params,root);add(c)
                return SpilledTable(path,owner=owner,rows=rows),counts
            finally:
                for path in intermediates:path.unlink()
        table,counts=self.module.relational(op,impl,data,right,canonical(params).decode(),str(directory))
        return table,json.loads(counts)

    def graph(self,op,impl,graph,seeds,params):
        with self.codec() as (encode,decode):
            result,counts=self.module.graph(op,impl,encode(graph),encode(seeds),encode(params))
            return decode(result),json.loads(counts)

    def set_op(self,left,right,mode,impl,item_type=None):
        from rcwg_full.runtime.values import native_temporal,temporal_json
        if item_type:
            left=[native_temporal(v,item_type) for v in left];right=[native_temporal(v,item_type) for v in right]
        with self.codec() as (encode,decode):
            result,counts=self.module.set_op(encode(left),encode(right),mode,impl)
            return temporal_json(decode(result)),json.loads(counts)

    def expression(self,ast,record,schema=None):
        from rcwg_full.runtime.values import native_temporal,temporal_json
        if schema:record=native_temporal(record,{'kind':'Record','schema':schema})
        with self.codec() as (encode,decode):return temporal_json(decode(self.module.expression(encode(ast),encode(record))))

    def aggregate_begin(self,schema,params):
        import pyarrow as pa
        return self.module.StreamAggregate(pa.Table.from_batches([],schema=schema),canonical(params).decode())

    def aggregate_consume(self,state,batch):state.consume(batch)

    def aggregate_finish(self,state):
        result,counts=state.finish();return result,json.loads(counts)

    def topk_begin(self,schema,params):
        import pyarrow as pa
        return self.module.StreamTopK(pa.Table.from_batches([],schema=schema),canonical(params).decode())

    def sort_begin(self,schema,params,directory):
        import pyarrow as pa
        return self.module.StreamSort(pa.Table.from_batches([],schema=schema),canonical(params).decode(),str(directory))

    def sort_finish(self,state):
        path,rows,counts=state.finish();return path,rows,json.loads(counts)

    def sorted_group(self,path,params,directory):
        path,rows,counts=self.module.sorted_group_file(str(path),canonical(params).decode(),str(directory))
        return path,rows,json.loads(counts)

    def sorted_join(self,left,right,params,directory):
        path,rows,counts=self.module.sorted_join_files(str(left),str(right),canonical(params).decode(),str(directory))
        return path,rows,json.loads(counts)

    def bm25_prepare(self,documents):
        with self.codec() as (encode,decode):return self.module.Bm25Index(encode(documents))

    def bm25_query(self,index,terms,limit,offset=0):
        with self.codec() as (encode,decode):
            result,counts=index.query(encode(terms),limit,offset);return decode(result),json.loads(counts)

    def dense(self,docs,query,params):
        with self.codec() as (encode,decode):
            result,counts=self.module.dense(encode(docs),encode(query),encode(params))
            return decode(result),json.loads(counts)
