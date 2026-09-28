"""Public, versioned diagnostic interventions; no outcomes or hidden gold as input."""
from copy import deepcopy
from rcwg_full.compiler import FullCompiler
from rcwg_full.evidence import digest

REGISTRY={
 'revision':'FULL001_DIAGNOSTIC_TRANSFORMS_1','formal_frozen':False,'selection_data':'PUBLIC_TASK_AND_PLAN_ONLY',
 'transforms':{
  'E3_P':{'intervention':'fixed_legal_implementations','invariants':['task','node_identity','edges','parameters','budgets'],'stage':'before_execution'},
  'E3_S':{'intervention':'one_cpu_kernel_and_serial_maps','invariants':['task','computation','parameters','budgets'],'stage':'scheduler_profile'},
  'E4_window512':{'intervention':'token_window','size':512,'overlap':64,'invariants':['task','E0','question','fields'],'stage':'before_execution'},
  'E4_window2048':{'intervention':'token_window','size':2048,'overlap':256,'invariants':['task','E0','question','fields'],'stage':'before_execution'},
  'E4_neighbors1':{'intervention':'gather_window_one','invariants':['task','E0','question','fields'],'stage':'before_execution'},
  'E4_shared_prefix':{'intervention':'share_identical_document_reads','invariants':['task','E0','question','selected_document_fields'],'stage':'before_execution'},
  'alpha_rename':{'intervention':'rename_node_identifiers','invariants':['computation','dataflow','budgets'],'stage':'before_execution'},
  'materialize_memory':{'intervention':'explicit_arrow_materialization','invariants':['logical_rows','task','budgets'],'stage':'before_execution'},
  'materialize_disk':{'intervention':'explicit_arrow_disk_materialization','invariants':['logical_rows','task','budgets'],'stage':'before_execution'},
  'broadcast_copy':{'intervention':'independent_payload_copies','invariants':['logical_values','task','budgets'],'stage':'before_execution'}
 }}

FIXED={'scan':['sequential'],'filter':['vectorized'],'project':['column_view'],'top_k':['streaming_heap'],
       'join':['hash'],'aggregate':['hash_group'],'deduplicate':['hash'],'sort':['in_memory'],'set_op':['hash'],
       'graph_neighbors':['csr'],'graph_reachability':['bfs'],'graph_shortest_path':['bfs','dijkstra'],
       'graph_filter':['edge_mask'],'read_documents':['batched'],'broadcast':['shared_ref']}


def walk(nodes):
    for node in nodes:
        yield node
        for region in node.get('regions',{}).values():yield from walk(region['nodes'])


def substitute_root(plan,replacements):
    def reference(ref):
        if ref.startswith('$'):return ref
        name,port=ref.split('.',1);return replacements.get(name,name)+'.'+port
    def nested(nodes,root=False):
        for node in nodes:
            if root:
                node['inputs']={k:reference(v) for k,v in node['inputs'].items()}
                if 'after' in node:node['after']=list(dict.fromkeys(replacements.get(v,v) for v in node['after']))
                for binding in node.get('param_bindings',[]):binding['ref']=reference(binding['ref'])
            for region in node.get('regions',{}).values():
                if root:region['bindings']={k:reference(v) if v not in {'$item','$state'} else v for k,v in region['bindings'].items()}
                nested(region['nodes'])
    nested(plan['nodes'],True);plan['result']=reference(plan['result'])


