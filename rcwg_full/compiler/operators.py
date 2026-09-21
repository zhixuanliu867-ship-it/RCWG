"""COMPAT1 additive contracts. Legacy validation is called for unchanged forms."""
from copy import deepcopy
from dataclasses import replace
from rcwg_spec.common import ContractError
from .typesystem import Type, row_schema, with_rows, unwrap_ref, type_json, check_declared
from .predicates import analyze_predicate
from .contracts import (validate_operator as legacy, REGISTRY, _object, _fields,
    _integer, _string, _enum, _mapped, _id_mappings, _ref, IDENT)


def fail(code, path):
    raise ContractError(code, path, 'COMPAT1 contract violation')


# Binding alters values, never static representation, service, authority or paths.
# The range is checked again after resolving the actual value in the worker.
BINDABLE = {
    'top_k': {'k': ('Int64', 1)},
    'text_retrieve': {'query': ('Utf8', 'binding'), 'limit': ('Int64', 1), 'offset': ('Int64', 0)},
    'semantic_extract': {'question': ('Utf8', 'binding'), 'context_budget': ('Int64', 1)},
    'graph_reachability': {'max_hops': ('Int64', 1)},
    'split_documents': {'size': ('Int64', 1024), 'overlap': ('Int64', 0)},
    'gather_context': {'window': ('Int64', 1)},
    'read_documents': {'batch_size': ('Int64', 1)},
    'stream_read': {'batch_size': ('Int64', 1)},
    'collect': {'limit': ('Int64', 1)},
    'stats': {'sample_size': ('Int64', 1)},
}


def bind_parameters(node, resolve, path):
    candidate, resolved = deepcopy(node), []
    allowed = BINDABLE.get(node['operator'], {})
    for i, binding in enumerate(node.get('param_bindings', [])):
        at = path + '/param_bindings/' + str(i)
        name = binding['parameter']
        if name not in allowed:
            fail('PARAMETER_BINDING_FORBIDDEN', at)
        typ = resolve(binding['ref']).type
        if 'field' in binding:
            if typ.kind != 'Record' or binding['field'] not in dict(typ.schema):
                fail('FIELD_NOT_FOUND', at + '/field')
            typ = dict(typ.schema)[binding['field']]
        expected, witness = allowed[name]
        if typ.kind != expected:
            fail('PARAMETER_TYPE', at)
        candidate['params'][name] = witness
        resolved.append({**binding, 'type':type_json(typ), 'range_check':'AFTER_RESOLUTION'})
    return candidate, resolved


def _view(source, view, path):
    source = unwrap_ref(source)
    if source.kind=='PathSet' and view in {'nodes','edges'}:
        field='node_id' if view=='nodes' else 'edge_id'
        item=source.item if view=='nodes' else source.metadata.get('edge_id_type')
        if item is None:fail('INPUT_METADATA_REQUIRED',path)
        return source,{'target':source.item,field:item,'ordinal':Type('Int64')}
    if view == 'rows':
        return source, row_schema(source, path)
    if view == 'edges' and source.kind in {'Graph','GraphView','EdgeStream'}:
        return source, dict(source.schema)
    if view == 'nodes' and source.kind in {'Graph','GraphView','NodeSet'}:
        schema = dict(source.metadata.get('node_schema', {}))
        schema['node_id'] = source.metadata.get('node_id_type', source.item or Type('Int64'))
        metadata={**source.metadata,'node_id_mappings':{'node_id':{'domain':source.domain,'revision':source.revision}}}
        return replace(source,metadata=metadata), schema
    if view == 'ids' and source.kind in {'Set','IDSet','RankedIDSet','NodeSet'}:
        return source, {'id':source.item}
    if view == 'paths' and source.kind == 'PathSet':
        return source, {'target':source.item, 'distance':Type('Nullable',item=Type('Float64')),
                        'reachable':Type('Bool'), 'nodes':Type('List',item=source.item),
                        'edges':Type('List',item=source.metadata.get('edge_id_type',Type('Utf8')))}
    fail('TYPE_MISMATCH', path)


