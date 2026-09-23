"""F4 fixed-capacity builders and bounded reference definitions.

Metadata construction never allocates a formal object. Actual formal writes
require a trusted admission callback for the exact immutable build request.
"""
from copy import deepcopy
from pathlib import Path
import json,math,os,random
from rcwg_full.evidence import canonical,digest,write,read,source_hashes,exclusive_directory
from rcwg_full.compiler import FullCompiler
from .capacity import parameter_table
from .stream_templates import f4
from .stream_prepare import prepare_streams


def definition(template,base,condition,*,fixture=False):
    p=next((r for r in parameter_table() if r['template_id']==template and r['family']=='F4'),None)
    if p is None:raise ValueError('FORMAL_STREAM_TEMPLATE')
    d=f4(template,base,condition);number=int(template[-2:]);profile='formal_builder_fixture_v1' if fixture else 'formal_candidate_v1'
    seed=int(digest({'namespace':'FULL001_F4_FIXTURE_1' if fixture else p['namespace'],'template':template,'base':base})[:16],16)
    parameters=deepcopy(p['C1' if condition=='C1' else 'C0'])
    if fixture:parameters['object_target_bytes']=max(16384 if number==12 else 4096,p['row_width_candidate_bytes']*17)*(2 if condition=='C1' else 1)
    width=p['row_width_candidate_bytes'];payload_width=width-28
    # Arrow: three Int64 arrays, one offsets buffer per Utf8 array and packed
    # Bool bits. Per-batch offsets/bit padding only increase actual payload.
    target=parameters['object_target_bytes'];n=math.ceil(target/(width+1/8))
    parameters.update(rows=n,payload_utf8_bytes_per_row=payload_width,row_width_candidate_bytes=width)
    revision=profile+'-logical-1';task=deepcopy(d['task']);plan=deepcopy(d['plan'])
    def replace(value):
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        if isinstance(value,list):return [replace(v) for v in value]
        return revision if value=='engineering-logical-v1' else value
    task=replace(task)
    task['resources'].update(cpu_slots=p['cpu_slots'],worker_memory_limit_bytes=p['worker_ram_C2_bytes'] if condition=='C2' else p['worker_ram_C0_C1_C3_bytes'])
    task['notes']=profile.upper()+'; FULL001_F4_BOUNDED_REFERENCE_1; formal_frozen=false; capacity and reference feasibility require admitted native execution.'
    for source in task['datasets']:
        source.update(revision=revision,schema_source='full001-formal-stream-1')
        if source['id']!='dataset:weights':source['stats']['row_count']=n
        source['stats'].update(estimated_row_bytes=width,estimate_source='predeclared_capacity_candidate_not_measured_physical_bytes')
    nodes=[]
    for node in plan['nodes']:
        if node['operator']=='map':
            # The task prescribes values and ordinal order. Vectorized projects
            # preserve both without generating one dynamic node per input row.
            children=node['regions']['body']['nodes'];previous=node['inputs']['rows']
            for index,child in enumerate(children):
                ident=node['id'] if index==len(children)-1 else node['id']+'_'+str(index)
                params=deepcopy(child['params']);params.pop('representation',None)
                nodes.append({'id':ident,'operator':'project','implementation':'column_view','inputs':{'rows':previous},
                              'params':params,'outputs':{'rows':'Stream[Record]'}});previous=ident+'.rows'
        elif number==10 and node['operator']=='collect':
            nodes.append({**node,'operator':'materialize','implementation':'disk','params':{'format':'arrow_ipc'},'storage':'disk'})
        else:
            if node['operator']=='scan':node['resources']={'batch_rows':1024}
            if node['operator']=='stream_read':node['params']['batch_size']=1024
            if number==12 and node['operator']=='loop':
                node['params']['condition']={'op':'and','args':[node['params']['condition'],
                    {'op':'lt','left':{'field':'iterations'},'right':{'literal':16}}]}
            nodes.append(node)
    plan['nodes']=nodes
    if number==12:
        task['instruction']+=' 正式构建器明确停止规则：完成16轮或原谓词为false即返回当前状态；不要求 remaining 在16轮内归零。'
    def records(alias):
        if alias=='weights':yield from d['rows']['weights'];return
        rng=random.Random(seed)
        for i in range(n):
            amount=rng.randrange(-70,300)
            payload=(f'{base}-{i}-{rng.randrange(99999):05d}-'+('x'*payload_width))[:payload_width]
            yield {'id':i,'group_id':i%7,'amount':amount if alias=='records' else amount*3+11,
                   'eligible':i%3!=1,'payload':payload}
    return {'task':task,'plan':plan,'profile':profile,'seed':seed,'template_id':template,'base_id':base,'condition':condition,
            'comparison':d['comparison'],'parameter_hash':p['parameter_hash'],'data_parameters':parameters,
            'sources':{s['id']:(lambda alias=s['id'].removeprefix('dataset:'):records(alias)) for s in task['datasets']}}


def build_request(template,base,condition):
    d=definition(template,base,condition)
    return {'revision':'FULL001_FORMAL_STREAM_BUILD_REQUEST_1','task_id':d['task']['task_id'],
        'profile':d['profile'],'source_hash':digest(source_hashes()),'parameter_hash':d['parameter_hash'],
        'data_parameters':d['data_parameters'],'task_hash':digest(d['task']),'plan_hash':digest(d['plan']),
        'action':'BUILD_GENERATED_DATA_AND_PRIVATE_STREAM_ORACLE','native_execution':False,'paid_calls':0,'formal_freeze':False}


