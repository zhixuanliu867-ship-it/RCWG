"""Registered, reproducible task constructors. Data and private recipes are separate."""
from copy import deepcopy
import random
from rcwg_full.evidence import ROOT,digest,write
from rcwg_full.compiler import FullCompiler
from .prepare import prepare


def scalar(kind,nullable=False):return {'kind':'Nullable','item':{'kind':kind}} if nullable else {'kind':kind}
def key(field,direction='asc'):return {'field':field,'direction':direction}
def predicate(field,op,value):return {'op':op,'left':{'field':field},'right':{'literal':value}}
def both(*args):return {'op':'and','args':list(args)}


class Plan:
    def __init__(self,task_id):self.value={'ir_version':'1.0','task_id':task_id,'external_inputs':{},'nodes':[]}
    def add(self,name,operator,implementation,inputs,params,outputs=None,**extra):
        outputs=outputs or {'rows':'Table'}
        self.value['nodes'].append(dict(id=name,operator=operator,implementation=implementation,inputs=inputs,params=params,outputs=outputs,**extra))
        return name+'.'+next(iter(outputs))
    def scan(self,alias,schema):
        self.value['external_inputs'][alias]='dataset:'+alias
        return self.add('scan_'+alias,'scan','sequential',{'source':'$input.'+alias},{'columns':list(schema)},{'rows':'Stream[Record]'},storage='stream')
    def filter(self,name,source,expression,kind='Stream[Record]'):
        return self.add(name,'filter','vectorized',{'rows':source},{'predicate':expression},{'rows':kind})
    def project(self,name,source,columns,kind='Table',**params):
        return self.add(name,'project','column_view',{'rows':source},{'columns':columns,**params},{'rows':kind})
    def top(self,name,source,k,keys,**params):
        return self.add(name,'top_k','streaming_heap',{'rows':source},{'k':k,'keys':keys,**params})
    def aggregate(self,name,source,groups,fn,field,alias):
        return self.add(name,'aggregate','hash_group',{'rows':source},{'group_by':groups,'aggregates':[{'function':fn,'field':field,'as':alias}]})
    def end(self,source):
        self.value['result']=self.add('emit','emit','json_artifact',{'rows':source},{'output_contract':'result'},{'result':'Result'})
        return self.value


def task_shell(template,base,condition,instruction,output):
    return {'task_id':f'{template}-b{base}-{condition}','instruction':instruction,'datasets':[],
            'resources':{'cpu_slots':2,'worker_memory_limit_bytes':(32 if condition=='C2' else 64)*1024**2,'wall_timeout_s':30},
            'output_contract':output,'tool_catalog_id':'rcwg-full001-compat1','notes':'ENGINEERING_TINY_ONLY; deterministic generated Unicode fixture; no formal calibration or data freeze.'}


def descriptor(alias,schema,rows):
    return {'id':'dataset:'+alias,'kind':'table','revision':'engineering-logical-v1','schema_source':'full001-generator-1',
            'schema':schema,'stats':{'row_count':len(rows),'estimated_row_bytes':128,'estimate_source':'generator_definition'}}


def seed_for(template,base):
    if type(base) is not int or base not in range(5):raise ValueError('BASE_RANGE')
    return int(digest({'namespace':'FULL001_ENGINEERING_TINY_1','template':template,'base':base,'condition_axis':'base'})[:16],16)


