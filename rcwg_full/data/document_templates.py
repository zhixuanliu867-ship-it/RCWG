"""F5 controlled texts and explicit, request-bound engineering service recordings.

The recording is a test service fixture, never an actual semantic-model result.
Private verification parses the source language independently in document_oracle.
"""
from copy import deepcopy
from .templates import Plan,seed_for,task_shell,descriptor,predicate
from rcwg_full.runtime.documents import canonical_document,Documents
from rcwg_full.evidence import digest

REVISION='engineering-docs-v1'
DOMAIN='engineering-papers'
CITATION={'kind':'Record','schema':{'document_id':'Utf8','revision':'Utf8','start_cp':'Int64','end_cp':'Int64','quote':'Utf8'}}
EVIDENCE={'kind':'List','item':CITATION,'max_length':256}
BASE_FIELDS={'query_id':'Utf8','paper_id':'Utf8','entity_id':'Utf8'}


def citation(doc,text,*,start=0):
    at=doc['canonical_text'].index(text,start)
    return {'document_id':doc['document_id'],'revision':doc['revision'],'start_cp':at,'end_cp':at+len(text),'quote':text}


def document_descriptor(alias,docs):
    return {'id':'dataset:'+alias,'kind':'document_index','domain':DOMAIN,'revision':REVISION,
        'schema_source':'generated','schema':{'document_id':'Utf8','revision':'Utf8','canonical_text':'Utf8'},
        'id_type':'Utf8','id_field':'document_id','stats':{'document_count':len(docs)},'indexes':[]}


def selection_descriptor(alias,ids):
    return {'id':'dataset:'+alias,'kind':'id_selection','domain':DOMAIN,'revision':REVISION,
        'schema_source':'generated','id_type':'Utf8','ranked':False,'stats':{'item_count':len(ids)}}