def transform(task,plan,transform_id):
    if transform_id not in REGISTRY['transforms']:raise ValueError('DIAGNOSTIC_TRANSFORM_UNKNOWN')
    baseline=FullCompiler().compile(task,plan)
    if baseline['status']!='IR_VALIDATED':raise ValueError('DIAGNOSTIC_PARENT_NOT_VALID')
    result={'transform_id':transform_id,'registry_hash':digest(REGISTRY),'parent_plan_hash':digest(plan),'task_hash':digest(task),
            'budget_hash':digest(task['resources']),'status':'TRANSFORM_NOT_APPLICABLE','reason':None,'execution_profile':{},
            'information_witness_checkpoint':'REQUIRED_ACTUAL_PRESENTED_CONTEXT_AND_SOURCE_CITATIONS','formal_frozen':False}
    variant=deepcopy(plan);changes=[]
    if transform_id=='E3_P':
        for node in walk(variant['nodes']):
            old=node['implementation']
            for choice in FIXED.get(node['operator'],[]):
                node['implementation']=choice
                if FullCompiler().compile(task,variant)['status']=='IR_VALIDATED':break
                node['implementation']=old
            if node['implementation']!=old:changes.append({'node_id':node['id'],'old':old,'new':node['implementation']})
        # Already-fixed plans remain a valid, explicitly reported no-op arm.
    elif transform_id=='E3_S':
        result['execution_profile']={'revision':'FULL001_SCHEDULE_1','cpu_kernel_concurrency':1,'map_parallelism':1}
        for node in walk(variant['nodes']):
            if node['operator']=='map':node.setdefault('resources',{})['max_parallelism']=1
        changes.append({'scheduler_profile':result['execution_profile']})
    elif transform_id.startswith('E4_window'):
        spec=REGISTRY['transforms'][transform_id]
        for node in walk(variant['nodes']):
            if node['operator']=='split_documents' and node['implementation']=='token_window':
                if any(b['parameter'] in {'size','overlap'} for b in node.get('param_bindings',[])):
                    result['reason']='DYNAMIC_WINDOW_BINDING';return result
                changes.append({'node_id':node['id'],'prior':deepcopy(node['params']),'size':spec['size'],'overlap':spec['overlap']})
                node['params'].update(size=spec['size'],overlap=spec['overlap'])
        if not changes:result['reason']='NO_TOKEN_WINDOW_OPERATOR';return result
    elif transform_id=='E4_neighbors1':
        for node in walk(variant['nodes']):
            if node['operator']=='gather_context' and node['implementation']=='neighbors':
                if any(b['parameter']=='window' for b in node.get('param_bindings',[])):
                    result['reason']='DYNAMIC_GATHER_BINDING';return result
                changes.append({'node_id':node['id'],'prior':node['params'].get('window'),'window':1});node['params']['window']=1
        if not changes:result['reason']='NO_GATHER_OPERATOR';return result
    elif transform_id=='E4_shared_prefix':
        groups={};replaced={}
        for node in variant['nodes']:
            if node['operator']!='read_documents' or node.get('after') or node.get('param_bindings'):continue
            key=digest({'inputs':node['inputs'],'params':node['params'],'outputs':node['outputs']})
            if key in groups:replaced[node['id']]=groups[key]
            else:groups[key]=node['id']
        if not replaced:result['reason']='NO_IDENTICAL_PUBLIC_READ_PREFIX';return result
        substitute_root(variant,replaced)
        variant['nodes']=[node for node in variant['nodes'] if node['id'] not in replaced]
        # The shared read is a concrete DocumentStream value. Cache retains its
        # complete declared fields for every consumer; source selection is unchanged.
        from rcwg_full.reference.candidates import document_prefix
        variant=document_prefix(variant,'memory','shared_ref');changes.append({'shared_nodes':replaced})
    elif transform_id=='alpha_rename':
        replacements={node['id']:'control_'+str(i) for i,node in enumerate(variant['nodes'])}
        substitute_root(variant,replacements)
        for node in variant['nodes']:node['id']=replacements[node['id']]
        changes.append({'node_ids':replacements})
    elif transform_id.startswith('materialize_'):
        from rcwg_full.reference.candidates import materialized_scan
        variant=materialized_scan(variant,transform_id.split('_')[1])
        if variant is None:result['reason']='NO_TABLE_SCAN';return result
        changes.append({'storage':transform_id.split('_')[1]})
    elif transform_id=='broadcast_copy':
        for node in walk(variant['nodes']):
            if node['operator']=='broadcast':node['implementation']='copy_each';changes.append({'node_id':node['id']})
        if not changes:result['reason']='NO_BROADCAST';return result
    checked=FullCompiler().compile(task,variant)
    if checked['status']!='IR_VALIDATED':
        result.update(reason='TYPE_OR_WORKIR_BOUNDARY',diagnostics=checked['diagnostics']);return result
    result.update(status='TRANSFORMED',plan=variant,plan_hash=digest(variant),changes=changes,no_op=variant==plan and not result['execution_profile'],
                  source_task_unchanged=True,budget_unchanged=True,semantic_preservation='REQUIRES_INDEPENDENT_EXECUTION_AND_INFORMATION_WITNESS')
    return result


def public_guidance(task):
    """The E3-L extra information is a public contract restatement, never a solution."""
    return {'revision':'FULL001_E3_L_GUIDANCE_1','task_hash':digest(task),'information_scope':'PUBLIC_CONTRACT_GUIDANCE_EXTRA_TO_MAIN_PROTOCOL',
            'output_contract':deepcopy(task['output_contract']),'resources':deepcopy(task['resources']),
            'requirements':['Preserve all declared output rows, including unknown values required by the contract.',
                            'Keep every graph and document identity at its declared domain and revision.',
                            'Use explicit materialization and sharing where the physical plan reuses data.',
                            'Preserve source spans for every semantic field and use only presented context.',
                            'Submit one physical WorkIR plan within the unchanged resource and node bounds.'],
            'uses_hidden_data':False,'uses_model_outcomes':False,'formal_frozen':False}