def f1(template,base,condition):
    if condition not in {'C0','C1','C2','C3'}:raise ValueError('CONDITION')
    number=int(template[-2:]);seed=seed_for(template,base);rng=random.Random(seed)
    selectivity=number in {2,10};n=113 if condition=='C1' and not selectivity else 37
    schema={'id':'Int64','entity_id':'Int64','group_id':'Int64','score':scalar('Float64',number==4),'priority':'Int64',
            'eligible':scalar('Bool',True),'q':scalar('Bool',True),'amount':'Int64','join_key':'Int64','timestamp':'Int64','payload':'Utf8'}
    rows=[]
    for i in range(n):
        rows.append({'id':i,'entity_id':i%13,'group_id':i%7,'score':float(rng.randrange(-4,18)),
            'priority':rng.randrange(3),'eligible':None if i%11==0 else (i%5==0 if base==0 else i%3!=0),
            'q':None if i%7==0 else i%2==0,'amount':rng.randrange(-20,70),'join_key':i%9,'timestamp':i*10,
            'payload':f'实例{base}·α·{rng.randrange(1000000):06d}'})
    # The final physical batch includes the global maximum, excluding the
    # approximate prefix used by F1-12. Late duplicates also matter for F1-06.
    rows[-1].update(score=99.,eligible=True,q=True)
    if number==4:
        for i in range(0,n,9):rows[i]['score']=None
    if condition=='C1' and selectivity:
        for i,row in enumerate(rows):row['eligible']=None if i%11==0 else i%7==0
    if number==7:rows.sort(key=lambda r:(-r['score'],r['id']))
    rank=[key('score','desc'),key('id')];fields=['id','score'];out_schema={k:schema[k] for k in fields}
    if number==4:rank[0]['nulls']='last'
    comparison='ordered';sources={'records':rows};schemas={'records':schema}
    instructions={
      1:'eligible=true 后按 score 降序、id 升序返回最多 20 行，只输出 id、score。',
      2:'eligible AND q 为 true 后按 score 降序、id 升序取 20；unknown 不入选。',
      3:'按 score 降序、priority 升序、id 升序取 20 行，保留三个排序字段。',
      4:'score>=0 AND eligible 为 true 后精确取前 20，null 不入选。',
      5:'每个 group_id 独立取 score 降序、id 升序前三行；输出全组结果，不补空组。',
      6:'按原始遍历 ordinal 对 entity_id 保留第一行，再按 score 降序、id 升序取 20。',
      7:'源记录保证按 score 降序、id 升序排列；返回前 20 个 eligible=true 的行，不足时耗尽。',
      8:'合并 left_candidates 与 right_candidates 的 id 集合，从公开 records 回取；按 records 原始 ordinal 对 entity_id 保留第一行，再精确取前 20。',
      9:'eligible=true 后按 group_id 求 sum(amount)，再按 total 降序、group_id 升序取 10 组。',
      10:'eligible=true 的共享记录分别统计 score>=5 和 score>=10 的行数；low/high 各包含唯一 count 记录。',
      11:'按 priority 升序、score 降序、id 升序精确取前 20，仅输出 id 和 score。',
      12:'approximate_candidates 仅是候选提示，必须返回全 records 中 eligible=true 的精确 top20，score 降序、id 升序。'}
    if number not in instructions:raise ValueError('TEMPLATE_UNREGISTERED')
    if number in {3,5,6,8}:fields=['id','score']+(['priority'] if number==3 else ['group_id'] if number==5 else ['entity_id'])
    if number==5:comparison='bag'
    if number==9:fields=['group_id','total'];out_schema={'group_id':'Int64','total':'Int64'}
    else:out_schema={k:schema[k] for k in fields}
    output={'id':'result','type':'records','mode':'exact','fields':fields,'schema':out_schema}
    if number==10:
        comparison='record';count_type={'kind':'Record','schema':{'count':'Int64'}}
        output={'id':'result','type':'record','mode':'exact','fields':['low','high'],'schema':{'low':count_type,'high':count_type}}
    task=task_shell(template,base,condition,instructions[number],output);plan=Plan(task['task_id']);source=plan.scan('records',schema)
    if number in {1,2,4,7,9,10,12}:
        expr=predicate('eligible','eq',True)
        if number==2:expr=both(expr,predicate('q','eq',True))
        if number==4:expr=both(expr,predicate('score','ge',0.))
        source=plan.filter('eligible',source,expr)
    if number in {3,11}:rank=[key('score','desc'),key('priority'),key('id')] if number==3 else [key('priority'),key('score','desc'),key('id')]
    if number==8:
        for alias,subset in [('left_candidates',[r for r in rows if r['id']%3!=2]),('right_candidates',[r for r in rows if r['id']%3!=0])]:
            sources[alias]=[{'id':r['id']} for r in subset];schemas[alias]={'id':'Int64'}
            scanned=plan.scan(alias,schemas[alias]);plan.project(alias,scanned,['id'],'Set',representation='set')
        union=plan.add('union','set_op','hash',{'left':'left_candidates.rows','right':'right_candidates.rows'},{'mode':'union'},{'items':'Set'})
        ids=plan.project('id_rows',union,['id'],source_view='ids',representation='table')
        source=plan.add('retrieve','join','hash',{'left':source,'right':ids},{'keys':[{'left':'id','right':'id'}],'join_type':'semi','build_side':'right'})
    if number in {6,8}:source=plan.add('unique','deduplicate','hash',{'rows':source},{'keys':['entity_id'],'keep':'first'},{'rows':'Stream[Record]' if number==6 else 'Table'})
    if number==9:source=plan.aggregate('sum_groups',source,['group_id'],'sum','amount','total');rank=[key('total','desc'),key('group_id')]
    if number==10:
        material=plan.add('shared','materialize','memory',{'rows':source},{'format':'arrow_ipc'},storage='memory')
        plan.add('fan','broadcast','shared_ref',{'artifact':material},{'consumers':['low','high']},{'low':'ArtifactRef','high':'ArtifactRef'})
        for label,threshold in [('low',5.),('high',10.)]:
            r=plan.add('read_'+label,'stream_read','arrow_batches',{'artifact':'fan.'+label},{'batch_size':7},{'rows':'Stream[Record]'})
            r=plan.filter('filter_'+label,r,predicate('score','ge',threshold));r=plan.aggregate('count_'+label,r,[],'count',None,'count')
            plan.project('record_'+label,r,['count'],'Record',representation='record')
        source=plan.add('combine','project','column_view',{'low':'record_low.rows','high':'record_high.rows'},
            {'representation':'record','field_map':{'low':'low','high':'high'}},{'rows':'Record'})
    else:
        if number==11:source=plan.add('ordered','sort','in_memory',{'rows':source},{'keys':rank})
        source=plan.top('top',source,3 if number==5 else 10 if number==9 else 20,rank,**({'partition_by':['group_id']} if number==5 else {}))
        source=plan.project('result_fields',source,fields)
    if number==12:sources['approximate_candidates']=[{'id':r['id']} for r in rows[:10]];schemas['approximate_candidates']={'id':'Int64'}
    task['datasets']=[descriptor(alias,schemas[alias],data) for alias,data in sources.items()]
    return {'task':task,'plan':plan.end(source),'rows':sources,'schemas':schemas,'template_id':template,'base_id':base,'condition':condition,
            'seed':seed,'axis':'selectivity' if selectivity else 'row_count','comparison':comparison,'output_fields':fields}