def f5(template,base,condition):
    if condition not in {'C0','C1','C2','C3'}:raise ValueError('CONDITION')
    number=int(template[-2:]);seed=seed_for(template,base)
    if number not in range(1,13):raise ValueError('TEMPLATE_UNREGISTERED')
    docs=[];recordings=[];extra=[]
    nullable={'kind':'Nullable','item':{'kind':'Int64'}}
    fields={**BASE_FIELDS,'dose':'Int64','evidence':EVIDENCE}
    if number==2:fields.update(unit='Utf8',date='Date',confirmed='Bool')
    if number==4:fields={**BASE_FIELDS,'amount':'Int64','unit':'Utf8','status':'Utf8','evidence':EVIDENCE}
    if number==8:fields={**BASE_FIELDS,'dose':nullable,'status':'Utf8','evidence':EVIDENCE}
    if number==10:fields.update(version='Int64',status='Utf8')
    for i in range(4 if number in {4,9} else 3):
        paper=f'paper-{base}-{i}';entity=f'entity-{base}-{i//2 if number==9 else i}'
        dose=2+seed%7+(i//2 if number==9 else i);date=f'2025-02-{11+i:02d}'
        unit='g' if number==4 and i%2==0 else 'mg';status='refuted' if number==4 and i==2 else 'supported'
        definition=f'The symbol A denotes {entity}; the printed name is Shared.'
        statement=f'Entity {entity} has dose {dose} {unit}.'
        flag=f'Status for {entity} is {status}.'
        secondary=f'Entity {entity} has rate {dose+10} per_day.'
        sections=[{'section_id':'definition','heading':'Definitions','text':definition},
                  {'section_id':'result','heading':'Clinical dose of A','text':statement+' '+flag+' '+f'Date {date}; confirmed true.'},
                  {'section_id':'other','heading':'Machine dose of A','text':f'Entity {entity} has dose {dose+100} mg. '+secondary}]
        if number==7:sections.append({'section_id':'repeat','heading':'Replication','text':f'Repeated dose for {entity} is {dose} mg.'})
        if number==8:
            status='unknown' if i!=1 else 'refuted'
            sections[1]['text']=f'No dose is reported for {entity}.' if status=='unknown' else f'It is false that {entity} has a reported dose.'
            sections[2]['text']=secondary
        if number==10:
            sections[1]['text']=f'Version 1: {entity} dose {dose} mg, status supported.'
            sections[2]['text']=f'Version 2: {entity} dose {dose+20} mg, status refuted. '+secondary
        sections.append({'section_id':'neutral','heading':'Unrelated context',
            'text':('Neutral background without dose assertions. '*(80 if condition=='C1' else 2))+f'Fixture {base}, seed {seed}, document {i}. 🙂'})
        doc=canonical_document(paper,REVISION,'Controlled source '+paper,sections);docs.append(doc)
        row={'query_id':'q-dose','paper_id':paper,'entity_id':entity,'dose':dose}
        quote=statement
        if number==2:row.update(unit=unit,date=date,confirmed=True);quote=sections[1]['text']
        if number in {3,6}:quotes=[definition,statement] if number==3 else ['Clinical dose of A',statement]
        else:quotes=[quote]
        if number==4:
            row.pop('dose');row.update(amount=dose,unit=unit,status=status);quotes=[statement,flag]
        if number==8:row.update(dose=None,status=status);quotes=[] if status=='unknown' else [sections[1]['text']]
        if number==10:
            row.update(version=1,status='supported');quotes=[sections[1]['text']]
        row['evidence']=[citation(doc,q) for q in quotes];recordings.append(row)
        if number==7:recordings.append({**deepcopy(row),'evidence':[citation(doc,sections[3]['text'])]})
        if number==10:recordings.append({**deepcopy(row),'dose':dose+20,'version':2,'status':'refuted','evidence':[citation(doc,sections[2]['text'].split(' Entity ')[0])]})
        extra.append({'query_id':'q-rate','paper_id':paper,'entity_id':entity,'rate':dose+10,'evidence':[citation(doc,secondary)]})
    instructions={
      1:'逐 paper_id 与 query_id=q-dose 返回临床剂量 dose（mg）及原文证据，实体用明确的 entity_id 对齐。',
      2:'逐论文返回 q-dose 的 dose、unit、date、confirmed 全部字段及联合证据；日期为 ISO Date。',
      3:'A 必须依 Definitions 对齐实体后回答临床 dose；证据必须同时包含实体定义和剂量句。',
      4:'抽取 amount、unit 与 status，排除 refuted，按公开 units 换算 mg；返回 normalized_mg>=1000 的行和证据。',
      5:'剂量证据句跨四 token 分块边界；恢复完整句后返回逐论文的 dose 与完整原文证据。',
      6:'只回答 Clinical dose of A，不能使用 Machine dose of A；保留章节标题及正文证据。',
      7:'逐论文合并重复剂量事实，返回一条字段结果且保留原声明和 Replication 两个来源证据。',
      8:'未报告剂量返回 dose=null,status=unknown；明确否定返回 dose=null,status=refuted 并引用否定句。',
      9:'跨全部论文提取 clinical dose 后按 entity_id 保留最早论文的一条，返回 count_entities 和 total_dose；同名不是同一实体。',
      10:'同一实体的冲突记录按 version 降序选择，保留 discarded_alternatives 及其来源；不得默认为首次出现。',
      11:'共享同一正文回答 q-dose 和 q-rate，分别返回 dose_branch 与 rate_branch 的所有 query_id 字段及对应证据。',
      12:'显式选择 result 章节的原文片段作为压缩上下文，只回答临床 dose 并保留可回映的证据；禁止摘要文本。'}
    output={'id':'result','type':'evidence','mode':'evidence_supported','domain':DOMAIN,'revision':REVISION,'fields':list(fields),'schema':fields}
    if number==4:
        result_fields={**fields,'normalized_mg':'Int64'};output={'id':'result','type':'records','mode':'exact','fields':list(result_fields),'schema':result_fields}
    if number==9:output={'id':'result','type':'record','mode':'exact','fields':['count_entities','total_dose'],'schema':{'count_entities':'Int64','total_dose':nullable}}
    if number==11:
        rate_fields={**BASE_FIELDS,'rate':'Int64','evidence':EVIDENCE}
        output={'id':'result','type':'record','mode':'exact','fields':['dose_branch','rate_branch'],'schema':{
            label:{'kind':'EvidenceTable','schema':schema,'domain':DOMAIN,'revision':REVISION}
            for label,schema in [('dose_branch',fields),('rate_branch',rate_fields)]}}
    task=task_shell(template,base,condition,instructions[number],output);plan=Plan(task['task_id'])
    ids=[d['document_id'] for d in docs];sources={'documents':docs,'ids':ids};schemas={}
    task['datasets']=[document_descriptor('documents',docs),selection_descriptor('ids',ids)]
    plan.value['external_inputs']={'documents':'dataset:documents','ids':'dataset:ids'}
    source=plan.add('read','read_documents','batched',{'index':'$input.documents','ids':'$input.ids'},
        {'fields':['canonical_text'],'batch_size':2},{'documents':'DocumentStream'})
    adapter=Documents(docs);contexts=adapter.read_documents(ids,['canonical_text'],2,'batched','fixture-recording')
    if number in {3,5,6,12}:
        size=4 if number==5 else 64;split_impl='token_window' if number==5 else 'section'
        source=plan.add('chunks','split_documents',split_impl,{'documents':source},{'size':size,'overlap':0},{'chunks':'ChunkStream'})
        contexts=adapter.split(contexts,size,0,split_impl)
        if number==5:
            # A public, explicit extractive selection precedes context recovery.
            # Keep every block intersecting the selected section, including both
            # halves of a boundary-crossing witness; do not repeat neutral text.
            section_ranges={d['document_id']:next(s for s in d['sections'] if s['section_id']=='result') for d in docs}
            selected=[]
            for chunk in contexts:
                s=section_ranges[chunk['document_id']]
                if any(x['source_start_cp']<s['end_cp'] and s['start_cp']<x['source_end_cp'] for x in chunk['segments']):selected.append(chunk)
            ordinals=[c['chunk_ordinal'] for c in selected]
            source=plan.filter('select_boundary_blocks',source,predicate('chunk_ordinal','in',ordinals),'ChunkStream');contexts=selected
            task['instruction']+=' 目标为 result 章节；公开块选择 ordinal='+str(ordinals)+'。'
        if number in {6,12}:
            source=plan.filter('select_context',source,predicate('section_id','eq','result'),'ChunkStream')
            contexts=[c for c in contexts if c['section_id']=='result']
        impl='neighbors' if number in {3,5} else 'section_header';window=1 if number==3 else 0
        source=plan.add('context','gather_context',impl,{'chunks':source},{'window':window},{'chunks':'ChunkStream'})
        contexts=adapter.gather(contexts,window,impl,'fixture-recording')
    else:contexts=[adapter.selected_context(c) for c in contexts]
    responses={};stages=[]
    def extract(name,ref,schema,rows,question):
        params={'question':question,'field_schema':schema,'context_budget':100000}
        request={'service_id':'engineering-replay-e0','question':question,'field_schema':schema,'contexts':contexts}
        responses[digest(request)]=deepcopy(rows);stages.append({'node':name,'question':question})
        return plan.add(name,'semantic_extract','fixed_e0',{'documents':ref},params,{'evidence':'EvidenceTable'})
    if number==11:
        source=plan.add('shared','cache','memory',{'artifact':source},{'key_fields':['canonical_text']},{'artifact':'ArtifactRef'},storage='memory')
        plan.add('fan','broadcast','shared_ref',{'artifact':source},{'consumers':['dose','rate']},{'dose':'ArtifactRef','rate':'ArtifactRef'})
        a=extract('extract_dose','fan.dose',fields,recordings,'q-dose: clinical dose in mg')
        b=extract('extract_rate','fan.rate',rate_fields,extra,'q-rate: rate per_day')
        source=plan.add('combine','project','column_view',{'a':a,'b':b},{'representation':'record','field_map':{'dose_branch':'a','rate_branch':'b'}},{'rows':'Record'})
    else:
        source=extract('extract',source,fields,recordings,'q-dose: '+instructions[number])
        if number in {3,5,7,9,10}:
            params={'keys':['query_id','paper_id','entity_id'],'conflict_policy':'declared_priority' if number==10 else 'keep_all'}
            if number==10:params['priority_rule']=[{'field':'version','direction':'desc'}]
            source=plan.add('merge','evidence_merge','by_entity',{'evidence':source},params,{'evidence':'EvidenceTable'})
        if number in {1,2,12}:source=plan.add('validate','evidence_validate','span_check',{'index':'$input.documents','evidence':source},{'strict':True},{'evidence':'EvidenceTable'})
        if number in {4,9}:
            source=plan.add('read_evidence','stream_read','arrow_batches',{'artifact':source},{'batch_size':2},{'rows':'Stream[Record]'})
        if number==4:
            sources['units']=[{'unit_key':'g','scale':1000},{'unit_key':'mg','scale':1}];schemas['units']={'unit_key':'Utf8','scale':'Int64'}
            task['datasets'].append(descriptor('units',schemas['units'],sources['units']))
            units=plan.scan('units',schemas['units'])
            source=plan.add('units_join','join','hash',{'left':source,'right':units},{'keys':[{'left':'unit','right':'unit_key'}],'join_type':'inner','build_side':'right'})
            source=plan.project('normalize',source,list(fields),expressions={'normalized_mg':{'op':'mul','left':{'field':'amount'},'right':{'field':'scale'}}})
            source=plan.filter('eligible',source,{'op':'and','args':[predicate('status','eq','supported'),predicate('normalized_mg','ge',1000)]},'Table')
        if number==9:
            source=plan.add('entities','deduplicate','hash',{'rows':source},{'keys':['entity_id'],'keep':'first'},{'rows':'Stream[Record]'})
            source=plan.add('totals','aggregate','hash_group',{'rows':source},{'group_by':[],'aggregates':[{'function':'count','field':None,'as':'count_entities'},{'function':'sum','field':'dose','as':'total_dose'}]})
            source=plan.project('summary',source,['count_entities','total_dose'],'Record',representation='record')
    return {'task':task,'plan':plan.end(source),'rows':sources,'schemas':schemas,'template_id':template,'base_id':base,'condition':condition,
        'seed':seed,'axis':'document_length_with_controlled_neutral_context','comparison':'document_semantics','output_fields':output['fields'],
        'semantic_stages':stages,'replay':{'revision':'full001-engineering-replay-1','service_id':'engineering-replay-e0','responses':responses},
        'expected_args':{'template':number,'documents':docs},'formal_gold_reviewed':False}
