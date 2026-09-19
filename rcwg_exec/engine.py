"""Actual serial-pull kernels shared by reference and supervised runners."""
from __future__ import annotations
from copy import deepcopy
import time
from . import PROFILE
from .errors import ExecFault
from .kernels import RowFrame,ProjectedRow,filter_rows,filter_batch_rows,project_rows,select_topk

class ClockControl:
    def __init__(self, seconds):
        self.start=time.perf_counter_ns()
        self.deadline=self.start+int(seconds*1e9)
    def tick(self):
        if time.perf_counter_ns()>self.deadline:
            raise ExecFault('WALL_TIMEOUT','budget')


def execute_chain(task,plan,*,registry,compiled,store,execution_key,manifest_hash,
                  max_materialized_rows,emit):
    counters={n['id']:{} for n in plan['nodes']};states={};ports={};nodes={n['id']:n for n in plan['nodes']}
    control=ClockControl(task['resources']['wall_timeout_s']);cpu0=time.process_time_ns();artifact=None
    emit('run_started','RUNNING',{'profile':PROFILE,'scope':'engineering_only','manifest_hash':manifest_hash})
    def node_event(name,kind,status):
        emit(kind,status,{'node_instance_id':'root/'+name+'#0','operator':nodes[name]['operator'],
                         'implementation':nodes[name]['implementation'],'counters':counters[name]})
    def wrapped(name,factory):
        states[name]='READY';node_event(name,'node_ready','READY')
        def consume():
            states[name]='RUNNING';node_event(name,'node_started','RUNNING')
            try:
                for frame in factory():
                    control.tick();counters[name]['rows_yielded']=counters[name].get('rows_yielded',0)+1
                    yield frame
            except BaseException:
                states[name]='FAILED';node_event(name,'node_finished','FAILED');raise
            else:
                states[name]='COMPLETED';node_event(name,'node_finished','COMPLETED')
        return consume()
    def get(ref):
        if ref.startswith('$input.'):return plan['external_inputs'][ref[7:]]
        if ref in ports:return ports[ref]
        name,port=ref.split('.');node=nodes[name];op=node['operator'];impl=node['implementation'];p=node['params'];c=counters[name]
        node_event(name,'node_queued','QUEUED')
        inp=get(next(iter(node['inputs'].values())))
        if op=='scan':
            def factory():
                stream=registry.frames(inp,c,control.tick)
                if 'predicate' in p:stream=filter_rows(stream,p['predicate'],c,control.tick)
                for f in stream:yield RowFrame(ProjectedRow(f.values,p['columns']),f.ordinal)
                emit('artifact_read','COMPLETED',{'source_id':inp,'read_bytes':c.get('source_read_bytes',0),
                                                'byte_scope':'jsonl_application_read','eof_verified':True})
            result=wrapped(name,factory)
        elif op in ('filter','project'):
            def factory():
                if op=='filter':
                    return (filter_batch_rows(iter(inp),p['predicate'],c,control.tick,batch_rows=node.get('resources',{}).get('batch_rows',128))
                            if impl=='vectorized' else filter_rows(iter(inp),p['predicate'],c,control.tick))
                return project_rows(iter(inp),p['columns'],impl,c,control.tick)
            stream=wrapped(name,factory)
            result=list(stream) if isinstance(inp,list) else stream
        else:
            states[name]='READY';node_event(name,'node_ready','READY');states[name]='RUNNING';node_event(name,'node_started','RUNNING')
            try:
                if op=='top_k':result=select_topk(iter(inp),p['k'],p['keys'],impl,c,control.tick,max_materialized_rows=max_materialized_rows)
                elif op=='emit':result=list(inp);c['rows_received']=len(result)
                else:raise ExecFault('KERNEL_GAP')
                control.tick()
            except BaseException:
                states[name]='FAILED';node_event(name,'node_finished','FAILED');raise
            states[name]='COMPLETED';node_event(name,'node_finished','COMPLETED')
        ports[ref]=result
        return result
    terminal='COMPLETED';failure=None;run_status='EXECUTED'
    try:
        result=list(get(plan['result']));control.tick()
        if len(result)>max_materialized_rows:raise ExecFault('REFERENCE_MATERIALIZATION_CAP')
        if set(states)!=set(nodes) or any(s!='COMPLETED' for s in states.values()):raise ExecFault('NODE_COMPLETION_INCOMPLETE')
        artifact=store.artifact(result,producer=plan['result'],source_refs=sorted(registry.entries),
                                type_label=compiled['typed_graph']['result']['type']['kind'],execution_key=execution_key)
        emit('artifact_created','SEALED',{'artifact_id':artifact['artifact_id'],
             'content_sha256':artifact['content_sha256'],'serialized_bytes':artifact['serialized_bytes'],'rows':len(result)})
        control.tick()
    except ExecFault as exc:
        failure={'code':exc.code,'attribution':exc.attribution}
        terminal='TIMEOUT' if exc.attribution=='budget' else 'MODEL_FAILURE' if exc.attribution=='plan' else 'INFRA_FAILURE'
    except MemoryError:
        # A Python MemoryError does not attest that the task's cgroup limit fired.
        terminal='INFRA_FAILURE';failure={'code':'UNISOLATED_MEMORY_ERROR','attribution':'facility'}
    except (OSError,ValueError,KeyError,TypeError,RecursionError) as exc:
        terminal='INFRA_FAILURE';failure={'code':'EXECUTION_INTERNAL_ERROR','attribution':'facility','exception_type':type(exc).__name__}
    finally:
        for value in ports.values():
            if hasattr(value,'close'):
                try:value.close()
                except Exception:pass
    elapsed=time.perf_counter_ns()-control.start;cpu=time.process_time_ns()-cpu0
    if terminal=='COMPLETED' and elapsed>int(task['resources']['wall_timeout_s']*1e9):
        terminal='TIMEOUT';failure={'code':'WALL_TIMEOUT','attribution':'budget'}
    emit('run_finished',terminal,{'failure':failure,'elapsed_ns':elapsed,'completed_wall_ns':elapsed if terminal=='COMPLETED' else None})
    return {'terminal_status':terminal,'failure':failure,'artifact':artifact,
            'elapsed_ns':elapsed,'process_cpu_ns':cpu,'node_counters':counters,'node_states':states}
