"""Concrete offline dispatch adapters; native CPU kernels remain source-bound."""
import asyncio
from copy import deepcopy
from pathlib import Path
import uuid
from rcwg_full.evidence import canonical,digest
from rcwg_full.runtime.artifacts import Artifact,ArtifactStore
from rcwg_full.runtime.streams import BoundedStream,StreamClosed,tee
from rcwg_full.runtime.scheduler import ExecutionFault
from rcwg_full.runtime.values import arrow_schema,validate


class Backend:
    def __init__(self,native,store,task,*,documents=None,semantic=None):
        import pyarrow as pa
        pa.set_cpu_count(1);pa.set_io_thread_count(1)
        self.pa=pa;self.native=native;self.store=store;self.task=task
        self.documents=documents;self.semantic=semantic;self.cache={}

    def check_parameters(self,node,params):
        # Static shape was checked by the compiler; check all dynamically bound ranges.
        for b in node.get('param_bindings',[]):
            name=b['parameter'];v=params[name]
            if b['type']['kind']=='Int64':
                minimum=1 if name in {'batch_size','size','context_budget','sample_size'} else 0
                if not minimum<=v<2**63:raise ExecutionFault('PARAMETER_RANGE')
            elif not v:raise ExecutionFault('PARAMETER_RANGE')
        if node['operator']=='split_documents' and not 0<=params['overlap']<params['size']:raise ExecutionFault('PARAMETER_RANGE')

    def wrap(self,value,typ,producer,parents=(),**kwargs):
        parents=[p for p in parents if isinstance(p,Artifact) and p.release_status=='LIVE']
        return self.store.register(value,typ,producer,parents=parents,**kwargs)

    def register_item(self,item,typ,producer):
        if isinstance(item,Artifact):return item
        validate(item,typ,self.store);return self.wrap(item,typ,producer)

    async def value(self,item):
        if not isinstance(item,Artifact):return item
        self.store.check(item);return self.store.load(item)

    def size(self,item):
        value=item.value if isinstance(item,Artifact) else item
        if hasattr(value,'nbytes'):return value.nbytes
        if isinstance(value,BoundedStream):return 0
        def represent(v):
            if isinstance(v,Artifact):return {'artifact_id':v.artifact_id}
            if isinstance(v,dict):return {k:represent(x) for k,x in v.items()}
            if isinstance(v,list):return [represent(x) for x in v]
            return v
        return len(canonical(represent(value)))

    async def records(self,item):
        value=await self.value(item)
        async def iterator():
            if isinstance(value,BoundedStream):
                try:
                    async for batch in value:
                        raw=await self.value(batch)
                        if isinstance(raw,(self.pa.Table,self.pa.RecordBatch)):
                            for row in raw.to_pylist():yield row
                        elif type(raw) is list:
                            for row in raw:yield row
                        else:yield raw
                finally:await value.cancel()
            elif isinstance(value,(self.pa.Table,self.pa.RecordBatch)):
                for row in value.to_pylist():yield row
            elif type(value) is list:
                for row in value:yield row
            else:yield value
        return iterator()

    async def table(self,item,typ,limit=None):
        value=await self.value(item)
        if isinstance(value,self.pa.Table):return value
        if isinstance(value,self.pa.RecordBatch):return self.pa.Table.from_batches([value])
        batches=[];rows=[];size=0;count=0
        async for row in await self.records(item):
            count+=1
            if limit is not None and count>limit:raise ExecutionFault('COLLECT_LIMIT_EXCEEDED')
            size+=len(canonical(row))
            if size>self.task['resources']['worker_memory_limit_bytes']:raise ExecutionFault('DECLARED_OBJECT_LIMIT_EXCEEDED')
            rows.append(row)
            if len(rows)>=1024:batches.extend(self.pa.Table.from_pylist(rows,schema=arrow_schema(typ)).to_batches());rows=[]
        if rows:batches.extend(self.pa.Table.from_pylist(rows,schema=arrow_schema(typ)).to_batches())
        return self.pa.Table.from_batches(batches,schema=arrow_schema(typ))

    async def predicate(self,ast,record,instance,node,scheduler):
        return await scheduler.compute(instance,node,self.native.expression,ast,record)

    async def finalize(self,item,scheduler):
        value=await self.value(item)
        if isinstance(value,BoundedStream):return [await self.finalize(x,scheduler) if isinstance(x,Artifact) else x async for x in await self.records(item)]
        if isinstance(value,(self.pa.Table,self.pa.RecordBatch)):return value.to_pylist()
        if isinstance(value,dict):return {k:await self.finalize(v,scheduler) for k,v in value.items()}
        if isinstance(value,list):return [await self.finalize(v,scheduler) for v in value]
        return value

    async def dispatch(self,node,inputs,p,instance,scheduler):
        op,impl=node['operator'],node['implementation']
        def output(port,value,parents=(),**kwargs):return {port:self.wrap(value,node['outputs'][port],instance,parents,**kwargs)}
        def observed(c):scheduler.event('kernel_observation',{'mode':self.native.mode,'counts':c,'physical_backend_id':'arrow-cpp20-full001'},instance)
        if op=='scan':
            source=await self.value(inputs['source'])
            table=source.table() if hasattr(source,'table') else source
            if not isinstance(table,self.pa.Table):raise ExecutionFault('DATASET_TABLE_REQUIRED','facility')
            if impl=='index_range':
                if not hasattr(source,'indexed_rows'):raise ExecutionFault('INDEX_UNAVAILABLE','facility')
                indices=source.indexed_rows(p.get('predicate'));table=table.take(self.pa.array(indices,type=self.pa.int64()))
                scheduler.event('index_read',{'rows_selected':len(indices),'index_id':source.index_id},instance)
            if 'predicate' in p:
                table,c=await scheduler.compute(instance,node,self.native.relational,'filter','scalar',table,{'predicate':p['predicate']});observed(c)
            table=table.select(p['columns'])
            async def producer(stream):
                for batch in table.to_batches(max_chunksize=1024):await stream.put(batch,batch.nbytes)
            payload=self.wrap(table,node['inputs']['source']['item'],instance+':arrow-source')
            scheduler.retirement_candidates[payload.artifact_id]=payload
            stream=scheduler.spawn_stream(producer,instance,holds=[inputs['source'],payload])
            return output('rows',stream,parents=[payload])
        if op in {'filter','project'}:
            if op=='project' and 'field_map' in p:
                record={k:(await self.value(inputs[v]) if node['inputs'][v]['kind'] in {'Int64','Float64','Bool','Utf8','Nullable','Record','List'} else inputs[v]) for k,v in p['field_map'].items()}
                if impl=='copy':
                    # Copy a capability wrapper, never silently copy its referenced payload.
                    def clone(v):
                        if isinstance(v,Artifact):
                            raw=canonical({'artifact_id':v.artifact_id,'run_id':v.run_id,'type':v.type})
                            scheduler.event('handle_wrapper_copy',{'handle_serialized_bytes':len(raw),'payload_copy_bytes':0},instance)
                            return self.wrap(v.value,v.type,instance+':handle-copy',parents=[v])
                        if isinstance(v,dict):return {k:clone(x) for k,x in v.items()}
                        if isinstance(v,list):return [clone(x) for x in v]
                        return deepcopy(v)
                    record=clone(record)
                return output('rows',record,parents=list(inputs.values()))
            source=await self.value(inputs['rows'])
            if op=='project' and (p.get('source_view','rows')!='rows' or isinstance(source,dict)):
                view=p.get('source_view','rows')
                rows=source.get(view) if view in {'nodes','edges'} else source
                if view=='ids':rows=[{'id':x} for x in source]
                if isinstance(rows,dict):rows=[rows]
                projected=[]
                for row in rows:
                    record={k:row[k] for k in p.get('columns',[])}
                    for k,ast in p.get('expressions',{}).items():record[k]=await self.predicate(ast,row,instance,node,scheduler)
                    projected.append(record)
                return output('rows',self._representation(projected,p,node['outputs']['rows']),parents=[inputs['rows']] if impl=='column_view' else [])
            async def operation(table):
                parameters=dict(p)
                if op=='project' and 'expressions' in p:
                    typ=node['outputs']['rows'];typ=typ['item'] if typ['kind']=='Stream' else typ
                    parameters['_field_types']=typ['schema']
                value,c=await scheduler.compute(instance,node,self.native.relational,op,impl,table,parameters);observed(c);return value
            if isinstance(source,BoundedStream) and node['outputs']['rows']['kind']=='Stream':
                async def producer(stream):
                    try:
                        async for batch in source:
                            table=self.pa.Table.from_batches([batch]) if isinstance(batch,self.pa.RecordBatch) else batch
                            result=await operation(table)
                            for b in result.to_batches(max_chunksize=1024):await stream.put(b,b.nbytes)
                    finally:await source.cancel()
                return output('rows',scheduler.spawn_stream(producer,instance,holds=[inputs['rows']]),parents=[inputs['rows']] if impl=='column_view' else [])
            table=await self.table(inputs['rows'],node['inputs']['rows']);result=await operation(table)
            if p.get('representation') in {'record','set'}:result=self._representation(result.to_pylist(),p,node['outputs']['rows'])
            return output('rows',result,parents=[inputs['rows']] if impl=='column_view' else [])
        if op in {'join','aggregate','deduplicate','sort','top_k'}:
            port='left' if op=='join' else 'rows';left=await self.table(inputs[port],node['inputs'][port])
            right=await self.table(inputs['right'],node['inputs']['right']) if op=='join' else None
            directory=self.store.directory/('scratch-'+str(uuid.uuid4()));directory.mkdir()
            result,c=await scheduler.compute(instance,node,self.native.relational,op,impl,left,p,right,directory);observed(c)
            if node['outputs']['rows']['kind']=='Stream':
                payload=self.wrap(result,{'kind':'Table','schema':node['outputs']['rows']['item']['schema']},instance+':arrow-payload')
                scheduler.retirement_candidates[payload.artifact_id]=payload
                async def producer(stream):
                    for b in result.to_batches(max_chunksize=1024):await stream.put(b,b.nbytes)
                return output('rows',scheduler.spawn_stream(producer,instance,holds=[payload]),parents=[payload])
            return output('rows',result)
        if op=='set_op':
            result,c=await scheduler.compute(instance,node,self.native.set_op,await self.value(inputs['left']),await self.value(inputs['right']),p['mode'],impl);observed(c)
            return output('items',result)
        if op.startswith('graph_'):
            graph=await self.value(inputs['graph']);seeds=[]
            for port in ['seeds','nodes','edges']:
                if port in inputs:seeds=await self.value(inputs[port])
            if op=='graph_subgraph' and impl=='edge_selected':seeds=[e['edge_id'] for e in seeds]
            result,c=await scheduler.compute(instance,node,self.native.graph,op,impl,graph,seeds,p);observed(c)
            port=next(iter(node['outputs']))
            return output(port,result,parents=[inputs['graph']] if op=='graph_filter' else [])
        if op in {'materialize','collect'}:
            result=await self.table(inputs['rows'],node['inputs']['rows'],p['limit'] if op=='collect' else None)
            out=output('rows',result,storage=impl if op=='materialize' else 'memory',format=p.get('format','arrow_ipc'))
            if op=='materialize' and impl=='disk':self.store.seal(out['rows'])
            return out
        if op=='stream_read':
            artifact=inputs['artifact']
            async def producer(stream):
                holder=instance+':stream';self.store.acquire(artifact,holder)
                try:
                    for batch in self.store.batches(artifact,p['batch_size']):await stream.put(batch,batch.nbytes)
                finally:self.store.drop_lease(artifact,holder)
            return output('rows',scheduler.spawn_stream(producer,instance,holds=[artifact]),parents=[artifact])
        if op=='broadcast':
            artifact=inputs['artifact'];value=await self.value(artifact)
            if isinstance(value,BoundedStream):
                streams={port:BoundedStream(on_event=lambda k,v:scheduler.event(k,v,instance)) for port in p['consumers']}
                scheduler.live_streams.extend(streams.values())
                async def distribute():
                    try:
                        async for batch in value:
                            for target in streams.values():
                                if target.closed:continue
                                delivered=batch if impl=='shared_ref' else batch.take(self.pa.array(range(batch.num_rows),type=self.pa.int64()))
                                await target.put(delivered,delivered.nbytes)
                    except BaseException as exc:
                        for target in streams.values():await target.finish(exc)
                        raise
                    finally:
                        await value.cancel()
                        for target in streams.values():await target.finish(target.error)
                scheduler.background.add(asyncio.create_task(distribute()))
                return {port:self.wrap(s,node['outputs'][port],instance,parents=[artifact] if impl=='shared_ref' else []) for port,s in streams.items()}
            return {port:self.wrap(value if impl=='shared_ref' else await self._copy(artifact,node,instance,scheduler),node['outputs'][port],instance,parents=[artifact] if impl=='shared_ref' else []) for port in p['consumers']}
        if op=='release':self.store.release(inputs['artifact']);return output('done',{'released':inputs['artifact'].artifact_id})
        if op=='cache':
            artifact=inputs['artifact'];self.store.seal(artifact)
            key=digest({'run_id':self.store.run_id,'content':artifact.content_sha256,'schema':artifact.schema_hash,'key_fields':p['key_fields'],'storage':impl})
            existing=self.cache.get(key)
            if existing is not None:self.store.check(existing);return {'artifact':existing}
            result=self.wrap(await self.value(artifact),node['outputs']['artifact'],instance,parents=[artifact] if impl=='memory' else [],storage=impl)
            if impl=='disk':self.store.seal(result)
            self.store.acquire(result,'cache:'+key);self.cache[key]=result;return {'artifact':result}
        if op=='emit':
            result=await self.finalize(inputs['rows'],scheduler)
            item=self.wrap(result,node['outputs']['result'],instance);self.store.seal(item);return {'result':item}
        if op=='stats':
            value=await self.value(inputs['source']);table=value.table() if hasattr(value,'table') else value
            result={'rows':table.num_rows,'bytes':table.nbytes,'fields':p['fields'],'kind':impl}
            if impl=='sample':result['sample']=table.select(p['fields']).slice(0,p['sample_size']).to_pylist()
            return output('stats',result)
        if op in {'read_documents','text_retrieve','split_documents','gather_context','evidence_merge','evidence_validate','semantic_extract'}:
            if self.documents is None:raise ExecutionFault('DOCUMENT_ADAPTER_UNAVAILABLE','facility')
            values={k:await self.value(v) for k,v in inputs.items()}
            result=await self.documents.dispatch(op,impl,values,p,semantic=self.semantic,instance=instance,scheduler=scheduler,node=node)
            return output(next(iter(node['outputs'])),result)
        raise ExecutionFault('UNSUPPORTED_IMPLEMENTATION','facility')

    def _representation(self,rows,params,typ):
        representation=params.get('representation','same')
        if representation=='record' or typ['kind']=='Record':
            if len(rows)!=1:raise ExecutionFault('CARDINALITY_EXACTLY_ONE')
            return rows[0]
        if representation=='set':
            result=[];seen=set()
            for row in rows:
                value=next(iter(row.values()));key=digest(value)
                if key not in seen:seen.add(key);result.append(value)
            return result
        return self.pa.Table.from_pylist(rows,schema=arrow_schema(typ))

    async def _copy(self,item,node,instance,scheduler):
        value=await self.value(item)
        if isinstance(value,self.pa.Table):
            result,c=await scheduler.compute(instance,node,self.native.relational,'project','copy',value,{'columns':value.column_names})
            self.store.copy_bytes+=result.nbytes;scheduler.event('copy',{'instrumented_copy_bytes':result.nbytes},instance);return result
        return deepcopy(value)
