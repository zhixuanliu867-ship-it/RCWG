"""Versioned public candidate grammar, explicit materialization and alpha deduplication."""
from copy import deepcopy
from itertools import product
import math
from rcwg_full.compiler import FullCompiler
from rcwg_full.evidence import digest

CHOICES={'filter':['vectorized','scalar'],'project':['column_view','copy'],
         'top_k':['streaming_heap','full_sort'],'aggregate':['hash_group','sorted_group'],
         'join':['hash','sort_merge','block_nested'],'deduplicate':['hash','sort_unique'],
         'sort':['in_memory','external_merge'],'set_op':['hash','sorted_merge'],
         'graph_neighbors':['csr','indexed_adjacency'],'graph_reachability':['bfs','dfs'],
         'graph_filter':['edge_mask','index_filter'],'broadcast':['shared_ref','copy_each'],
         'read_documents':['batched','per_document']}


def decision_identity(plan):
    """Canonicalize all local labels/captures, retaining actual edges and choices."""
    value=deepcopy(plan);value.pop('task_id',None)
    aliases={name:'e'+str(i) for i,name in enumerate(value['external_inputs'])}
    value['external_inputs']={aliases[k]:v for k,v in value['external_inputs'].items()}
    def region(nodes,scope,bindings=None):
        ids={n['id']:'n'+str(i) for i,n in enumerate(nodes)}
        bound={name:'b'+str(i) for i,name in enumerate(bindings or {})}
        def reference(ref):
            if ref.startswith('$input.'):return '$input.'+aliases[ref[7:]]
            if ref.startswith('$bound.'):return '$bound.'+bound[ref[7:]]
            a,b=ref.split('.',1);return ids[a]+'.'+b
        for node in nodes:
            node['id']=ids[node['id']];node['inputs']={k:reference(v) for k,v in node['inputs'].items()}
            if 'after' in node:node['after']=[ids[x] for x in node['after']]
            for binding in node.get('param_bindings',[]):binding['ref']=reference(binding['ref'])
            for label,r in node.get('regions',{}).items():
                original=dict(r['bindings']);newbindings={name:ref if ref in {'$item','$state'} else reference(ref) for name,ref in original.items()}
                childref,childbound=region(r['nodes'],scope+label,newbindings)
                r['bindings']={childbound[k]:v for k,v in newbindings.items()};r['yield']={k:childref(v) for k,v in r['yield'].items()}
        return reference,bound
    ref,_=region(value['nodes'],'root');value['result']=ref(value['result'])
    return digest(value)


def materialized_scan(plan,storage):
    if storage=='stream':return deepcopy(plan)
    plan=deepcopy(plan);nodes=plan['nodes'];scan=next((n for n in nodes if n['operator']=='scan'),None)
    if scan is None:return None
    old=scan['id']+'.rows';ids={n['id'] for n in nodes}
    prefix='candidate_buffer'
    while prefix in ids or prefix+'_read' in ids:prefix+='x'
    replacement=prefix+'_read.rows'
    def substitute(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in {'inputs','bindings'}:value[k]={p:replacement if ref==old else ref for p,ref in v.items()}
                elif k=='param_bindings':
                    for binding in v:
                        if binding['ref']==old:binding['ref']=replacement
                else:substitute(v)
        elif isinstance(value,list):
            for v in value:substitute(v)
    substitute(plan)
    material={'id':prefix,'operator':'materialize','implementation':storage,'inputs':{'rows':old},
        'params':{'format':'arrow_ipc'},'outputs':{'rows':'Table'},'storage':storage}
    read={'id':prefix+'_read','operator':'stream_read','implementation':'arrow_batches','inputs':{'artifact':prefix+'.rows'},
        'params':{'batch_size':7},'outputs':{'rows':'Stream[Record]'},'storage':'stream'}
    at=nodes.index(scan)+1;nodes[at:at]=[material,read]
    if plan['result']==old:plan['result']=replacement
    return plan


def candidates(task,baseline,*,max_candidates=32):
    if not 8<=max_candidates<=32:raise ValueError('CANDIDATE_LIMIT')
    # Frozen axis order is chosen before any measurements; vary entire registered
    # operator classes and explicit stream/memory/disk, not names or hidden data.
    present={n['operator'] for n in baseline['nodes']}
    axes=[op for op in ['top_k','aggregate','join','project','filter','deduplicate','sort','set_op','graph_neighbors','graph_reachability','graph_filter','broadcast','read_documents'] if op in present]
    axes=axes[:4];result=[];seen=set();rejected=[]
    for choices,storage in product(product(*(CHOICES[op] for op in axes)),['stream','memory','disk']):
        variant=materialized_scan(baseline,storage)
        if variant is None:continue
        decisions=dict(zip(axes,choices))
        for node in variant['nodes']:
            if node['operator'] in decisions:node['implementation']=decisions[node['operator']]
        report=FullCompiler().compile(task,variant)
        if report['status']!='IR_VALIDATED':rejected.append({'decisions':{**decisions,'storage':storage},'diagnostics':report['diagnostics']});continue
        identity=decision_identity(variant)
        if identity in seen:continue
        seen.add(identity);result.append({'candidate_id':identity,'plan_hash':digest(variant),'plan':variant,'decisions':{**decisions,'storage':storage},'feasibility':'STATIC_PASS_REQUIRES_EXECUTION_AND_BUDGET'})
        if len(result)==max_candidates:break
    if len(result)<8:raise ValueError('INSUFFICIENT_DISTINCT_EXECUTABLE_GRAMMAR')
    return {'profile':'FULL001_REFERENCE_GRAMMAR_1','task_hash':digest(task),'definition_hash':digest([{'id':c['candidate_id'],'decisions':c['decisions']} for c in result]),
        'candidates':result,'statically_rejected':rejected,'data_used':'PUBLIC_TASK_ONLY','measurement_used':False,'formal_frozen':False}


def public_rule(features):
    required=['n','k','left_rows','right_rows','row_bytes','ram_bytes','sorted_inputs','independent_copy_required']
    if any(k not in features for k in required):raise ValueError('PUBLIC_FEATURES_MISSING')
    n,k,l,r,w,ram=(features[x] for x in required[:6])
    if any(type(x) not in {int,float} or not math.isfinite(x) or x<0 for x in (n,k,l,r,w,ram)):raise ValueError('PUBLIC_FEATURE_RANGE')
    if any(type(features[k]) is not bool for k in required[6:]):raise ValueError('PUBLIC_FEATURE_RANGE')
    build='left' if l<r else 'right';estimated=min(l,r)*w
    join='block_nested' if l*r<=4096 else 'hash' if estimated<=ram/2 else 'sort_merge'
    return {'top_k':'streaming_heap' if 2*k<n else 'full_sort','join':join,'build_side':build,
            'broadcast':'copy_each' if features['independent_copy_required'] else 'shared_ref',
            'estimated_build_bytes':estimated,'merge_sort_required':not features['sorted_inputs'],
            'budget_verified':False,'uses_hidden_data':False}