def build(template,base,condition,directory):
    import pyarrow as pa
    from rcwg_full.runtime.values import arrow_schema
    from rcwg_full.verification.relational_oracle import f1_expected,f2_expected
    if template.startswith('F1-'):definition=f1(template,base,condition);oracle=f1_expected
    elif template.startswith('F2-'):
        from .relational_f2 import f2
        definition=f2(template,base,condition);oracle=f2_expected
    elif template.startswith('F3-'):
        from .graph_templates import f3
        from rcwg_full.verification.graph_oracle import f3_expected
        definition=f3(template,base,condition);oracle=None
    elif template.startswith('F4-'):
        from .stream_templates import f4
        from rcwg_full.verification.stream_oracle import f4_expected
        definition=f4(template,base,condition);oracle=lambda number,sources:f4_expected(number,sources,base)
    elif template.startswith('F5-'):
        from .document_templates import f5
        from rcwg_full.verification.document_oracle import f5_expected
        definition=f5(template,base,condition);oracle=lambda number,sources:f5_expected(definition['expected_args'])
    else:raise ValueError('TEMPLATE_BUILDER_NOT_YET_REGISTERED')
    values={'dataset:'+alias:(pa.Table.from_pylist(rows,schema=arrow_schema({'kind':'Table','schema':definition['schemas'][alias]})) if alias in definition['schemas'] else deepcopy(rows)) for alias,rows in definition['rows'].items()}
    task,manifest,path=prepare(definition['task'],values,directory,layout='fragmented' if condition=='C3' else 'contiguous')
    expected=oracle(int(template[-2:]),definition['rows']) if oracle else f3_expected(definition['expected_args'])
    report=FullCompiler().compile(task,definition['plan'])
    proof={'status':report['status'],'profile':report['profile'],'task_hash':digest(task),'plan_hash':digest(definition['plan']),
           'operators':[n['operator'] for n in definition['plan']['nodes']],'diagnostics':report['diagnostics']}
    write(path.parent/'representation_proof.json',proof);write(path.parent/'reference_plan.json',definition['plan'])
    from rcwg_full.reference.candidates import candidates
    write(path.parent/'candidate_definitions.json',candidates(task,definition['plan']))
    recipe={'role':'PRIVATE_ENGINEERING_ORACLE','template_id':template,'seed':definition['seed'],'comparison':definition['comparison'],
            'expected':expected,'implementation':'independent source-language oracle' if template.startswith('F5-') else 'independent Python contract; no runtime kernels','formal_gold_reviewed':False}
    if 'replay' in definition:
        write(path.parent/'engineering_service_replay.json',definition['replay'])
        write(path.parent/'semantic_stage_definitions.json',definition['semantic_stages'])
        write(path.parent/'evidence_span_remap.json',{'condition':condition,'mapping':'IDENTITY_CANONICAL_TEXT_UNCHANGED',
            'documents':[{'document_id':d['document_id'],'revision':d['revision'],'canonical_sha256':d['canonical_text_sha256']} for d in definition['rows']['documents']],
            'human_reviewed':False,'formal_frozen':False})
    write(path.parent/'private_verifier_recipe.json',recipe)
    write(path.parent/'condition_invariants.json',{'condition':condition,'c1_axis':definition['axis'],'base_seed':definition['seed'],
        'logical_hashes':{r['source_id']:r['logical_content_sha256'] for r in manifest['sources']},
        'physical_hashes':{r['source_id']:r['content_sha256'] for r in manifest['sources']},
        'expected_output_hash':digest(expected),'condition_crosscheck':'REQUIRES_SIBLING_CONDITIONS'})
    return {**definition,'task':task,'manifest':manifest,'manifest_path':path,'recipe':recipe,'proof':proof}


