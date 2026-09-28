"""Fixed-scale F3 recipes; streaming sources and independent disk SQL gold."""
from copy import deepcopy
import json,math
from rcwg_full.evidence import digest,write,source_hashes
from rcwg_full.compiler import FullCompiler
from .capacity import parameter_table
from .graph_templates import f3
from .json_stream import JsonRows
from .stream_prepare import prepare_streams


def definition(template,base,condition,*,fixture=False):
    p=next((r for r in parameter_table() if r['template_id']==template and r['family']=='F3'),None)
    if p is None:raise ValueError('FORMAL_GRAPH_TEMPLATE')
    d=f3(template,base,condition);number=int(template[-2:]);profile='formal_builder_fixture_v1' if fixture else 'formal_candidate_v1'
    parameters=deepcopy(p['C1' if condition=='C1' else 'C0'])
    if fixture:parameters['nodes']=83 if condition=='C1' else 43
    n=parameters['nodes'];e=(n*(n-1)+127)//128 if number==11 else n*8;parameters['edges_upper']=e
    seed=int(digest({'namespace':'FULL001_F3_FIXTURE_1' if fixture else p['namespace'],'template':template,'base':base})[:16],16)
    revision=profile+'-graph-1';domain=profile+'-graph-'+template
    def replace(value):
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        if isinstance(value,list):return [replace(v) for v in value]
        return revision if value=='engineering-graph-v1' else domain if value=='controlled-graph-'+template else value
    task=replace(deepcopy(d['task']));plan=replace(deepcopy(d['plan']))
    def nodes():
        for i in range(n):yield {'node_id':i,'eligible':i%4!=0,'value':(seed+7919*i)%1000,'label':f'节点{base}·{i}'}
    def edges():
        space=(n-1)*(n-2);stride=137
        while math.gcd(stride,space)!=1:stride+=2
        for i in range(e):
            if number==11:
                ordinal=(seed+i*stride)%space;a,b=divmod(ordinal,n-2);b+=b>=a
            else:
                a=i%(n-1);b=(a+1+i//(n-1))%(n-1)
                if i==n-1:a,b=0,1  # a distinct parallel edge; final node stays isolated
            yield {'edge_id':i,'src':a,'dst':b,'type':'allowed' if i%3 else 'other','time':i,
                   'weight':float(1+(seed+31*i)%5) if number in {3,11} else 1.}
    graph={'domain':domain,'revision':revision,'directed':True,'nodes':JsonRows(nodes,n),'edges':JsonRows(edges,e),
           'edge_index':JsonRows(lambda:iter(range(e)),e)}
    seeds=[0,n-3] if number==6 else [n-3] if number==5 else [0]
    targets=[0,n-2,n-1] if number==5 else [2,n//2-1,n-1]
    sources={'dataset:graph':graph,'dataset:seeds':seeds};selection=None
    for node in plan['nodes']:
        if node['operator']=='graph_shortest_path':node['params']['target']=targets
    if number in {2,3,5,12}:task['instruction']=task['instruction'].split(' targets=')[0]+' targets='+json.dumps(targets)
    if number==8:
        selection=[0,1,2,n-1] if base%2==0 else list(__import__('itertools').islice(edges(),2))
        sources['dataset:selection']=selection
    if number==9:
        def mappings():
            for i in range(n):
                for j in range(2 if i%4==0 else 1):yield {'node_id':i,'document_id':f'doc-{base}-{i*3+j}','source_revision':revision}
        sources['dataset:node_doc']=JsonRows(mappings,n+(n+3)//4)
    if number==10:sources['dataset:query_union']=[0,1,2,3]
    if number==12:
        sources['dataset:attributes']=JsonRows(lambda:({'attribute_node_id':r['node_id'],'value':r['value'],'source_revision':revision} for r in nodes()),n)
    for public in task['datasets']:
        public['revision']=revision;public['schema_source']='full001-formal-graph-1'
        if public['kind']=='graph':public['stats'].update(node_count=n,edge_count=e)
        elif public['kind']=='table':public['stats']['row_count']=sources[public['id']].count
        elif public['kind']=='node_set':public['stats']['item_count']=len(sources[public['id']])
    task['resources'].update(cpu_slots=p['cpu_slots'],worker_memory_limit_bytes=p['worker_ram_C2_bytes'] if condition=='C2' else p['worker_ram_C0_C1_C3_bytes'])
    task['notes']=profile.upper()+'; fixed capacity, no implicit shrink; native reference feasibility pending admitted host evidence.'
    return {'task':task,'plan':plan,'sources':sources,'profile':profile,'seed':seed,'template_id':template,
            'base_id':base,'condition':condition,'parameter_hash':p['parameter_hash'],'data_parameters':parameters,
            'oracle_context':{'number':number,'domain':domain,'revision':revision,'seeds':seeds,'targets':targets,
                              'mode':'induced' if base%2==0 else 'edge_selected','selection':selection}}


def build_request(template,base,condition):
    d=definition(template,base,condition)
    return {'revision':'FULL001_FORMAL_GRAPH_BUILD_REQUEST_1','task_id':d['task']['task_id'],
        'profile':d['profile'],'source_hash':digest(source_hashes()),'parameter_hash':d['parameter_hash'],
        'data_parameters':d['data_parameters'],'task_hash':digest(d['task']),'plan_hash':digest(d['plan']),
        'action':'BUILD_GENERATED_GRAPH_AND_PRIVATE_SQL_ORACLE','native_execution':False,'paid_calls':0,'formal_freeze':False}


def build_formal(template,base,condition,directory,*,host_admit=None):
    request=build_request(template,base,condition)
    if not callable(host_admit) or host_admit(deepcopy(request)) is not True:raise PermissionError('FORMAL_BUILD_HOST_ADMISSION_REQUIRED')
    if request!=build_request(template,base,condition):raise ValueError('BUILD_SOURCE_CHANGED')
    return _build(definition(template,base,condition),directory,request=request)


def build_fixture(template,base,condition,directory):
    return _build(definition(template,base,condition,fixture=True),directory,request=None)


def _build(d,directory,*,request):
    from rcwg_full.runtime.catalog import DataCatalog
    from rcwg_full.verification.graph_sql import build_recipe
    from rcwg_full.reference.candidates import candidates
    task,manifest,path=prepare_streams(d['task'],d['sources'],directory,profile=d['profile'],
        provenance={'kind':'deterministic_generated_graph','parameter_hash':d['parameter_hash']},
        batch_rows=31 if d['profile']=='formal_builder_fixture_v1' else 1024,
        fragment_rows=(7 if d['profile']=='formal_builder_fixture_v1' else 4093) if d['condition']=='C3' else None)
    private=path.parent.with_name(path.parent.name+'-private')
    verifier,evidence=build_recipe(d['sources'],d['oracle_context'],manifest,private)
    # Fixtures also independently reread every persisted source with the runtime
    # validator. Formal scale remains subject to explicit host/capacity evidence.
    catalog=DataCatalog(path).bind(task)
    audited=catalog.audit() if d['profile']=='formal_builder_fixture_v1' else None
    compiled=FullCompiler().compile(task,d['plan'])
    proof={'status':compiled['status'],'diagnostics':compiled['diagnostics'],'task_hash':digest(task),'plan_hash':digest(d['plan']),
           'native_execution_status':'NOT_RUN','formal_reference_feasible':None}
    write(path.parent/'reference_plan.json',d['plan']);write(path.parent/'representation_proof.json',proof)
    write(path.parent/'candidate_definitions.json',candidates(task,d['plan']))
    write(path.parent/'condition_invariants.json',{'condition':d['condition'],'c1_axis':'node_count',
        'logical_hashes':audited or {s['source_id']:s['logical_content_sha256'] for s in manifest['sources']},'formal_frozen':False})
    build={'profile':d['profile'],'parameter_hash':d['parameter_hash'],'data_parameters':d['data_parameters'],
        'compile_status':compiled['status'],'independent_runtime_source_audit':'PASS' if audited else 'PENDING_ADMITTED_FORMAL_REREAD',
        'oracle_proof_hash':digest(evidence),'host_admission_request_hash':digest(request) if request else None,
        'native_execution_performed':False,'formal_frozen':False,'formal_ready':False}
    write(path.parent/'build_manifest.json',build)
    return {'task':task,'plan':d['plan'],'manifest':manifest,'manifest_path':path,'private_verifier':verifier,
            'private_directory':private,'proof':proof,'build':build}
