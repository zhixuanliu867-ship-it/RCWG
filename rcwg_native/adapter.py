"""Public WorkIR admission and owner path binding; never reads dataset rows."""
from copy import deepcopy
from pathlib import Path
from rcwg_spec.compiler import validate_workflow
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.typesystem import row_schema,unwrap_ref
from rcwg_exec.runner import preflight
from .evidence import no_symlink,run_id

def lower(task,plan,*,locations,allowed_root,ident,mode='diagnostic',max_rows=100000):
    task,plan=deepcopy(task),deepcopy(plan)
    compiled=validate_workflow(task,plan)
    if compiled['status']!='IR_VALIDATED':return {'status':compiled['status'],'compiler':compiled,'execution_started':False}
    gate=preflight(task,plan,compiled)
    def gap(code):return {'status':'UNSUPPORTED_IMPLEMENTATION','attribution':'facility','reason':code,'compiler':compiled,'execution_started':False,'formal_ready':False}
    if gate['status']!='REFERENCE_PROFILE_READY':return gap(gate.get('gaps'))
    if task['resources'].get('cpu_slots')!=1:return gap('SINGLE_COMPUTE_THREAD_ONLY')
    if type(max_rows) is not int or not 1<=max_rows<=1000000:raise ValueError('MATERIALIZATION_CAP_INVALID')
    if mode not in {'diagnostic','performance'}:raise ValueError('MODE_INVALID')
    checked=validate_public_task(task)
    sources={s['id']:s for s in checked['source_manifest']}
    if set(sources)!=set(locations) or len(sources)!=1:return gap('ONE_OWNER_REGISTERED_SOURCE_REQUIRED')
    source_id=next(iter(sources));source=sources[source_id]
    typ=unwrap_ref(checked['input_types'][source_id])
    if typ.kind!='Table':return gap('TABLE_ONLY')
    schema={}
    for key,t in row_schema(typ,'').items():
        nullable=t.kind=='Nullable';base=t.item if nullable else t
        if base.kind not in {'Bool','Int64','Float64','Utf8'}:return gap('DATA_TYPE_PROFILE_GAP')
        schema[key]={'kind':base.kind,'nullable':nullable}
    root=no_symlink(allowed_root).resolve(strict=True);path=no_symlink(locations[source_id])
    if not path.is_relative_to(root):raise ValueError('SOURCE_OUTSIDE_OWNER_ROOT')
    if not source.get('data_sha256') or not source.get('revision'):return gap('SOURCE_IDENTITY_REQUIRED')
    nodes={n['id']:n for n in plan['nodes']};chain=[]
    for name in gate['chain']:
        n=nodes[name]
        chain.append({'id':n['id'],'operator':n['operator'],'implementation':n['implementation'],'params':deepcopy(n['params']),'batch_rows':n.get('resources',{}).get('batch_rows',128)})
    if chain[0]['operator']!='scan' or chain[-1]['operator']!='emit':return gap('SCAN_EMIT_CHAIN_REQUIRED')
    public=next(s for s in task['datasets'] if s['id']==source_id)
    request={'revision':'NATIVE001_REQUEST_V1','run_id':run_id(ident),'mode':mode,'nodes':chain,
             'source':{'id':source_id,'revision':source['revision'],'path':str(path),'sha256':source['data_sha256'],'schema_hash':source['schema_hash'],'schema':schema,'row_count':public.get('stats',{}).get('row_count')},
             'max_materialized_rows':max_rows}
    return {'status':'NATIVE_PROFILE_READY','request':request,'compiler':compiled,'formal_ready':False}
