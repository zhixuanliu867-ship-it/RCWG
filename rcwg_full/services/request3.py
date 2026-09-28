"""One coherent public grammar; old messages/examples stay byte-identical."""
import json
from copy import deepcopy
from rcwg_full.evidence import ROOT,read,sha,canonical,digest
from rcwg_full.compiler.contracts import REGISTRY
from rcwg_full.compiler.operators import BINDABLE
from rcwg_full.compiler import FullCompiler
from rcwg_full.compiler.public_task import validate_public_task
from .requests import assemble

# These concise cards mirror executable contracts, including COMPAT1 overloads.
# Registry membership and required/optional names are derived, never copied from
# the stale illustrative catalog. Compiler regressions independently check them.
DETAILS={
 'scan':('source:DatasetRef[Table]','rows:Stream[Record]','columns:nonempty unique field array; predicate:Bool expression AST'),
 'filter':('rows:Table|Stream|EvidenceTable|DocumentStream|ChunkStream','rows:same representation','predicate:Bool/Nullable[Bool] AST; retain only true'),
 'project':('rows:row-readable, or named inputs with field_map','rows:same|Table|Record|Set|NodeSet|IDSet','columns:field array (nonempty columns and/or expressions unless field_map packing); source_view:rows|nodes|edges|ids|paths; representation:same|table|record|set; expressions:field->typed AST; field_map:output field->input port (record packing only)'),
 'join':('left,right:Table|Stream|EvidenceTable','rows:Table','keys:nonempty [{left:field,right:field}]; join_type:inner|left|right|full|semi|anti; build_side:left|right'),
 'aggregate':('rows:Table|Stream|EvidenceTable','rows:Table','group_by:field array (may be empty); aggregates:nonempty [{function:count|sum|min|max|mean,field:field or null,as:unique name}]'),
 'deduplicate':('rows:Table|Stream|EvidenceTable','rows:same representation','keys:nonempty field array; keep:first|last'),
 'sort':('rows:Table|Stream|EvidenceTable','rows:Table','keys:nonempty [{field:name,direction:asc|desc,nulls:first|last(optional)}]'),
 'top_k':('rows:Table|Stream|EvidenceTable','rows:Table','k:Int64>=0; keys:sort-key array; partition_by:field array optional'),
 'set_op':('left,right:same Set|NodeSet|IDSet','items:same representation','mode:union|intersection|difference; matching element/domain/revision'),
 'graph_neighbors':('graph:Graph|GraphView,seeds:NodeSet','edges:EdgeStream','direction:in|out|both; edge_types:string array of declared relations'),
 'graph_reachability':('graph:Graph|GraphView,seeds:NodeSet','nodes:NodeSet','max_hops:Int64>=0; direction:in|out|both'),
 'graph_shortest_path':('graph:Graph|GraphView,seeds:NodeSet','paths:PathSet','target:one node ID or nonempty array of node IDs; weight_field:numeric field or null; bfs equal weights, dijkstra nonnegative'),
 'graph_filter':('graph:Graph|GraphView','graph:GraphView','predicate:Bool AST on edge fields/edge.FIELD/node.FIELD'),
 'graph_subgraph':('graph:Graph|GraphView,nodes:NodeSet for induced or edges:EdgeStream for edge_selected','graph:Graph','mode:must equal implementation'),
 'read_documents':('index:DocumentIndex,ids:IDSet|RankedIDSet|one-column Table with explicit ID mapping','documents:DocumentStream','fields:nonempty public field array (select canonical_text or sections before semantic use); batch_size:Int64>=1; id_field:string when Table'),
 'text_retrieve':('index:DocumentIndex','ids:RankedIDSet','query:nonempty Utf8; limit:Int64>=0; offset:Int64>=0 optional'),
 'split_documents':('documents:DocumentStream','chunks:ChunkStream','size:Int64>=1; overlap:Int64 in [0,size-1]'),
 'gather_context':('chunks:ChunkStream','chunks:ChunkStream','window:Int64>=0'),
 'semantic_extract':('documents:DocumentStream|ChunkStream','evidence:EvidenceTable','field_schema:nonempty field->type descriptor, JSON scalars/Nullable/List/Record; context_budget:Int64>=1; question:nonempty Utf8 optional; fixed E0 only'),
 'evidence_merge':('evidence:EvidenceTable','evidence:EvidenceTable','keys:nonempty field array; conflict_policy:keep_all|reject|declared_priority; priority_rule:sort-key array required only for declared_priority'),
 'evidence_validate':('evidence:EvidenceTable,index:DocumentIndex','evidence:EvidenceTable','strict:Bool'),
 'materialize':('rows:Stream[Record]','rows:Table','format:arrow_ipc|parquet; storage must equal memory or disk implementation'),
 'stream_read':('artifact:row-readable artifact or ArtifactRef','rows:Stream[Record]','batch_size:Int64>=1'),
 'broadcast':('artifact:artifact value/ref','one output port per consumers entry; Stream for stream input, otherwise ArtifactRef','consumers:nonempty unique identifier array; outputs keys exactly consumers'),
 'release':('artifact:artifact value/ref','done:ControlToken','no parameters; wait for all consumers before release'),
 'cache':('artifact:artifact value/ref','artifact:ArtifactRef','key_fields:nonempty public field array; same-run cache only'),
 'map':('rows:Stream[Record]','region-derived output ports','no parameters; explicit body region and $bound aliases'),
 'branch':('condition:Bool|Nullable[Bool], optional named captures','region-derived joined output ports','predicate:Bool AST; explicit then/else regions; schemas/domain must join'),
 'loop':('state:typed value, optional captures','region-derived output ports','condition:Bool AST continue while true; max_iterations:Int64 1..16; explicit body region, state feedback'),
 'collect':('rows:Stream[Record]','rows:Table','limit:Int64>=0; exceeding limit fails, never silently truncates'),
 'emit':('rows:representation matching TASK.output_contract','result:Result','output_contract:STRING naming TASK.output_contract.id/contract_id (not object)'),
 'stats':('source:DatasetRef','stats:Stats','fields:nonempty public field array; sample_size:Int64>=1 for sample; only generation_probe with I2'),
}
EXTRA={'project':['source_view','representation','expressions','field_map'],'top_k':['partition_by'],'text_retrieve':['offset'],'semantic_extract':['question']}

