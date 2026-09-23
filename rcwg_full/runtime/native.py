"""Load only a source-bound native build; importing never builds or installs."""
from pathlib import Path
import ctypes
import importlib.util
import importlib.metadata
import json
import platform
import sysconfig
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
        self.manifest=manifest;self.mode=mode

    def relational(self,op,impl,data,params,right=None,directory=''):
        table,counts=self.module.relational(op,impl,data,right,canonical(params).decode(),str(directory))
        return table,json.loads(counts)

    def graph(self,op,impl,graph,seeds,params):
        result,counts=self.module.graph(op,impl,canonical(graph).decode(),canonical(seeds).decode(),canonical(params).decode())
        return json.loads(result),json.loads(counts)

    def set_op(self,left,right,mode,impl,item_type=None):
        from rcwg_full.runtime.values import native_temporal,temporal_json
        if item_type:
            left=[native_temporal(v,item_type) for v in left];right=[native_temporal(v,item_type) for v in right]
        result,counts=self.module.set_op(canonical(left).decode(),canonical(right).decode(),mode,impl)
        return temporal_json(json.loads(result)),json.loads(counts)

    def expression(self,ast,record,schema=None):
        from rcwg_full.runtime.values import native_temporal,temporal_json
        if schema:record=native_temporal(record,{'kind':'Record','schema':schema})
        return temporal_json(json.loads(self.module.expression(canonical(ast).decode(),canonical(record).decode())))

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

    def bm25_prepare(self,documents):return self.module.Bm25Index(canonical(documents).decode())

    def bm25_query(self,index,terms,limit,offset=0):
        result,counts=index.query(canonical(terms).decode(),limit,offset);return json.loads(result),json.loads(counts)

    def dense(self,docs,query,params):
        result,counts=self.module.dense(canonical(docs).decode(),canonical(query).decode(),canonical(params).decode())
        return json.loads(result),json.loads(counts)
