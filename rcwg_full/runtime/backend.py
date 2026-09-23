"""Concrete offline dispatch adapters; native CPU kernels remain source-bound."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
import uuid
from rcwg_full.evidence import canonical,digest
from rcwg_full.runtime.artifacts import Artifact,ArtifactStore
from rcwg_full.runtime.streams import BoundedStream,StreamClosed,tee
from rcwg_full.runtime.scheduler import ExecutionFault
from rcwg_full.runtime.values import arrow_schema,arrow_rows,validate
from rcwg_full.runtime.batching import arrow_batches
from rcwg_full.runtime.spilled import SpilledTable,JsonResult


class Backend:
    def __init__(self,native,store,task,*,documents=None,semantic=None,result_path=None):
        import pyarrow as pa
        pa.set_cpu_count(1);pa.set_io_thread_count(1)
        self.pa=pa;self.native=native;self.store=store;self.task=task
        self.documents=documents;self.semantic=semantic;self.cache={}
        self.result_path=Path(result_path) if result_path else None

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
        validate(value,typ,self.store)
        parents=[p for p in parents if isinstance(p,Artifact) and p.release_status=='LIVE']
        return self.store.register(value,typ,producer,parents=parents,**kwargs)

    def register_item(self,item,typ,producer):
        if isinstance(item,Artifact):return item
        validate(item,typ,self.store);return self.wrap(item,typ,producer)

    async def value(self,item):
        if not isinstance(item,Artifact):return item
        self.store.check(item)
        if item.storage=='disk' and item.path is not None and item.format in {'arrow_stream','arrow_ipc','parquet'} and item.path.suffix!='.json':
            self.store.verify_file(item)
            return SpilledTable(item.path,format=item.format,verify=lambda:self.store.verify_file(item))
        value=self.store.load(item)
        validate(value,item.type,self.store)
        return value

    def size(self,item):
        value=item.value if isinstance(item,Artifact) else item
        if hasattr(value,'nbytes'):return value.nbytes
        if isinstance(value,BoundedStream):return 0
        if isinstance(value,SpilledTable):return 0
        def represent(v):
            if isinstance(v,Artifact):return {'artifact_id':v.artifact_id}
            if isinstance(v,dict):return {k:represent(x) for k,x in v.items()}
            if isinstance(v,list):return [represent(x) for x in v]
            return v
        return len(canonical(represent(value)))

    async def records(self,item):
        if isinstance(item,Artifact) and item.storage=='disk' and item.path is not None and item.format!='json_stream':
            async def disk_iterator():
                for batch in self.store.batches(item):
                    for row in batch.to_pylist():yield json.loads(canonical(row))
            return disk_iterator()
        value=await self.value(item)
        async def iterator():
            if isinstance(value,BoundedStream):
                try:
                    async for batch in value:
                        raw=await self.value(batch)
                        if isinstance(raw,(self.pa.Table,self.pa.RecordBatch)):
                            for row in raw.to_pylist():yield json.loads(canonical(row))
                        elif type(raw) is list:
                            for row in raw:yield row
                        else:yield raw
                finally:await value.cancel()
            elif isinstance(value,(self.pa.Table,self.pa.RecordBatch,SpilledTable)):
                batches=value.batches() if isinstance(value,SpilledTable) else arrow_batches(value)
                for batch in batches:
                    for row in batch.to_pylist():yield json.loads(canonical(row))
            elif type(value) is list:
                for row in value:yield row
            else:yield value
        return iterator()

    async def batches(self,item,typ):
        """No whole-stream collection; at most one conversion batch is local."""
        if isinstance(item,Artifact) and item.storage=='disk' and item.path is not None:
            for batch in self.store.batches(item):
                table=self.pa.Table.from_batches([batch])
                with self.store.transient(table,'batch-input'):yield table
            return
        value=await self.value(item);schema=arrow_schema(typ)
        def convert(raw):
            if not isinstance(raw,(self.pa.Table,self.pa.RecordBatch)):
                raw=self.pa.Table.from_pylist(arrow_rows(raw if isinstance(raw,list) else [raw],typ),schema=schema)
            for batch in arrow_batches(raw):yield self.pa.Table.from_batches([batch]).select(schema.names)
        if isinstance(value,BoundedStream):
            try:
                async for batch in value:
                    for table in convert(await self.value(batch)):
                        with self.store.transient(table,'batch-conversion'):yield table
            finally:await value.cancel()
        elif isinstance(value,SpilledTable):
            for batch in value.batches():
                for table in convert(batch):
                    with self.store.transient(table,'spill-read'):yield table
        else:
            for table in convert(value):
                with self.store.transient(table,'batch-conversion'):yield table

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
            if len(rows)>=1024:batches.extend(self.pa.Table.from_pylist(arrow_rows(rows,typ),schema=arrow_schema(typ)).to_batches());rows=[]
        if rows:batches.extend(self.pa.Table.from_pylist(arrow_rows(rows,typ),schema=arrow_schema(typ)).to_batches())
        return self.pa.Table.from_batches(batches,schema=arrow_schema(typ))

    async def predicate(self,ast,record,instance,node,scheduler):
        schema={}
        for port,t in node.get('inputs',{}).items():
            while t['kind'] in {'ArtifactRef','DatasetRef','Stream'}:t=t['item']
            if t['kind']=='Record':schema.update({k:v for k,v in t['schema'].items() if k in record})
            if port in record:schema[port]=t
        args=(ast,record,schema) if schema else (ast,record)
        return await scheduler.compute(instance,node,self.native.expression,*args)

    async def finalize(self,item,scheduler):
        value=await self.value(item)
        if isinstance(value,JsonResult):
            if self.result_path:
                import shutil,os
                with value.path.open('rb') as source,self.result_path.open('xb') as target:
                    shutil.copyfileobj(source,target,1024*1024);target.flush();os.fsync(target.fileno())
                return JsonResult(self.result_path)
            return json.loads(value.path.read_bytes())
        if self.result_path:
            await self.write_json(item,self.result_path)
            return JsonResult(self.result_path)
        if isinstance(value,SpilledTable):return [row async for row in await self.records(item)]
        if isinstance(value,BoundedStream):return [await self.finalize(x,scheduler) if isinstance(x,Artifact) else x async for x in await self.records(item)]
        if isinstance(value,(self.pa.Table,self.pa.RecordBatch)):
            return json.loads(canonical(value.to_pylist()))
        if isinstance(value,dict):return {k:await self.finalize(v,scheduler) for k,v in value.items()}
        if isinstance(value,list):return [await self.finalize(v,scheduler) for v in value]
        return value

    async def dispatch(self,node,inputs,p,instance,scheduler):
        op,impl=node['operator'],node['implementation']
        def output(port,value,parents=(),**kwargs):return {port:self.wrap(value,node['outputs'][port],instance,parents,**kwargs)}
        def observed(c):scheduler.event('kernel_observation',{'mode':self.native.mode,'counts':c,'physical_backend_id':'arrow-cpp20-full001'},instance)
        if op=='scan':
            source=await self.value(inputs['source'])
            async def producer(stream):
                if impl=='index_range':
                    if not hasattr(source,'indexed_rows'):raise ExecutionFault('INDEX_UNAVAILABLE','facility')
                    table=await scheduler.compute(instance,node,source.table)
                    indices=source.indexed_rows(p.get('predicate'));table=table.take(self.pa.array(indices,type=self.pa.int64()))
                    scheduler.event('index_read',{'rows_selected':len(indices),'index_id':source.index_id,'source_materialized':True},instance)
                    iterator=iter(table.to_batches(max_chunksize=1024))
                elif hasattr(source,'batches'):
                    selected=list(p['columns'])
                    def fields(ast):
                        if isinstance(ast,dict):
                            if 'field' in ast and ast['field'] not in selected:selected.append(ast['field'])
                            for value in ast.values():fields(value)
                        elif isinstance(ast,list):
                            for value in ast:fields(value)
                    fields(p.get('predicate'))
                    iterator=iter(source.batches(selected,expected_type=node['inputs']['source'],batch_size=min(1024,node.get('resources',{}).get('batch_rows',1024)),on_event=lambda k,v:scheduler.event(k,v,instance)))
                elif isinstance(source,self.pa.Table):iterator=iter(source.to_batches(max_chunksize=1024))
                else:raise ExecutionFault('DATASET_TABLE_REQUIRED','facility')
                def advance():
                    try:return next(iterator)
                    except StopIteration:return None
                try:
                    while (batch:=await scheduler.compute(instance,node,advance)) is not None:
                        table=self.pa.Table.from_batches([batch])
                        if 'predicate' in p:
                            table,c=await scheduler.compute(instance,node,self.native.relational,'filter','scalar',table,{'predicate':p['predicate']});observed(c)
                        for selected in arrow_batches(table.select(p['columns']),max_object_bytes=min(64*1024**2,self.task['resources']['worker_memory_limit_bytes'])):await stream.put(selected,selected.nbytes)
                finally:
                    if hasattr(iterator,'close'):iterator.close()
            return output('rows',scheduler.spawn_stream(producer,instance,holds=[inputs['source']]),parents=[inputs['source']])
        if op in {'filter','project'}:
            source_type=node['inputs'].get('rows',{})
            while source_type.get('kind') in {'ArtifactRef','DatasetRef'}:source_type=source_type['item']
            if op=='filter' and source_type.get('kind') in {'DocumentStream','ChunkStream'}:
                records=await self.value(inputs['rows'])
                table=self.pa.Table.from_pylist(arrow_rows(records,source_type),schema=arrow_schema(source_type));ordinal='_full001_source_ordinal'
                while ordinal in table.column_names:ordinal+='x'
                table=table.append_column(ordinal,self.pa.array(range(table.num_rows),type=self.pa.int64()))
                result,c=await scheduler.compute(instance,node,self.native.relational,'filter',impl,table,p);observed(c)
                return output('rows',[records[i] for i in result.column(ordinal).to_pylist()],parents=[inputs['rows']])
            if op=='project' and 'field_map' in p:
                record={k:(await self.value(inputs[v]) if node['inputs'][v]['kind'] in {'Int64','Float64','Bool','Utf8','Date','Timestamp','Nullable','Record','List'} else inputs[v]) for k,v in p['field_map'].items()}
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
                input_type=node['inputs']['rows']
                while input_type['kind'] in {'ArtifactRef','DatasetRef'}:input_type=input_type['item']
                if input_type['kind']=='PathSet' and view in {'nodes','edges'}:
                    field='node_id' if view=='nodes' else 'edge_id'
                    rows=[{'target':p['target'],field:v,'ordinal':i} for p in source for i,v in enumerate(p[view])]
                else:rows=source.get(view) if isinstance(source,dict) and view in {'nodes','edges'} else source
                if view=='ids':rows=[{'id':x['document_id'] if isinstance(x,dict) else x} for x in source]
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
                value,c=await scheduler.compute(instance,node,self.native.relational,op,impl,table,parameters);observed(c)
                if op=='project' and impl=='copy':self.store.copied(value,instance,scope='ARROW_PAYLOAD_EXPLICIT_PROJECT_COPY')
                return value
            if isinstance(source,(BoundedStream,SpilledTable)) and node['outputs']['rows']['kind']=='Stream':
                async def producer(stream):
                    try:
                        async for table in self.batches(inputs['rows'],node['inputs']['rows']):
                            result=await operation(table)
                            for b in arrow_batches(result):await stream.put(b,b.nbytes)
                    finally:
                        if isinstance(source,BoundedStream):await source.cancel()
                return output('rows',scheduler.spawn_stream(producer,instance,holds=[inputs['rows']]),parents=[inputs['rows']] if impl=='column_view' else [])
            if isinstance(source,SpilledTable) and p.get('representation') not in {'record','set'}:
                from rcwg_full.runtime.disk_sink import DiskSink
                sink=DiskSink(self.store,node['outputs']['rows'],arrow_schema(node['outputs']['rows']),instance,'arrow_ipc')
                try:
                    async for table in self.batches(inputs['rows'],node['inputs']['rows']):
                        await scheduler.compute(instance,node,sink.append,await operation(table))
                    return {'rows':await scheduler.compute(instance,node,sink.finish)}
                except BaseException:sink.abort();raise
            table=await self.table(inputs['rows'],node['inputs']['rows']);result=await operation(table)
            if p.get('representation') in {'record','set'}:result=self._representation(json.loads(canonical(result.to_pylist())),p,node['outputs']['rows'])
            return output('rows',result,parents=[inputs['rows']] if impl=='column_view' else [])
        if op in {'join','aggregate','deduplicate','sort','top_k'}:
            if (op=='aggregate' and impl=='sorted_group') or (op=='join' and impl=='sort_merge'):
                intermediates=[]
                async def sorted_input(port,fields):
                    directory=self.store.directory/('scratch-'+str(uuid.uuid4()));directory.mkdir()
                    typ=node['inputs'][port];schema=arrow_schema(typ)
                    state=await scheduler.compute(instance,node,self.native.sort_begin,schema,
                        {'keys':[{'field':name,'direction':'asc','nulls':'last'} for name in fields]},directory)
                    async for table in self.batches(inputs[port],typ):
                        await scheduler.compute(instance,node,self.native.aggregate_consume,state,table)
                    path,rows,c=await scheduler.compute(instance,node,self.native.sort_finish,state);observed(c)
                    while typ['kind'] in {'Stream','DatasetRef','ArtifactRef'}:typ=typ['item']
                    artifact=self.store.adopt_stream(path,{'kind':'Table','schema':typ['schema']},instance+':sorted-input',rows)
                    intermediates.append(artifact);return artifact.path
                directory=self.store.directory/('scratch-'+str(uuid.uuid4()));directory.mkdir()
                try:
                    if op=='aggregate':
                        source=await sorted_input('rows',p['group_by'])
                        path,rows,c=await scheduler.compute(instance,node,self.native.sorted_group,source,p,directory)
                    else:
                        left=await sorted_input('left',[k['left'] for k in p['keys']])
                        right=await sorted_input('right',[k['right'] for k in p['keys']])
                        path,rows,c=await scheduler.compute(instance,node,self.native.sorted_join,left,right,p,directory)
                    observed(c)
                    typ=node['outputs']['rows'];table_type={'kind':'Table','schema':typ['item']['schema']} if typ['kind']=='Stream' else typ
                    artifact=self.store.adopt_stream(path,table_type,instance,rows)
                finally:
                    for intermediate in intermediates:self.store.release(intermediate)
                if typ['kind']!='Stream':return {'rows':artifact}
                async def producer(stream):
                    for batch in self.store.batches(artifact):await stream.put(batch,batch.nbytes)
                scheduler.retirement_candidates[artifact.artifact_id]=artifact
                return output('rows',scheduler.spawn_stream(producer,instance,holds=[artifact]),parents=[artifact])
            if op=='top_k' and impl=='streaming_heap':
                state=await scheduler.compute(instance,node,self.native.topk_begin,arrow_schema(node['inputs']['rows']),p)
                async for table in self.batches(inputs['rows'],node['inputs']['rows']):
                    await scheduler.compute(instance,node,self.native.aggregate_consume,state,table)
                result,c=await scheduler.compute(instance,node,self.native.aggregate_finish,state);observed(c)
                return output('rows',result)
            if op=='sort' and impl=='external_merge':
                directory=self.store.directory/('scratch-'+str(uuid.uuid4()));directory.mkdir()
                state=await scheduler.compute(instance,node,self.native.sort_begin,arrow_schema(node['inputs']['rows']),p,directory)
                async for table in self.batches(inputs['rows'],node['inputs']['rows']):
                    await scheduler.compute(instance,node,self.native.aggregate_consume,state,table)
                path,rows,c=await scheduler.compute(instance,node,self.native.sort_finish,state);observed(c)
                typ=node['outputs']['rows'];table_type={'kind':'Table','schema':typ['item']['schema']} if typ['kind']=='Stream' else typ
                artifact=self.store.adopt_stream(path,table_type,instance,rows)
                if typ['kind']!='Stream':return {'rows':artifact}
                async def producer(stream):
                    for batch in self.store.batches(artifact):await stream.put(batch,batch.nbytes)
                scheduler.retirement_candidates[artifact.artifact_id]=artifact
                return output('rows',scheduler.spawn_stream(producer,instance,holds=[artifact]),parents=[artifact])
            if op=='aggregate' and impl=='hash_group':
                schema=arrow_schema(node['inputs']['rows']);state=await scheduler.compute(instance,node,self.native.aggregate_begin,schema,p)
                async def consume(batch):
                    raw=await self.value(batch)
                    table=self.pa.Table.from_batches([raw]) if isinstance(raw,self.pa.RecordBatch) else raw
                    if not isinstance(table,self.pa.Table):table=self.pa.Table.from_pylist(arrow_rows(raw if isinstance(raw,list) else [raw],node['inputs']['rows']),schema=schema)
                    await scheduler.compute(instance,node,self.native.aggregate_consume,state,table.select(schema.names))
                    scheduler.event('aggregate_batch_consumed',{'rows':table.num_rows,'bytes':table.nbytes},instance)
                async for batch in self.batches(inputs['rows'],node['inputs']['rows']):await consume(batch)
                result,c=await scheduler.compute(instance,node,self.native.aggregate_finish,state);observed(c)
                return output('rows',result)
            port='left' if op=='join' else 'rows';left=await self.table(inputs[port],node['inputs'][port])
            right=await self.table(inputs['right'],node['inputs']['right']) if op=='join' else None
            directory=self.store.directory/('scratch-'+str(uuid.uuid4()));directory.mkdir()
            result,c=await scheduler.compute(instance,node,self.native.relational,op,impl,left,p,right,directory);observed(c)
            if node['outputs']['rows']['kind']=='Stream':
                payload=self.wrap(result,{'kind':'Table','schema':node['outputs']['rows']['item']['schema']},instance+':arrow-payload')
                scheduler.retirement_candidates[payload.artifact_id]=payload
                async def producer(stream):
                    for b in arrow_batches(result):await stream.put(b,b.nbytes)
                return output('rows',scheduler.spawn_stream(producer,instance,holds=[payload]),parents=[payload])
            return output('rows',result)
        if op=='set_op':
            typ=node['inputs']['left']
            while typ['kind'] in {'ArtifactRef','DatasetRef'}:typ=typ['item']
            result,c=await scheduler.compute(instance,node,self.native.set_op,await self.value(inputs['left']),await self.value(inputs['right']),p['mode'],impl,typ.get('item'));observed(c)
            return output('items',result)
        if op.startswith('graph_'):
            graph=await self.value(inputs['graph']);seeds=[]
            for port in ['seeds','nodes','edges']:
                if port in inputs:seeds=await self.value(inputs[port])
            if op=='graph_subgraph' and impl=='edge_selected':seeds=[e['edge_id'] for e in seeds]
            caps=node.get('input_capabilities',{}).get('graph',{});params=dict(p)
            params['_graph_fields']={k:caps[k] for k in ['node_id_field','source_field','target_field'] if k in caps}
            from rcwg_full.runtime.values import native_temporal,temporal_json
            typ=node['inputs']['graph']
            while typ['kind'] in {'ArtifactRef','DatasetRef'}:typ=typ['item']
            graph={**graph,'nodes':[native_temporal(row,{'kind':'Record','schema':caps.get('node_schema',{})}) for row in graph['nodes']],
                   'edges':[native_temporal(row,{'kind':'Record','schema':typ['schema']}) for row in graph['edges']]}
            with self.store.transient(graph,instance+':graph-conversion'):
                result,c=await scheduler.compute(instance,node,self.native.graph,op,impl,graph,seeds,params)
            result=temporal_json(result);observed(c)
            port=next(iter(node['outputs']))
            return output(port,result,parents=[inputs['graph']] if op=='graph_filter' else [])
        if op in {'materialize','collect'}:
            if op=='materialize' and impl=='disk':
                from rcwg_full.runtime.disk_sink import DiskSink
                sink=DiskSink(self.store,node['outputs']['rows'],arrow_schema(node['inputs']['rows']),instance,p['format'])
                try:
                    async for batch in self.batches(inputs['rows'],node['inputs']['rows']):
                        await scheduler.compute(instance,node,sink.append,batch)
                    result=await scheduler.compute(instance,node,sink.finish)
                    return {'rows':result}
                except BaseException:sink.abort();raise
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
                streams={port:scheduler.new_stream(instance) for port in p['consumers']}
                scheduler.live_streams.extend(streams.values())
                async def distribute():
                    try:
                        async for batch in value:
                            for target in streams.values():
                                if target.closed:continue
                                delivered=batch if impl=='shared_ref' else batch.take(self.pa.array(range(batch.num_rows),type=self.pa.int64()))
                                if impl!='shared_ref':self.store.copied(delivered,instance,scope='ARROW_PAYLOAD_BROADCAST_COPY')
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
            value=await self.value(artifact)
            if isinstance(value,SpilledTable):
                if impl=='disk':
                    from rcwg_full.runtime.disk_sink import DiskSink
                    sink=DiskSink(self.store,node['outputs']['artifact'],value.schema,instance,'arrow_ipc')
                    try:
                        async for batch in self.batches(artifact,artifact.type):await scheduler.compute(instance,node,sink.append,batch)
                        result=await scheduler.compute(instance,node,sink.finish)
                    except BaseException:sink.abort();raise
                else:result=self.wrap(await self.table(artifact,artifact.type),node['outputs']['artifact'],instance)
            else:
                result=self.wrap(value,node['outputs']['artifact'],instance,parents=[artifact] if impl=='memory' else [],storage=impl)
                if impl=='disk':self.store.seal(result)
            self.store.acquire(result,'cache:'+key);self.cache[key]=result;return {'artifact':result}
        if op=='emit':
            if self.result_path:
                path=self.store.directory/(str(uuid.uuid4())+'.result.partial')
                await self.write_json(inputs['rows'],path)
                return {'result':self.store.adopt_json(path,node['outputs']['result'],instance)}
            result=await self.finalize(inputs['rows'],scheduler)
            item=self.wrap(result,node['outputs']['result'],instance);self.store.seal(item);return {'result':item}
        if op=='stats':
            from rcwg_full.runtime.probes import probe
            value=await self.value(inputs['source'])
            result=await scheduler.compute(instance,node,probe,value,impl,p,lambda k,v:scheduler.event(k,v,instance))
            return output('stats',result)
        if op in {'read_documents','text_retrieve','split_documents','gather_context','evidence_merge','evidence_validate','semantic_extract'}:
            if self.documents is None:raise ExecutionFault('DOCUMENT_ADAPTER_UNAVAILABLE','facility')
            values={k:await self.value(v) for k,v in inputs.items()}
            result=await self.documents.dispatch(op,impl,values,p,semantic=self.semantic,instance=instance,scheduler=scheduler,node=node)
            return output(next(iter(node['outputs'])),result)
        raise ExecutionFault('UNSUPPORTED_IMPLEMENTATION','facility')

    async def write_json(self,item,path):
        """Serialize a result with a bounded batch, outside any whole-table load."""
        import os
        async def sequence(values,file):
            file.write(b'[');first=True
            async for value in values:
                if not first:file.write(b',')
                first=False;await emit(value,file)
            file.write(b']')
        async def emit(value,file):
            if isinstance(value,Artifact):
                if value.storage=='disk' and value.format in {'arrow_stream','arrow_ipc','parquet'}:
                    await sequence(await self.records(value),file);return
                value=await self.value(value)
            if isinstance(value,JsonResult):
                import shutil
                with value.path.open('rb') as source:shutil.copyfileobj(source,file,1024*1024)
            elif isinstance(value,(BoundedStream,SpilledTable,self.pa.Table,self.pa.RecordBatch)):
                await sequence(await self.records(value),file)
            elif isinstance(value,dict):
                file.write(b'{')
                for index,key in enumerate(sorted(value)):
                    if index:file.write(b',')
                    file.write(canonical(key)+b':');await emit(value[key],file)
                file.write(b'}')
            elif isinstance(value,list):
                file.write(b'[')
                for index,entry in enumerate(value):
                    if index:file.write(b',')
                    await emit(entry,file)
                file.write(b']')
            else:file.write(canonical(value))
        with Path(path).open('xb') as file:
            await emit(item,file);file.write(b'\n');file.flush();os.fsync(file.fileno())

    def _representation(self,rows,params,typ):
        representation=params.get('representation','same')
        if representation=='record' or typ['kind']=='Record':
            if len(rows)!=1:raise ExecutionFault('CARDINALITY_VIOLATION')
            return rows[0]
        if representation=='set':
            result=[];seen=set()
            for row in rows:
                value=next(iter(row.values()));key=digest(value)
                if key not in seen:seen.add(key);result.append(value)
            return result
        return self.pa.Table.from_pylist(arrow_rows(rows,typ),schema=arrow_schema(typ))

    async def _copy(self,item,node,instance,scheduler):
        value=await self.value(item)
        if isinstance(value,SpilledTable):value=await self.table(item,item.type)
        if isinstance(value,self.pa.Table):
            result,c=await scheduler.compute(instance,node,self.native.relational,'project','copy',value,{'columns':value.column_names})
            self.store.copy_bytes+=result.nbytes;scheduler.event('copy',{'instrumented_copy_bytes':result.nbytes},instance);return result
        return deepcopy(value)
