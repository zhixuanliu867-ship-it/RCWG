"""DAG and lexical region scheduling with one run-wide admission controller."""
import asyncio
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import time
from collections import Counter
from rcwg_full.runtime.streams import CpuAdmission,BoundedStream,bounded_map
from rcwg_full.runtime.artifacts import Artifact


class ExecutionFault(RuntimeError):
    def __init__(self,code,attribution='plan'):super().__init__(code);self.code=code;self.attribution=attribution


class Scheduler:
    def __init__(self,report,task,externals,backend,journal,*,execution_profile=None):
        if report['status']!='IR_VALIDATED':raise ExecutionFault('COMPILED_PLAN_REQUIRED','facility')
        self.report=report;self.task=task;self.externals=externals;self.backend=backend;self.journal=journal
        self.nodes=report['typed_graph']['nodes'];self.scopes={}
        for n in self.nodes:self.scopes.setdefault(n['scope'],[]).append(n)
        self.admission=CpuAdmission(task['resources']['cpu_slots'],report['original_plan'].get('limits',{}).get('max_node_instances',4096))
        from rcwg_full.runtime.scheduling_profile import validate_profile
        self.execution_profile=validate_profile(task,execution_profile)
        parallelism=self.execution_profile['cpu_kernel_concurrency'] if self.execution_profile else self.admission.slots
        self.kernel_gate=asyncio.Semaphore(parallelism)
        self.pool=ThreadPoolExecutor(max_workers=parallelism,thread_name_prefix='full001-cpu')
        if self.execution_profile:self.event('scheduling_profile',{'profile':self.execution_profile,'public_cpu_budget':self.admission.slots})
        self.background=set();self.live_streams=[];self.timings=[];self.reference_roots={};self.retirement_candidates={}

    def retire(self):
        """Destroy unreachable wrappers, retaining explicit captures, cache and streams."""
        store=self.backend.store
        def nested(value,seen=None):
            seen=set() if seen is None else seen
            if id(value) in seen:return set()
            seen.add(id(value))
            if isinstance(value,Artifact):return {value.artifact_id}
            if isinstance(value,dict):return set().union(*(nested(v,seen) for v in value.values())) if value else set()
            if isinstance(value,list):return set().union(*(nested(v,seen) for v in value)) if value else set()
            return set()
        protected={v.artifact_id for v in self.reference_roots.values() if isinstance(v,Artifact)}
        changed=True
        while changed:
            changed=False
            captured=set().union(*(nested(v.value) for v in store.artifacts.values() if v.release_status=='LIVE')) if store.artifacts else set()
            for aid,value in list(self.retirement_candidates.items()):
                if value.release_status!='LIVE':del self.retirement_candidates[aid];continue
                stream=value.value if isinstance(value.value,BoundedStream) else None
                if aid in protected or aid in captured or store.leases[aid] or (stream is not None and (not stream.closed or stream.queue)):continue
                # Sealed objects own the backing file. Retire their dependent
                # views first; explicit release still rejects live aliases.
                if value.path is not None and any(store.buffers[b]['artifacts']-{aid} or store.buffers[b]['leases'] for b in value.buffer_ids):continue
                store.drop_view(value);del self.retirement_candidates[aid];changed=True

    def event(self,kind,payload,instance=None,status='OBSERVED'):
        return self.journal.append(kind,payload,node_instance=instance,status=status)

    async def compute(self,instance,node,fn,*args):
        self.event('node_waiting_cpu',{'blocked_reason':'CPU_PERMIT'},instance)
        async with self.kernel_gate,self.admission.acquire(node.get('resources',{}).get('cpu_slots',1)):
            self.event('cpu_permit_acquired',{'resource_ready_ns':time.monotonic_ns()},instance)
            future=asyncio.get_running_loop().run_in_executor(self.pool,fn,*args)
            try:return await asyncio.shield(future)
            except asyncio.CancelledError:
                # Do not release a permit while the native function still runs.
                # The external supervisor deadline is authoritative for a hang.
                await asyncio.shield(future);raise
            finally:self.event('cpu_permit_released',{},instance)

    def spawn_stream(self,producer,instance,holds=()):
        stream=BoundedStream(max_object_bytes=min(64*1024*1024,self.task['resources']['worker_memory_limit_bytes']),on_event=lambda k,p:self.event(k,p,instance))
        self.live_streams.append(stream)
        holder=instance+':producer:'+str(len(self.live_streams))
        held={v.artifact_id:v for v in holds if isinstance(v,Artifact)}
        for value in held.values():self.backend.store.acquire(value,holder)
        async def run():
            try:await producer(stream)
            except BaseException as exc:await stream.finish(exc);raise
            else:await stream.finish()
            finally:
                for value in held.values():self.backend.store.drop_lease(value,holder)
                self.retire()
        task=asyncio.create_task(run());self.background.add(task)
        return stream

    async def run(self):
        try:
            out=await self.scope('root','root',{}, {'result':self.report['typed_graph']['result']['reference']})
            result=await self.backend.finalize(out['result'],self)
            # Unconsumed streams are cancelled explicitly; producers cannot hang finalization.
            for stream in self.live_streams:
                if not stream.started:await stream.cancel()
            if self.background:await asyncio.gather(*self.background)
            return result
        finally:
            for stream in self.live_streams:await stream.cancel()
            for task in self.background:
                if not task.done():task.cancel()
            if self.background:await asyncio.gather(*self.background,return_exceptions=True)
            self.pool.shutdown(wait=True,cancel_futures=True)

    async def scope(self,scope,instance_prefix,bound,yields):
        nodes=self.scopes.get(scope,[]);values={};pending={n['logical_id']:n for n in nodes};running={};completed=set()
        def resolve(ref):
            if ref.startswith('$input.'):return self.externals[ref[7:]]
            if ref.startswith('$bound.'):return bound[ref[7:]]
            name,port=ref.split('.');return values[name][port]
        def references(node):
            refs=set(node['input_references'].values())|{b['ref'] for b in node.get('param_bindings',[])}
            for region in node['regions'].values():refs|={r for r in region['bindings'].values() if r not in {'$item','$state'}}
            return refs
        dependencies={n['logical_id']:{r.split('.')[0] for r in references(n) if not r.startswith('$')}|set(n['after']) for n in nodes}
        remaining=Counter(ref for n in nodes for ref in references(n));remaining.update(yields.values())
        for ref in remaining:
            if ref.startswith('$'):self.reference_roots[(instance_prefix,ref)]=resolve(ref)
        try:
            while pending or running:
                ready=sorted((n for k,n in pending.items() if dependencies[k]<=completed),key=lambda n:n['serialization_position'])
                for node in ready:
                    name=node['logical_id'];del pending[name]
                    ordinal=self.admission.admit_instance();instance=instance_prefix+'/'+name+'#'+str(ordinal)
                    ready_ns=time.monotonic_ns();self.event('node_ready',{'ready_ns':ready_ns,'serialization_position':node['serialization_position']},instance)
                    inputs={p:resolve(r) for p,r in node['input_references'].items()};params=deepcopy(node['params'])
                    for b in node.get('param_bindings',[]):
                        value=await self.backend.value(resolve(b['ref']))
                        if 'field' in b:value=value[b['field']]
                        expected=b['type']['kind']
                        if (expected=='Int64' and type(value) is not int) or (expected=='Utf8' and type(value) is not str):raise ExecutionFault('PARAMETER_TYPE')
                        params[b['parameter']]=value
                    self.backend.check_parameters(node,params)
                    captured={r:resolve(r) for r in references(node)}
                    async def execute(node=node,inputs=inputs,params=params,instance=instance,captured=captured,ready_ns=ready_ns):
                        holders=[]
                        if node['operator']!='release':
                            for value in {id(v):v for v in captured.values()}.values():
                                if isinstance(value,Artifact):self.backend.store.acquire(value,instance);holders.append(value)
                        start=time.monotonic_ns();self.event('node_started',{'start_ns':start,'operator':node['operator'],'implementation':node['implementation']},instance)
                        try:
                            if node['operator'] in {'map','branch','loop'}:result=await self.control(node,inputs,params,captured,instance)
                            else:result=await self.backend.dispatch(node,inputs,params,instance,self)
                            self.event('node_finished',{'finish_ns':time.monotonic_ns(),'operator':node['operator'],'implementation':node['implementation']},instance,'COMPLETED')
                            return result
                        except BaseException as exc:self.event('node_failed',{'cause':getattr(exc,'code',type(exc).__name__)},instance,'FAILED');raise
                        finally:
                            for value in holders:
                                if value.release_status=='LIVE':self.backend.store.drop_lease(value,instance)
                    future=asyncio.create_task(execute());running[future]=name
                if not running:raise ExecutionFault('SCHEDULER_DEPENDENCY_DEADLOCK','facility')
                done,_=await asyncio.wait(running,return_when=asyncio.FIRST_COMPLETED)
                for future in sorted(done,key=lambda t:next(n['serialization_position'] for n in nodes if n['logical_id']==running[t])):
                    name=running.pop(future);values[name]=future.result();completed.add(name)
                    for port,value in values[name].items():
                        ref=name+'.'+port
                        if remaining[ref]:self.reference_roots[(instance_prefix,ref)]=value
                        elif isinstance(value,Artifact):self.retirement_candidates[value.artifact_id]=value
                    for ref in references(next(n for n in nodes if n['logical_id']==name)):
                        remaining[ref]-=1
                        if not remaining[ref]:
                            value=resolve(ref);self.reference_roots.pop((instance_prefix,ref),None)
                            if isinstance(value,Artifact):self.retirement_candidates[value.artifact_id]=value
                    self.retire()
            return {port:resolve(ref) for port,ref in yields.items()}
        finally:
            for future in running:future.cancel()
            await asyncio.gather(*running,return_exceptions=True)
            for key in list(self.reference_roots):
                if key[0]==instance_prefix:self.reference_roots.pop(key)

    async def control(self,node,inputs,params,captured,instance):
        async def region(label,special,suffix):
            r=node['regions'][label];bound={alias:special[ref] if ref in special else captured[ref] for alias,ref in r['bindings'].items()}
            return await self.scope(r['scope'],instance+':'+suffix,bound,r['yield'])
        op=node['operator']
        if op=='branch':
            record={k:await self.backend.value(v) for k,v in inputs.items()}
            selected=await self.backend.predicate(params['predicate'],record,instance,node,self)
            if type(selected) is not bool:raise ExecutionFault('BRANCH_PREDICATE_UNKNOWN')
            label='then' if selected else 'else';other='else' if selected else 'then'
            self.event('region_selection',{'selected':label,'not_selected':other},instance)
            for skipped in self.scopes.get(node['regions'][other]['scope'],[]):self.event('node_not_selected',{'logical_node':skipped['id']},instance,'NOT_SELECTED')
            return await region(label,{},label)
        if op=='loop':
            state=inputs['state'];iterations=0
            while True:
                value=await self.backend.value(state);record={k:await self.backend.value(v) for k,v in inputs.items()};record['state']=value
                if type(value) is dict:record.update(value)
                keep=await self.backend.predicate(params['condition'],record,instance,node,self)
                if type(keep) is not bool:raise ExecutionFault('LOOP_PREDICATE_UNKNOWN')
                self.event('loop_condition',{'iteration':iterations,'continue':keep},instance)
                if not keep:return {'state':state}
                if iterations>=params['max_iterations']:raise ExecutionFault('LOOP_LIMIT_REACHED')
                state=(await region('body',{'$state':state},'iteration-'+str(iterations)))['state'];iterations+=1
        async def producer(stream):
            source=await self.backend.records(inputs['rows'])
            index=0
            async def item_body(item):
                nonlocal index
                ordinal=index;index+=1
                wrapped=self.backend.register_item(item,node['inputs']['rows']['item'],instance)
                return (await region('body',{'$item':wrapped},'item-'+str(ordinal)))['rows']
            parallelism=node.get('resources',{}).get('max_parallelism',1)
            if self.execution_profile:parallelism=min(parallelism,self.execution_profile['map_parallelism'])
            async for result in bounded_map(source,item_body,parallelism=parallelism,admission=self.admission):
                await stream.put(result,self.backend.size(result))
        stream=self.spawn_stream(producer,instance,holds=list(captured.values()))
        return {'rows':self.backend.wrap(stream,node['outputs']['rows'],instance,parents=list(inputs.values()))}