def _project(node, inputs, path):
    params = node['params']
    _object(params, set(), {'columns','source_view','representation','expressions','field_map'}, path+'/params')
    impl = node['implementation']
    if impl not in REGISTRY['project'][0]: fail('UNKNOWN_IMPLEMENTATION',path)
    representation = params.get('representation','same')
    _enum(representation, {'same','table','record','set'}, path+'/params/representation')
    obligations, aliases = [], {}
    if 'field_map' in params:
        mapping = params['field_map']
        if representation != 'record' or set(params) != {'representation','field_map'}:
            fail('PARAMETER_UNKNOWN',path+'/params')
        if type(mapping) is not dict or not mapping or set(mapping.values()) != set(inputs) or len(mapping)!=len(inputs):
            fail('PORT_MISMATCH',path+'/params/field_map')
        if not all(IDENT.fullmatch(k) for k in mapping): fail('PARAMETER_RANGE',path)
        typ = Type('Record', schema=tuple((k,inputs[v]) for k,v in mapping.items()))
        if impl=='column_view': aliases={'rows':list(inputs)}
        obligations.append({'code':'RECORD_CAPABILITY_LEASES','path':path,'copy_semantics':'values_and_handle_wrappers'})
    else:
        if set(inputs) != {'rows'}: fail('PORT_MISMATCH',path+'/inputs')
        source, schema = _view(inputs['rows'],params.get('source_view','rows'),path+'/inputs/rows')
        selected = _fields(params.get('columns',[]), schema, path+'/params/columns', allow_empty=True)
        expressions = params.get('expressions',{})
        if type(expressions) is not dict: fail('PARAMETER_TYPE',path+'/params/expressions')
        for name, ast in expressions.items():
            if not IDENT.fullmatch(name) or name in selected: fail('PARAMETER_RANGE',path+'/params/expressions')
            typ, guards = analyze_predicate(ast,schema,path+'/params/expressions/'+name,require_bool=False)
            if typ.kind=='List':
                if not 0<=typ.metadata.get('max_length',4097)<=4096:fail('PARAMETER_RANGE',path)
                if typ.item.kind in {'Empty','Null'}:fail('TYPE_MISMATCH',path)
            selected[name]=typ
            obligations.extend(guards)
        if not selected: fail('PARAMETER_REQUIRED',path+'/params/columns')
        if representation == 'same':
            if params.get('source_view','rows')!='rows': fail('TYPE_MISMATCH',path)
            typ=with_rows(source,selected)
        elif representation in {'table','record'}:
            typ=Type('Table' if representation=='table' else 'Record',tuple(selected.items()),
                     domain=source.domain,revision=source.revision,metadata=dict(source.metadata))
            if representation=='record': obligations.append({'code':'CARDINALITY_EXACTLY_ONE','path':path})
        else:
            if len(selected)!=1: fail('PARAMETER_RANGE',path+'/params/columns')
            name,item=next(iter(selected.items()))
            mappings=[m for m in _id_mappings(source) if m['field']==name]
            kind,domain,revision='Set',source.domain,source.revision
            if source.kind in {'NodeSet','Graph','GraphView'} and name in {'id','node_id'}:kind='NodeSet'
            elif name in source.metadata.get('node_id_mappings',{}):
                identity=source.metadata['node_id_mappings'][name];kind,domain,revision='NodeSet',identity['domain'],identity['revision']
            elif source.kind in {'IDSet','RankedIDSet'}:kind='IDSet'
            elif mappings:kind,domain,revision='IDSet',mappings[0]['domain'],mappings[0]['revision']
            typ=Type(kind,item=item,domain=domain,revision=revision)
        if typ.kind in {'Table','Record','Stream'}:
            typ=_mapped(typ,[m for m in _id_mappings(source) if m['field'] in selected])
        if impl=='column_view':aliases={'rows':['rows']}
    if set(node['outputs'])!={'rows'}: fail('PORT_MISMATCH',path+'/outputs')
    check_declared(typ,node['outputs']['rows'],path+'/outputs/rows')
    return {'outputs':{'rows':typ},'alias_inputs':aliases,'runtime_obligations':obligations,'dispatch_id':'project:'+impl}


def validate_operator(node, inputs, *, task, stage, path):
    op, p = node['operator'], node['params']
    if op.startswith('graph_'):
        result=legacy(node,{k:unwrap_ref(t) for k,t in inputs.items()},task=task,stage=stage,path=path)
        if op=='graph_shortest_path':
            graph=unwrap_ref(inputs['graph']);edge_id=dict(graph.schema).get('edge_id')
            if edge_id is not None:result['outputs']['paths']=replace(result['outputs']['paths'],metadata={**graph.metadata,'edge_id_type':edge_id})
        return result
    if op=='project' and set(p)-{'columns'}:
        return _project(node,inputs,path)
    extra={'top_k':{'partition_by'},'text_retrieve':{'offset'},'semantic_extract':{'question'}}.get(op,set())
    if not (set(p)&extra):
        return legacy(node,inputs,task=task,stage=stage,path=path)
    adapted=deepcopy(node)
    for name in extra: adapted['params'].pop(name,None)
    result=legacy(adapted,inputs,task=task,stage=stage,path=path)
    if op=='top_k':
        _fields(p['partition_by'],row_schema(inputs['rows'],path),path+'/params/partition_by',allow_empty=True)
        result['runtime_obligations'].append({'code':'EXACT_PARTITION_TOP_K','path':path})
    elif op=='text_retrieve': _integer(p['offset'],path+'/params/offset')
    else:_string(p['question'],path+'/params/question')
    return result
