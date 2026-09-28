"""F6 controlled graph/text plans with typed, revision-bound mapping tables."""
from copy import deepcopy
from .templates import Plan,seed_for,task_shell,descriptor,predicate,both
from .document_templates import BASE_FIELDS,EVIDENCE,DOMAIN,REVISION,document_descriptor,selection_descriptor,citation
from rcwg_full.runtime.documents import canonical_document,Documents
from rcwg_full.evidence import digest


def f6(template,base,condition):
    if condition not in {'C0','C1','C2','C3'}:raise ValueError('CONDITION')
    number=int(template[-2:]);seed=seed_for(template,base)
    if number not in range(1,13):raise ValueError('TEMPLATE_UNREGISTERED')
    n=15 if condition=='C1' else 9;domain='engineering-mixed-graph';revision=REVISION
    ns={'node_id':'Int64','score':'Int64'};es={'edge_id':'Int64','src':'Int64','dst':'Int64','type':'Utf8','time':'Int64','weight':'Float64'}
    nodes=[{'node_id':i,'score':1000-i*7+base} for i in range(n)]
    arcs=[(0,1),(1,2),(2,3),(0,4),(4,5),(0,6),(6,7),(0,8)]+[(0,i) for i in range(9,n)]
    edges=[{'edge_id':j,'src':a,'dst':b,'type':'other' if b%4==0 else 'allowed','time':10+20*(j%4),'weight':1.} for j,(a,b) in enumerate(arcs)]
    graph={'domain':domain,'revision':revision,'directed':True,'nodes':nodes,'edges':edges,'edge_index':sorted(range(len(edges)),key=lambda i:(edges[i]['time'],i))}
    docs=[];facts={};mappings=[]
    fields={**BASE_FIELDS,'status':'Utf8','value':'Int64','evidence':EVIDENCE}
    for i in range(n):
        paper=f'mixed-{base}-{i:02d}';entity=f'entity-{base}-{i}'
        status=['supported','refuted','unknown'][i%3]
        if number==9:status='supported' if i in {1,3,5,6,7} else 'unknown'
        second='supported' if i%2 else 'refuted';value=seed%17+i*3
        first=f'Condition A for {entity} is {status}. Value {value} mg.'
        latter=f'Condition B for {entity} is {second}.'
        doc=canonical_document(paper,revision,'Controlled graph-linked source',[{'heading':'Entity definition','text':f'Node {i} denotes {entity}.'},
            {'heading':'Primary evidence','text':first},{'heading':'Secondary evidence','text':latter},
            {'heading':'Link evidence','text':f'The next entity node is 1. Fixture {seed}.'}]);docs.append(doc)
        facts[paper]={'query_id':'q-A','paper_id':paper,'entity_id':entity,'status':status,'value':value,
            'evidence':[citation(doc,first)]}
        group=0 if i in {1,3} else 1 if i in {6,7} else 2
        mappings.append({'node_key':i,'document_id':paper,'score':nodes[i]['score'],'group_id':group,'source_revision':revision})
    mapping_schema={'node_key':'Int64','document_id':'Utf8','score':'Int64','group_id':'Int64','source_revision':'Utf8'}
    public_graph={'id':'dataset:graph','kind':'graph','domain':domain,'revision':revision,'schema_source':'generated',
        'node_schema':ns,'edge_schema':es,'node_id_type':'Int64','node_id_field':'node_id','source_field':'src','target_field':'dst','directed':True,
        'weight_field':'weight','weight_nonnegative':True,'weight_equal':True,'stats':{'node_count':n,'edge_count':len(edges)},
        'indexes':[{'id':'edge-time','kind':'sorted','fields':['time'],'revision':revision,'source':'generated'}]}
    mapped=descriptor('mapping',mapping_schema,mappings);mapped.update(revision=revision,id_field='document_id',id_domain=DOMAIN)
    datasets=[public_graph,mapped,document_descriptor('documents',docs),
        {'id':'dataset:seeds','kind':'node_set','domain':domain,'revision':revision,'schema_source':'generated','id_type':'Int64','stats':{'item_count':1}}]
    sources={'graph':graph,'mapping':mappings,'documents':docs,'seeds':[0]};schemas={'mapping':mapping_schema}
    instructions={
      1:'仅沿 allowed 边从 node 0 向外3跳可达且 node_id>0 的文档，核验条件 A；输出 supported 的全量字段和原文证据。',
      2:'先从完整公开文档索引检索并核验条件 A，再取与 allowed 边3跳可达（不含0）映射的交集；候选 limit 必须覆盖索引。',
      3:'关系仅 time 在 [20,60) 且 type=allowed 的边有效；从0向外3跳、不含0，再核验条件 A 的 supported 状态。',
      4:'返回 allowed 图从0至所有非0 targets 的合法最短 paths，及3跳可达的 supported 终端 facts；路径和语义证据均须通过。',
      5:'仅 allowed 图3跳可达非0文档且条件 A=supported 后，按 mapping.score 降序、paper_id 升序精确取前2。',
      6:'先从 node0 正文提取 next entity node，显式对齐图 node_id，再沿 allowed 边2跳取文档，核验条件 A=supported；保留两个问题各自证据。',
      7:'同一 allowed 图3跳非0候选上核验 A 与 B，返回 A=supported 文档集合减去 B=supported 文档集合（A-B），不得反转。',
      8:'allowed 图3跳非0候选全部输出条件 A；缺少证据保留 unknown，不能用图关系推导 supported 或 refuted。',
      9:'指定每个 group_id 必须有两实体同时满足 allowed 图3跳非0及 A=supported；返回完整组的 count_entities=2、total_value，不能只检查部分实体。',
      10:'共享 allowed 图3跳非0候选，分别返回 A、B 两条件 supported 的 dose_branch 与 rate_branch，证据不得串用。',
      11:'按公开 score 降序、document_id 升序遍历 allowed 图3跳非0候选；完整核验 A 后返回前2个 supported，unknown 不得冒充 refuted；完整扫描是合法参照。',
      12:'图、mapping 和正文必须来自 engineering-docs-v1；仅 allowed 图3跳非0且 A=supported；同ID旧版正文不得混用。'}
    out={'id':'result','type':'records','mode':'exact','fields':list(fields),'schema':fields}
    if number in {5,11}:out['fields']+=['score'];out['schema']={**fields,'score':'Int64'}
    if number==7:out={'id':'result','type':'records','mode':'exact','fields':['id'],'schema':{'id':'Utf8'}}
    if number==9:out={'id':'result','type':'records','mode':'exact','fields':['group_id','count_entities','total_value'],
        'schema':{'group_id':'Int64','count_entities':'Int64','total_value':'Int64'}}
    evidence_type={'kind':'Table','schema':fields,'domain':DOMAIN,'revision':revision}
    if number==4:out={'id':'result','type':'record','mode':'exact','fields':['paths','facts'],
        'schema':{'paths':{'kind':'PathSet','item':'Int64','domain':domain,'revision':revision},'facts':evidence_type}}
    if number==10:out={'id':'result','type':'record','mode':'exact','fields':['dose_branch','rate_branch'],
        'schema':{'dose_branch':evidence_type,'rate_branch':evidence_type}}
    task=task_shell(template,base,condition,instructions[number],out);task['resources']['wall_timeout_s']=45
    plan=Plan(task['task_id']);plan.value['external_inputs']={'graph':'dataset:graph','seeds':'dataset:seeds','documents':'dataset:documents'}
    mapping=plan.scan('mapping',mapping_schema)
    mapping=plan.add('mapping_table','materialize','memory',{'rows':mapping},{'format':'arrow_ipc'},storage='memory')
    responses={};stages=[];adapter=Documents(docs)
    def read(name,ids_ref,ids_list,table=True):
        params={'fields':['canonical_text'],'batch_size':3}
        if table:params['id_field']='document_id'
        ref=plan.add(name,'read_documents','batched',{'index':'$input.documents','ids':ids_ref},params,{'documents':'DocumentStream'})
        context=[adapter.selected_context(c) for c in adapter.read_documents(ids_list,['canonical_text'],3,'batched','fixture-recording')]
        return ref,context
    def extract(name,ref,context,rows,schema=fields,question='q-A: verify condition A'):
        request={'service_id':'engineering-replay-e0','question':question,'field_schema':schema,'contexts':context}
        responses[digest(request)]=deepcopy(rows);stages.append({'node':name,'question':question})
        return plan.add(name,'semantic_extract','fixed_e0',{'documents':ref},{'question':question,'field_schema':schema,'context_budget':100000},{'evidence':'EvidenceTable'})
    def table(name,evidence):return plan.add(name,'stream_read','arrow_batches',{'artifact':evidence},{'batch_size':3},{'rows':'Stream[Record]'})
    def eligible(name,evidence):
        stream=table(name+'_read',evidence)
        filtered=plan.filter(name,stream,predicate('status','eq','supported'))
        return plan.add(name+'_collect','collect','bounded_collect',{'rows':filtered},{'limit':n})
    def join(name,left,right,left_key,right_key,mode='inner'):
        return plan.add(name,'join','hash',{'left':left,'right':right},{'keys':[{'left':left_key,'right':right_key}],'join_type':mode,'build_side':'right'})
    seed_ref='$input.seeds';seed_ids=[0]
    if number==6:
        sources['root_document']=[docs[0]['document_id']];datasets.append(selection_descriptor('root_document',sources['root_document']))
        plan.value['external_inputs']['root_document']='dataset:root_document'
        root_ref,root_context=read('read_root','$input.root_document',sources['root_document'],False)
        root_schema={**BASE_FIELDS,'target_node':'Int64','evidence':EVIDENCE}
        root_rows=[{'query_id':'q-next','paper_id':docs[0]['document_id'],'entity_id':facts[docs[0]['document_id']]['entity_id'],'target_node':1,'evidence':[citation(docs[0],'The next entity node is 1.')]}]
        root_result=extract('extract_seed',root_ref,root_context,root_rows,root_schema,'q-next: next entity node')
        graph_nodes=plan.project('graph_node_rows','$input.graph',['node_id'],source_view='nodes',representation='table')
        seed_join=join('align_seed',graph_nodes,table('seed_rows',root_result),'node_id','target_node','semi')
        seed_ref=plan.project('semantic_seeds',seed_join,['node_id'],'NodeSet',representation='set');seed_ids=[1]
    expr=predicate('type','eq','allowed')
    if number==3:expr=both(expr,predicate('time','ge',20),predicate('time','lt',60))
    g=plan.add('graph_view','graph_filter','edge_mask',{'graph':'$input.graph'},{'predicate':expr},{'graph':'GraphView'})
    hops=2 if number==6 else 3
    reachable=plan.add('reachable','graph_reachability','bfs',{'graph':g,'seeds':seed_ref},{'max_hops':hops,'direction':'out'},{'nodes':'NodeSet'})
    node_rows=plan.project('reachable_rows',reachable,['id'],source_view='ids',representation='table')
    node_rows=plan.filter('exclude_root',node_rows,predicate('id','gt',0),'Table')
    mapped_rows=join('map_documents',node_rows,mapping,'id','node_key')
    # Fixture service recordings are fixed from the declarative graph, not from a trial's outputs.
    frontier=set(seed_ids);seen=set(frontier)
    for _ in range(hops):
        frontier={e['dst'] for e in edges if e['src'] in frontier and e['type']=='allowed' and (number!=3 or 20<=e['time']<60)}-seen;seen|=frontier
    selected=[m['document_id'] for m in mappings if m['node_key'] in seen and m['node_key']>0]
    if number==11:mapped_rows=plan.add('ordered_candidates','sort','in_memory',{'rows':mapped_rows},{'keys':[{'field':'score','direction':'desc'},{'field':'document_id','direction':'asc'}]})
    selected_ref=plan.project('selected_documents',mapped_rows,['document_id'])
    if number==2:
        ranked=plan.add('retrieve','text_retrieve','bm25',{'index':'$input.documents'},{'query':'entity','limit':n,'offset':0},{'ids':'RankedIDSet'})
        retrieved=adapter.retrieve('entity',n);all_ids=[r['document_id'] for r in retrieved]
        document_ref,contexts=read('read_all',ranked,all_ids,False)
        all_rows=[facts[i] for i in all_ids];extracted=extract('extract',document_ref,contexts,all_rows)
        source=join('graph_verified',eligible('semantic_supported',extracted),selected_ref,'paper_id','document_id','semi')
    elif number==10:
        stream=plan.add('candidate_stream','stream_read','arrow_batches',{'artifact':selected_ref},{'batch_size':3},{'rows':'Stream[Record]'})
        shared=plan.add('shared_candidates','materialize','memory',{'rows':stream},{'format':'arrow_ipc'},storage='memory')
        plan.add('fan','broadcast','shared_ref',{'artifact':shared},{'consumers':['a','b']},{'a':'ArtifactRef','b':'ArtifactRef'})
        branches={}
        for label in ['a','b']:
            document_ref,contexts=read('read_'+label,'fan.'+label,selected)
            rows=[deepcopy(facts[i]) for i in selected]
            if label=='b':
                for row in rows:
                    d=adapter.document(row['paper_id']);s=d['sections'][2]['text'];row.update(query_id='q-B',status='supported' if ' is supported.' in s else 'refuted',evidence=[citation(d,s),citation(d,f"Value {row['value']} mg.")])
            extracted=extract('extract_'+label,document_ref,contexts,rows,question='q-'+label.upper()+': verify condition '+label.upper())
            branches['dose_branch' if label=='a' else 'rate_branch']=eligible('supported_'+label,extracted)
        source=plan.add('combine','project','column_view',branches,{'representation':'record','field_map':{k:k for k in branches}},{'rows':'Record'})
    else:
        document_ref,contexts=read('read',selected_ref,selected);rows=[deepcopy(facts[i]) for i in selected]
        extracted=extract('extract',document_ref,contexts,rows)
        source=table('all_status_rows',extracted) if number==8 else eligible('semantic_supported',extracted)
        if number==8:source=plan.add('all_status','collect','bounded_collect',{'rows':source},{'limit':n})
        if number==7:
            b_rows=deepcopy(rows)
            for row in b_rows:
                d=adapter.document(row['paper_id']);s=d['sections'][2]['text'];row.update(query_id='q-B',status='supported' if ' is supported.' in s else 'refuted',evidence=[citation(d,s),citation(d,f"Value {row['value']} mg.")])
            b=extract('extract_b',document_ref,contexts,b_rows,question='q-B: verify condition B')
            a_ids=plan.project('a_ids',source,['paper_id'],'Set',representation='set')
            b_ids=plan.project('b_ids',eligible('b_supported',b),['paper_id'],'Set',representation='set')
            difference=plan.add('difference','set_op','hash',{'left':a_ids,'right':b_ids},{'mode':'difference'},{'items':'Set'})
            source=plan.project('ids',difference,['id'],source_view='ids',representation='table')
        if number in {5,9,11}:
            enriched=join('attributes',source,mapping,'paper_id','document_id')
            if number==9:
                source=plan.add('groups','aggregate','hash_group',{'rows':enriched},{'group_by':['group_id'],'aggregates':[{'function':'count','field':None,'as':'count_entities'},{'function':'sum','field':'value','as':'total_value'}]})
                source=plan.filter('complete_groups',source,predicate('count_entities','eq',2),'Table')
            else:
                source=plan.project('rank_fields',enriched,list(fields)+['score'])
                source=plan.top('top',source,2,[{'field':'score','direction':'desc'},{'field':'paper_id','direction':'asc'}])
        if number==4:
            paths=plan.add('paths','graph_shortest_path','bfs',{'graph':g,'seeds':'$input.seeds'},{'target':list(range(1,n)),'weight_field':'weight'},{'paths':'PathSet'})
            source=plan.add('combine','project','column_view',{'paths':paths,'facts':source},{'representation':'record','field_map':{'paths':'paths','facts':'facts'}},{'rows':'Record'})
        if number==12:
            old=[]
            for doc in docs:
                old.append(canonical_document(doc['document_id'],'engineering-docs-v0','Stale version',[{'heading':'Old','text':'Condition A is refuted. Value 9999 mg.'}]))
            sources['stale_documents']=old;stale=deepcopy(document_descriptor('stale_documents',old));stale['revision']='engineering-docs-v0';datasets.append(stale)
    task['datasets']=datasets
    return {'task':task,'plan':plan.end(source),'rows':sources,'schemas':schemas,'template_id':template,'base_id':base,'condition':condition,
        'seed':seed,'axis':'controlled_candidate_count','comparison':'mixed_semantics','output_fields':out.get('fields',[]),
        'semantic_stages':stages,'replay':{'revision':'full001-engineering-replay-1','service_id':'engineering-replay-e0','responses':responses},
        'expected_args':{'template':number,'documents':docs,'graph':graph,'mapping':mappings},'formal_gold_reviewed':False}