def operator_cards():
    if set(DETAILS)!=set(REGISTRY):raise ValueError('REQUEST3_CATALOG_COVERAGE')
    cards=[]
    for name,(implementations,required,optional) in REGISTRY.items():
        inputs,outputs,params=DETAILS[name]
        cards.append({'operator':name,'implementations':list(implementations),'inputs':inputs,'outputs':outputs,
            'required_parameters':[] if name=='project' else list(required),'optional_parameters':list(optional)+EXTRA.get(name,[]),
            'parameter_contract':params,'bindable_value_parameters':BINDABLE.get(name,{})})
    return cards

def neutral_example():
    task={'task_id':'request3-public-BOOT_ONLY','instruction':'Return all rows of the public flag table.',
        'datasets':[{'id':'dataset:flags:v1','kind':'table','revision':'example-v1','schema_source':'public:BOOT_ONLY',
          'schema':{'flag':'Bool'},'stats':{'row_count':2},'indexes':[]}],
        'resources':{'cpu_slots':1,'worker_memory_limit_bytes':104857600,'wall_timeout_s':60},
        'output_contract':{'type':'records','mode':'exact','id':'all_flags','fields':['flag'],'schema':{'flag':'Bool'}},
        'tool_catalog_id':'rcwg-operators-1.0'}
    plan={'ir_version':'1.0','task_id':task['task_id'],'external_inputs':{'flags':'dataset:flags:v1'},'nodes':[
        {'id':'read','operator':'scan','implementation':'sequential','inputs':{'source':'$input.flags'},
         'params':{'columns':['flag']},'outputs':{'rows':'Stream[Record]'},'storage':'stream'},
        {'id':'finish','operator':'emit','implementation':'json_artifact','inputs':{'rows':'read.rows'},
         'params':{'output_contract':'all_flags'},'outputs':{'result':'Result'},'storage':'memory'}],
        'result':'finish.result'}
    proof=FullCompiler().compile(task,plan)
    if proof['status']!='IR_VALIDATED':raise ValueError('REQUEST3_PUBLIC_EXAMPLE_INVALID:'+str(proof['diagnostics']))
    return {'purpose':'BOOT_ONLY grammar example, unrelated to benchmark answers','task':task,'workflow':plan}

def assemble_request3(task,binding,**kwargs):
    # Reuse the same frozen provider decoding/output limits and validation.
    result=assemble(task,binding,**kwargs)
    checked=validate_public_task(task)['normalized_task'];contract=checked['output_contract']
    names={contract.get('id'),contract.get('contract_id')}-{None}
    if contract.get('type')=='ordered_records' and contract.get('mode')=='exact':names.add('exact_ordered_topk_v1')
    paths=['prompts/full001/request3.txt','prompts/full001/compat1.txt','specs/full001/schemas/workflow.compat1.schema.json',
      'specs/spec001b/generation_schema_addendum.json','rcwg_full/services/request3.py','rcwg_full/compiler/contracts.py',
      'rcwg_full/compiler/operators.py','rcwg_full/compiler/typesystem.py','rcwg_full/compiler/core.py']
    sources={p:read(ROOT/p) for p in paths}
    rules={'profile':'FULL001_REQUEST_3','compiler_profile':'RCWG_FULL001_COMPAT1','operators':operator_cards(),
      'wire_schema':json.loads(sources[paths[2]]),'stage_contracts':json.loads(sources[paths[3]]),
      'neutral_example':neutral_example()}
    public={'TASK':checked,'stage':kwargs['stage'],'protocol':kwargs['protocol'],
      'allowed_source_ids':[d['id'] for d in checked['datasets']],'allowed_emit_contract_names':sorted(names)}
    if kwargs.get('logical') is not None:public['completed_logical_contract']=kwargs['logical']
    if kwargs.get('guidance') is not None:public['public_guidance']=kwargs['guidance']
    body={'systemInstruction':{'parts':[{'text':sources[paths[0]].decode()},{'text':sources[paths[1]].decode()},
          {'text':canonical(rules).decode()}]},'contents':[{'role':'user','parts':[{'text':canonical(public).decode()}]}],
          'generationConfig':deepcopy(result['body']['generationConfig'])}
    result.update(schema_version='FULL001_REQUEST_3',body=body,body_hash=digest(body),
        source_hashes={p:sha(raw) for p,raw in sources.items()},input_bytes=len(canonical(body)),input_characters=len(canonical(body).decode()))
    return result
