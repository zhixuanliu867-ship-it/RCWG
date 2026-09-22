"""F1/F2 formal candidate builders, batch bounded and separate from tiny seeds.

Formal construction is an internal controller operation requiring a trusted
host-admission callback. The callback must verify the exact request against the
owner's receipt; a file or a user-provided Boolean is never an approval here.
The fixture entrypoint has fixed small ceilings and cannot emit a formal profile.
"""
from copy import deepcopy
import random
from rcwg_full.evidence import digest,write,source_hashes
from rcwg_full.compiler import FullCompiler
from .capacity import parameter_table
from .templates import f1
from .relational_f2 import f2
from .stream_prepare import prepare_streams


def parameters(template):
    matches=[r for r in parameter_table() if r['template_id']==template and r['family'] in {'F1','F2'}]
    if len(matches)!=1:raise ValueError('FORMAL_RELATIONAL_TEMPLATE')
    return matches[0]


def definition(template,base,condition,*,fixture=False):
    p=parameters(template);d=(f1 if p['family']=='F1' else f2)(template,base,condition)
    profile='formal_builder_fixture_v1' if fixture else 'formal_candidate_v1'
    namespace='FULL001_FORMAL_BUILDER_FIXTURE_1' if fixture else p['namespace']
    seed=int(digest({'namespace':namespace,'template':template,'base':base})[:16],16)
    data=deepcopy(p['C1' if condition=='C1' else 'C0'])
    if fixture:
        if p['family']=='F1':data['rows']=113 if condition=='C1' and p['c1_axis']=='row_count' else 37
        else:data.update(left_rows=113 if condition=='C1' and p['c1_axis']=='left_row_count' else 37,right_rows=20,third_rows=12)
    task=deepcopy(d['task']);task['resources'].update(cpu_slots=p['cpu_slots'],
        worker_memory_limit_bytes=p['worker_ram_C2_bytes'] if condition=='C2' else p['worker_ram_C0_C1_C3_bytes'])
    task['notes']=profile.upper()+'; generated source; formal_frozen=false; reference feasibility requires native execution.'
    number=int(template[-2:]);n=data['rows'] if p['family']=='F1' else data['left_rows']
    def count(alias):
        if alias=='left_candidates':return n-n//3
        if alias=='right_candidates':return n-(n+2)//3
        if alias=='approximate_candidates':return min(10,n)
        return n if alias in {'records','left'} else data['right_rows'] if alias=='right' else data['third_rows']
    for source in task['datasets']:
        alias=source['id'].removeprefix('dataset:');source['revision']=profile+'-logical-1'
        source['schema_source']='full001-formal-relational-1'
        source['stats'].update(row_count=count(alias),estimated_row_bytes=p['row_width_candidate_bytes'],estimate_source='predeclared_capacity_candidate_not_measured_physical_bytes')
    def records(alias):
        rng=random.Random(seed ^ (0xB001 if alias=='right' else 0))
        if alias in {'left_candidates','right_candidates','approximate_candidates'}:
            for i in range(n if alias!='approximate_candidates' else min(10,n)):
                if alias=='left_candidates' and i%3==2 or alias=='right_candidates' and i%3==0:continue
                yield {'id':i}
            return
        for i in range(count(alias)):
            if p['family']=='F1':
                ratio=data.get('eligible_true_ratio',[3,4]);eligible=i%ratio[1]<ratio[0]
                if not eligible and i%11==0:eligible=None
                score=float(rng.randrange(-4,18));priority=rng.randrange(3);amount=rng.randrange(-20,70);payload=f'{base:01d}-{rng.randrange(1000000):06d}'+'x'*128
                if number==7:score=float(1000001-i)
                elif i==n-1:score=99.
                if number==4 and i%9==0:score=None
                yield {'id':i,'entity_id':i%13,'group_id':i%7,'score':score,'priority':priority,'eligible':eligible,
                    'q':None if i%7==0 else i%2==0,'amount':amount,'join_key':i%9,'timestamp':i*10,'payload':payload}
            elif alias=='left':
                keys=max(1,(data['right_rows']+3)//4);key=None if i%13==0 else i%(keys+max(1,keys//8))
                if number==2:
                    ratio=data['left_hot_key_ratio'];key=0 if i%ratio[1]<ratio[0] else 1+i%max(1,keys-1)
                ratio=data.get('eligible_true_ratio',[3,4])
                yield {'left_id':i,'join_key':key,'group_id':i%6,'entity_id':i%9,'amount':rng.randrange(-5,35),
                    'timestamp':i*10,'eligible':i%ratio[1]<ratio[0],'payload':f'{base}-{rng.randrange(99999):05d}'+'x'*128}
            elif alias=='right':
                yield {'right_id':i,'join_key':None if i%11==0 else i//4,
                    'right_entity_id':None if i%17==0 else i%max(1,(data['third_rows']+3)//4),
                    'qualified':i%4!=0,'payload_b':f'{base}-{rng.randrange(99999):05d}'+'y'*128}
            else:yield {'entity_key':i//4,'weight':1+i%3}
    return {'task':task,'plan':d['plan'],'schemas':d['schemas'],'sources':{r['id']:(lambda alias=r['id'].removeprefix('dataset:'):records(alias)) for r in task['datasets']},
        'seed':seed,'profile':profile,'parameter_hash':p['parameter_hash'],'data_parameters':data,'comparison':d['comparison'],
        'template_id':template,'base_id':base,'condition':condition,'c1_axis':p['c1_axis']}


def build_request(template,base,condition):
    d=definition(template,base,condition)
    return {'revision':'FULL001_FORMAL_RELATIONAL_BUILD_REQUEST_1','task_id':d['task']['task_id'],
        'profile':d['profile'],'source_hash':digest(source_hashes()),'parameter_hash':d['parameter_hash'],
        'data_parameters':d['data_parameters'],'action':'BUILD_GENERATED_DATA_AND_PRIVATE_SQL_ORACLE',
        'native_execution':False,'paid_calls':0,'formal_freeze':False}


def build_formal(template,base,condition,directory,*,host_admit=None):
    request=build_request(template,base,condition)
    if not callable(host_admit) or host_admit(deepcopy(request)) is not True:raise PermissionError('FORMAL_BUILD_HOST_ADMISSION_REQUIRED')
    # Callback side effects must not change any source used to define the load.
    if request!=build_request(template,base,condition):raise ValueError('BUILD_SOURCE_CHANGED')
    return _build(definition(template,base,condition),directory,request=request)


def build_fixture(template,base,condition,directory):
    return _build(definition(template,base,condition,fixture=True),directory,request=None)


def _build(d,directory,*,request):
    from rcwg_full.runtime.catalog import DataCatalog
    from rcwg_full.verification.relational_sql import build_recipe
    from rcwg_full.reference.candidates import candidates
    parameters_hash=d['parameter_hash'];profile=d['profile']
    task,manifest,path=prepare_streams(d['task'],{k:v() for k,v in d['sources'].items()},directory,
        profile=profile,provenance={'kind':'deterministic_generated_relational','parameter_hash':parameters_hash},
        batch_rows=31 if profile=='formal_builder_fixture_v1' else 1024,
        fragment_rows=(7 if profile=='formal_builder_fixture_v1' else 4093) if d['condition']=='C3' else None)
    catalog=DataCatalog(path).bind(task);logical=catalog.audit()
    private=path.parent.with_name(path.parent.name+'-private')
    recipe,oracle=build_recipe(catalog,d['template_id'],d['comparison'],private,seed=d['seed'],profile=profile)
    report=FullCompiler().compile(task,d['plan'])
    proof={'status':report['status'],'profile':report['profile'],'task_hash':digest(task),'plan_hash':digest(d['plan']),
        'operators':[n['operator'] for n in d['plan']['nodes']],'diagnostics':report['diagnostics'],
        'native_execution_status':'NOT_RUN','formal_reference_feasible':None}
    write(path.parent/'reference_plan.json',d['plan']);write(path.parent/'representation_proof.json',proof)
    write(path.parent/'candidate_definitions.json',candidates(task,d['plan']))
    write(path.parent/'condition_invariants.json',{'condition':d['condition'],'c1_axis':d['c1_axis'],
        'logical_hashes':logical,'condition_crosscheck':'REQUIRES_SIBLING_CONDITIONS','formal_frozen':False})
    build={'profile':profile,'parameter_hash':parameters_hash,'data_parameters':d['data_parameters'],
        'compile_status':proof['status'],'source_audit':'PASS','oracle_proof_hash':digest(oracle),
        'capacity':{'source_physical_bytes':sum(f['bytes'] for s in manifest['sources'] for f in s['physical_files']),
            'oracle_sqlite_bytes':oracle['sqlite_file_bytes'],'builder_peak_ram_bytes':None},
        'host_admission_request_hash':digest(request) if request else None,'native_execution_performed':False,
        'formal_frozen':False,'formal_ready':False}
    write(path.parent/'build_manifest.json',build)
    return {'task':task,'plan':d['plan'],'manifest':manifest,'manifest_path':path,'private_verifier':recipe,
        'proof':proof,'build':build,'private_directory':private}