def build_formal(template,base,condition,directory,*,host_admit=None):
    request=build_request(template,base,condition)
    if not callable(host_admit) or host_admit(deepcopy(request)) is not True:raise PermissionError('FORMAL_BUILD_HOST_ADMISSION_REQUIRED')
    if request!=build_request(template,base,condition):raise ValueError('BUILD_SOURCE_CHANGED')
    return _build(definition(template,base,condition),directory,request=request)


def build_fixture(template,base,condition,directory):
    return _build(definition(template,base,condition,fixture=True),directory,request=None)


def oracle(catalog,number,base,directory):
    """Independent scalar sums and sequential output from persisted input bytes."""
    private=exclusive_directory(directory);out=private/'verifier.json';groups={};count=total=other=0;payload_bytes={}
    def rows(alias):
        for batch in catalog.resolve('dataset:'+alias).batches():
            for row in batch.to_pylist():yield row
    for alias in ['records','other']:
        if 'dataset:'+alias not in catalog.sources:continue
        payload_bytes[alias]=0
        for batch in catalog.resolve('dataset:'+alias).batches():payload_bytes[alias]+=batch.nbytes
    for row in rows('records'):
        if number in {6,9} and not row['eligible']:continue
        count+=1;total+=row['amount'];g=row['group_id'];groups[g]=groups.get(g,0)+row['amount']
    grouped=[{'group_id':g,'total':v} for g,v in sorted(groups.items())]
    if number in {1,6,7}:expected={'sum':{'total':total},'count':{'count':count}}
    elif number==2:expected={'a':{'total':total},'b':{'total':total}}
    elif number in {3,4,5}:expected=grouped
    elif number==9:
        multiplicities={}
        for row in rows('weights'):multiplicities[row['g']]=multiplicities.get(row['g'],0)+1
        expected={'original':grouped,'joined':[{'group_id':g,'total':v*multiplicities[g]} for g,v in sorted(groups.items()) if multiplicities.get(g)]}
    elif number==11:expected={'a':{'total':total},'b':{'total':sum(r['amount'] for r in rows('other'))}}
    elif number==12:
        iterations=min(16,(count+15)//16) if base!=0 else 0
        expected={'remaining':count-16*iterations,'iterations':iterations,'active':base!=0}
    else:expected=None
    comparison='ordered' if number==8 else 'bag' if number in {3,4,5} else 'record'
    with out.open('xb') as file:
        file.write(b'{"comparison":'+canonical(comparison)+b',"expected":')
        def sequence():
            file.write(b'[')
            for index,row in enumerate(rows('records')):
                if index:file.write(b',')
                file.write(canonical({'id':row['id'],'value':row['amount']*2}))
            file.write(b']')
        if number==8:sequence()
        elif number==10:
            file.write(b'{"fast":');sequence();file.write(b',"slow":');sequence();file.write(b'}')
        else:file.write(canonical(expected))
        file.write(b',"formal_frozen":false}\n');file.flush();os.fsync(file.fileno())
    return out,{'algorithm':'independent Python scalar reduction / sequential mapping from persisted Arrow',
                'source_logical_hashes':{k:v.entry['logical_content_sha256'] for k,v in catalog.sources.items()},
                'actual_source_arrow_payload_bytes':payload_bytes,'oracle_peak_ram_bytes':None,'formal_frozen':False}


def _build(d,directory,*,request):
    from rcwg_full.runtime.catalog import DataCatalog
    from rcwg_full.reference.candidates import candidates
    task,manifest,path=prepare_streams(d['task'],{k:v() for k,v in d['sources'].items()},directory,profile=d['profile'],
        provenance={'kind':'deterministic_generated_stream','parameter_hash':d['parameter_hash']},
        batch_rows=31 if d['profile']=='formal_builder_fixture_v1' else 1024,
        fragment_rows=(7 if d['profile']=='formal_builder_fixture_v1' else 4093) if d['condition']=='C3' else None)
    catalog=DataCatalog(path).bind(task);logical=catalog.audit()
    private=path.parent.with_name(path.parent.name+'-private')
    verifier,evidence=oracle(catalog,int(d['template_id'][-2:]),d['base_id'],private)
    if any(size<d['data_parameters']['object_target_bytes'] for size in evidence['actual_source_arrow_payload_bytes'].values()):raise ValueError('ACTUAL_OBJECT_TARGET_NOT_REACHED')
    compiled=FullCompiler().compile(task,d['plan'])
    proof={'status':compiled['status'],'diagnostics':compiled['diagnostics'],'task_hash':digest(task),'plan_hash':digest(d['plan']),
           'native_execution_status':'NOT_RUN','formal_reference_feasible':None,'reference_revision':'FULL001_F4_BOUNDED_REFERENCE_1'}
    write(private/'oracle_proof.json',evidence);write(path.parent/'reference_plan.json',d['plan'])
    write(path.parent/'representation_proof.json',proof);write(path.parent/'candidate_definitions.json',candidates(task,d['plan']))
    write(path.parent/'condition_invariants.json',{'condition':d['condition'],'c1_axis':'object_bytes','logical_hashes':logical,'formal_frozen':False})
    build={'profile':d['profile'],'parameter_hash':d['parameter_hash'],'data_parameters':d['data_parameters'],
        'compile_status':compiled['status'],'source_audit':'PASS','oracle_proof_hash':digest(evidence),
        'actual_source_arrow_payload_bytes':evidence['actual_source_arrow_payload_bytes'],
        'host_admission_request_hash':digest(request) if request else None,'native_execution_performed':False,'formal_frozen':False,'formal_ready':False}
    write(path.parent/'build_manifest.json',build)
    return {'task':task,'plan':d['plan'],'manifest':manifest,'manifest_path':path,'private_verifier':verifier,
            'private_directory':private,'proof':proof,'build':build}