def f1_01(base,condition,directory):return build('F1-01',base,condition,directory)
def f1_02(base,condition,directory):return build('F1-02',base,condition,directory)
def f1_03(base,condition,directory):return build('F1-03',base,condition,directory)
def f1_04(base,condition,directory):return build('F1-04',base,condition,directory)
def f1_05(base,condition,directory):return build('F1-05',base,condition,directory)
def f1_06(base,condition,directory):return build('F1-06',base,condition,directory)
def f1_07(base,condition,directory):return build('F1-07',base,condition,directory)
def f1_08(base,condition,directory):return build('F1-08',base,condition,directory)
def f1_09(base,condition,directory):return build('F1-09',base,condition,directory)
def f1_10(base,condition,directory):return build('F1-10',base,condition,directory)
def f1_11(base,condition,directory):return build('F1-11',base,condition,directory)
def f1_12(base,condition,directory):return build('F1-12',base,condition,directory)

def f2_01(base,condition,directory):return build('F2-01',base,condition,directory)
def f2_02(base,condition,directory):return build('F2-02',base,condition,directory)
def f2_03(base,condition,directory):return build('F2-03',base,condition,directory)
def f2_04(base,condition,directory):return build('F2-04',base,condition,directory)
def f2_05(base,condition,directory):return build('F2-05',base,condition,directory)
def f2_06(base,condition,directory):return build('F2-06',base,condition,directory)
def f2_07(base,condition,directory):return build('F2-07',base,condition,directory)
def f2_08(base,condition,directory):return build('F2-08',base,condition,directory)
def f2_09(base,condition,directory):return build('F2-09',base,condition,directory)
def f2_10(base,condition,directory):return build('F2-10',base,condition,directory)
def f2_11(base,condition,directory):return build('F2-11',base,condition,directory)
def f2_12(base,condition,directory):return build('F2-12',base,condition,directory)

def f3_01(base,condition,directory):return build('F3-01',base,condition,directory)
def f3_02(base,condition,directory):return build('F3-02',base,condition,directory)
def f3_03(base,condition,directory):return build('F3-03',base,condition,directory)
def f3_04(base,condition,directory):return build('F3-04',base,condition,directory)
def f3_05(base,condition,directory):return build('F3-05',base,condition,directory)
def f3_06(base,condition,directory):return build('F3-06',base,condition,directory)
def f3_07(base,condition,directory):return build('F3-07',base,condition,directory)
def f3_08(base,condition,directory):return build('F3-08',base,condition,directory)
def f3_09(base,condition,directory):return build('F3-09',base,condition,directory)
def f3_10(base,condition,directory):return build('F3-10',base,condition,directory)
def f3_11(base,condition,directory):return build('F3-11',base,condition,directory)
def f3_12(base,condition,directory):return build('F3-12',base,condition,directory)

def f4_01(base,condition,directory):return build('F4-01',base,condition,directory)
def f4_02(base,condition,directory):return build('F4-02',base,condition,directory)
def f4_03(base,condition,directory):return build('F4-03',base,condition,directory)
def f4_04(base,condition,directory):return build('F4-04',base,condition,directory)
def f4_05(base,condition,directory):return build('F4-05',base,condition,directory)
def f4_06(base,condition,directory):return build('F4-06',base,condition,directory)
def f4_07(base,condition,directory):return build('F4-07',base,condition,directory)
def f4_08(base,condition,directory):return build('F4-08',base,condition,directory)
def f4_09(base,condition,directory):return build('F4-09',base,condition,directory)
def f4_10(base,condition,directory):return build('F4-10',base,condition,directory)
def f4_11(base,condition,directory):return build('F4-11',base,condition,directory)
def f4_12(base,condition,directory):return build('F4-12',base,condition,directory)

def f5_01(base,condition,directory):return build('F5-01',base,condition,directory)
def f5_02(base,condition,directory):return build('F5-02',base,condition,directory)
def f5_03(base,condition,directory):return build('F5-03',base,condition,directory)
def f5_04(base,condition,directory):return build('F5-04',base,condition,directory)
def f5_05(base,condition,directory):return build('F5-05',base,condition,directory)
def f5_06(base,condition,directory):return build('F5-06',base,condition,directory)
def f5_07(base,condition,directory):return build('F5-07',base,condition,directory)
def f5_08(base,condition,directory):return build('F5-08',base,condition,directory)
def f5_09(base,condition,directory):return build('F5-09',base,condition,directory)
def f5_10(base,condition,directory):return build('F5-10',base,condition,directory)
def f5_11(base,condition,directory):return build('F5-11',base,condition,directory)
def f5_12(base,condition,directory):return build('F5-12',base,condition,directory)
