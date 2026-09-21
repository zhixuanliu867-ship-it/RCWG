"""Controlled graph tasks with explicit node, edge, path and document-ID bridges."""
import random
import json
from .templates import Plan,scalar,predicate,both,descriptor,task_shell,seed_for


def f3(template,base,condition):
    if condition not in {'C0','C1','C2','C3'}:raise ValueError('CONDITION')
    number=int(template[-2:])
    if number not in range(1,13):raise ValueError('TEMPLATE_UNREGISTERED')
    seed=seed_for(template,base);rng=random.Random(seed);n=67 if condition=='C1' else 23
    revision='engineering-graph-v1';domain='controlled-graph-'+template
    ns={'node_id':'Int64','eligible':'Bool','value':'Int64','label':'Utf8'}
    es={'edge_id':'Int64','src':'Int64','dst':'Int64','type':'Utf8','time':'Int64','weight':'Float64'}
    nodes=[{'node_id':i,'eligible':i%4!=0,'value':rng.randrange(1000),'label':f'节点{base}·{i}'} for i in range(n)]
    arcs=[]
    if number==11:arcs=[(a,b) for a in range(n-1) for b in range(n-1) if a!=b and (a+b+base)%3!=0]
    else:
        arcs=[(i,i+1) for i in range(n-2) if i!=n//2-1]+[(2,0),(0,2),(0,1),(n-3,n//2)]
    edges=[{'edge_id':i,'src':a,'dst':b,'type':'allowed' if i%3 else 'other','time':(i*7+base)%90,
            'weight':float(rng.randrange(1,6)) if number in {3,11} else 1.} for i,(a,b) in enumerate(arcs)]
    graph={'domain':domain,'revision':revision,'directed':True,'nodes':nodes,'edges':edges,
           'edge_index':sorted(range(len(edges)),key=lambda i:(edges[i]['time'],i))}
    public_graph={'id':'dataset:graph','kind':'graph','revision':revision,'domain':domain,'schema_source':'controlled-graph-generator-v1',
        'node_schema':ns,'edge_schema':es,'node_id_type':'Int64','node_id_field':'node_id','source_field':'src','target_field':'dst','directed':True,
        'weight_field':'weight','weight_nonnegative':True,'weight_equal':number not in {3,11},
        'indexes':[{'id':'edge-time','kind':'sorted','fields':['time'],'revision':revision,'source':'controlled-preparation'}],
        'stats':{'node_count':n,'edge_count':len(edges)}}
    seeds=[0,n-3] if number==6 else [n-3] if number==5 else [0]
    targets=[0,n-2,n-1] if number==5 else [2,n//2-1,n-1]
    sources={'graph':graph,'seeds':seeds};schemas={};datasets=[public_graph]
    def ids(alias,values):
        sources[alias]=values;datasets.append({'id':'dataset:'+alias,'kind':'node_set','revision':revision,'domain':domain,
            'schema_source':'controlled-graph-generator-v1','id_type':'Int64','stats':{'item_count':len(values)}})
    ids('seeds',seeds)
    instructions={1:'沿有向 out 边从 seeds 至多 3 跳，含深度零节点，返回 NodeSet。',
        2:'单位权有向图各 target 最短距离和任一合法最短路径；不可达明确表示。',
        3:'非负带权有向图各 target 最短距离和任一合法最短路径，权重字段 weight。',
        4:'仅沿 time 在 [10,70) 且 type=allowed 的边，从 seeds 求 4 跳 out 可达集合。',
        5:'仅沿有向 out 边到 targets 求最短路径，不得把反向边视作正向边。',
        6:'对全部 seeds 求 3 跳 out 可达并集，保留图 domain 与 revision。',
        7:'仅沿 type=allowed 的边求 seeds 的 4 跳 out 可达集合。',
        8:'按公开 mode 返回 nodes 诱导或 explicit_edges 明确边选子图，以 graph 字段输出。',
        9:'过滤 type=allowed 的边，求 4 跳 out 可达；通过 node_doc.node_id 到 document_id 显式映射返回文档 ID 集。',
        10:'一次读取 queries q0=[0,1], q1=[2,3] 的共享 out 邻居边，按 src 属于各 query 返回完整边表，命名 q0/q1。',
        11:'选 eligible=true 节点，并限制 weight<=3，返回包含全部合格节点和全部合格端点间边的受限子图。',
        12:'输出 targets 合法最短路径及每个路径节点的公开属性、每条路径边的完整证据；必须同一 revision。'}
    graph_type={'kind':'Graph','schema':es,'domain':domain,'revision':revision}
    output={'id':'result','type':'node_set','mode':'exact','domain':domain,'revision':revision,'item_type':'Int64'}
    comparison='set';expected_args={'number':number,'graph':graph,'seeds':seeds,'targets':targets}
    if number in {2,3,5}:
        output={'id':'result','type':'paths','mode':'exact','domain':domain,'revision':revision};comparison='paths'
    if number in {8,11}:output={'id':'result','type':'record','mode':'exact','fields':['graph'],'schema':{'graph':graph_type}};comparison='graph_record'
    if number==9:output={'id':'result','type':'id_set','mode':'exact','domain':'controlled-documents','revision':revision,'item_type':'Utf8'}
    if number==10:
        table_type={'kind':'Table','schema':es,'domain':domain,'revision':revision}
        output={'id':'result','type':'record','mode':'exact','fields':['q0','q1'],'schema':{'q0':table_type,'q1':table_type}};comparison='query_edges'
    if number==12:
        path_type={'kind':'PathSet','item':'Int64','domain':domain,'revision':revision}
        attr_schema={'target':'Int64','node_id':'Int64','ordinal':'Int64','value':'Int64','source_revision':'Utf8'}
        evidence_schema={'target':'Int64','edge_ref':'Int64','edge_ordinal':'Int64',**es}
        output={'id':'result','type':'record','mode':'exact','fields':['paths','attributes','edges'],
            'schema':{'paths':path_type,'attributes':{'kind':'Table','schema':attr_schema},'edges':{'kind':'Table','schema':evidence_schema}}};comparison='enriched_paths'
    task=task_shell(template,base,condition,instructions[number],output);plan=Plan(task['task_id'])
    if number in {2,3,5,12}:task['instruction']+=' targets='+json.dumps(targets)
    plan.value['external_inputs'].update(graph='dataset:graph',seeds='dataset:seeds');g='$input.graph';source=None
    if number in {4,7,9,11}:
        expr=predicate('weight','le',3.) if number==11 else predicate('type','eq','allowed')
        if number==4:expr=both(expr,predicate('time','ge',10),predicate('time','lt',70))
        g=plan.add('graph_view','graph_filter','edge_mask',{'graph':g},{'predicate':expr},{'graph':'GraphView'})
    if number in {1,4,6,7,9}:
        source=plan.add('reachable','graph_reachability','bfs',{'graph':g,'seeds':'$input.seeds'},
                        {'max_hops':4 if number in {4,7,9} else 3,'direction':'out'},{'nodes':'NodeSet'})
    if number in {2,3,5,12}:
        source=plan.add('paths','graph_shortest_path','dijkstra' if number==3 else 'bfs',{'graph':g,'seeds':'$input.seeds'},
            {'target':targets,'weight_field':'weight'},{'paths':'PathSet'})
    if number==8:
        mode='induced' if base%2==0 else 'edge_selected';expected_args['mode']=mode;selection=[0,1,2,n-1] if mode=='induced' else edges[:2]
        if mode=='induced':ids('selection',selection)
        else:
            sources['selection']=selection;datasets.append({'id':'dataset:selection','kind':'edge_stream','schema':es,'revision':revision,'domain':domain,
                'schema_source':'controlled-edge-selection','stats':{'edge_count':len(selection)}})
        plan.value['external_inputs']['selection']='dataset:selection';expected_args['selection']=selection
        source=plan.add('subgraph','graph_subgraph',mode,{'graph':g,'nodes' if mode=='induced' else 'edges':'$input.selection'},{'mode':mode},{'graph':'Graph'})
        task['instruction']+=' mode='+mode
    if number==9:
        mappings=[{'node_id':i,'document_id':f'doc-{base}-{i*3+j}','source_revision':revision} for i in range(n) for j in range(2 if i%4==0 else 1)]
        schema={'node_id':'Int64','document_id':'Utf8','source_revision':'Utf8'};sources['node_doc']=mappings;schemas['node_doc']=schema
        public=descriptor('node_doc',schema,mappings);public.update(revision=revision,id_field='document_id',id_domain='controlled-documents');datasets.append(public)
        left=plan.project('node_rows',source,['id'],source_view='ids',representation='table');right=plan.scan('node_doc',schema)
        joined=plan.add('map_ids','join','hash',{'left':left,'right':right},{'keys':[{'left':'id','right':'node_id'}],'join_type':'inner','build_side':'right'})
        source=plan.project('document_ids',joined,['document_id'],'IDSet',representation='set');expected_args['node_doc']=mappings
    if number==10:
        queries={'q0':[0,1],'q1':[2,3]};expected_args['queries']=queries;ids('query_union',[0,1,2,3]);plan.value['external_inputs']['query_union']='dataset:query_union'
        edges_ref=plan.add('neighbors','graph_neighbors','csr',{'graph':g,'seeds':'$input.query_union'},{'direction':'out','edge_types':[]},{'edges':'EdgeStream'})
        table=plan.project('edge_rows',edges_ref,list(es),source_view='edges',representation='table')
        stream=plan.add('edge_stream','stream_read','arrow_batches',{'artifact':table},{'batch_size':7},{'rows':'Stream[Record]'})
        material=plan.add('shared','materialize','memory',{'rows':stream},{'format':'arrow_ipc'},storage='memory')
        plan.add('fan','broadcast','shared_ref',{'artifact':material},{'consumers':['q0','q1']},{'q0':'ArtifactRef','q1':'ArtifactRef'})
        for label,seeds_for_query in queries.items():
            r=plan.add('read_'+label,'stream_read','arrow_batches',{'artifact':'fan.'+label},{'batch_size':7},{'rows':'Stream[Record]'})
            r=plan.filter('filter_'+label,r,predicate('src','in',seeds_for_query))
            plan.add('collect_'+label,'collect','bounded_collect',{'rows':r},{'limit':4096})
        source=plan.add('combine','project','column_view',{'q0':'collect_q0.rows','q1':'collect_q1.rows'},
            {'representation':'record','field_map':{'q0':'q0','q1':'q1'}},{'rows':'Record'})
    if number==11:
        table=plan.project('node_rows','$input.graph',list(ns),source_view='nodes',representation='table')
        selected=plan.filter('eligible',table,predicate('eligible','eq',True),'Table')
        node_ids=plan.project('node_ids',selected,['node_id'],'NodeSet',representation='set')
        source=plan.add('restricted','graph_subgraph','induced',{'graph':g,'nodes':node_ids},{'mode':'induced'},{'graph':'Graph'})
    if number in {8,11}:source=plan.add('wrap_graph','project','column_view',{'graph':source},{'representation':'record','field_map':{'graph':'graph'}},{'rows':'Record'})
    if number==12:
        paths=source;attributes=[{'attribute_node_id':r['node_id'],'value':r['value'],'source_revision':revision} for r in nodes]
        schema={'attribute_node_id':'Int64','value':'Int64','source_revision':'Utf8'};sources['attributes']=attributes;schemas['attributes']=schema;datasets.append(descriptor('attributes',schema,attributes))
        node_rows=plan.project('path_nodes',paths,['target','node_id','ordinal'],source_view='nodes',representation='table')
        attrs=plan.scan('attributes',schema)
        joined=plan.add('joined_attributes','join','hash',{'left':node_rows,'right':attrs},{'keys':[{'left':'node_id','right':'attribute_node_id'}],'join_type':'inner','build_side':'right'})
        attr_result=plan.project('attribute_result',joined,list(attr_schema))
        edge_rows=plan.project('path_edges',paths,['target'],source_view='edges',representation='table',
            expressions={'edge_ref':{'field':'edge_id'},'edge_ordinal':{'field':'ordinal'}})
        edges_table=plan.project('graph_edges','$input.graph',list(es),source_view='edges',representation='table')
        edge_result=plan.add('joined_edges','join','hash',{'left':edge_rows,'right':edges_table},{'keys':[{'left':'edge_ref','right':'edge_id'}],'join_type':'inner','build_side':'right'})
        source=plan.add('combine','project','column_view',{'paths':paths,'attributes':attr_result,'edges':edge_result},
            {'representation':'record','field_map':{'paths':'paths','attributes':'attributes','edges':'edges'}},{'rows':'Record'})
        expected_args['attributes']=attributes
    task['datasets']=datasets
    return {'task':task,'plan':plan.end(source),'rows':sources,'schemas':schemas,'template_id':template,'base_id':base,'condition':condition,
            'seed':seed,'axis':'node_count','comparison':comparison,'expected_args':expected_args,'output_fields':output.get('fields',[])}
