"""Validate actual JSON payloads against the bound public source descriptor."""
from rcwg_full.evidence import digest
from rcwg_full.runtime.values import validate,native_temporal


def unique(values,code):
    seen=set()
    for value in values:
        key=digest(value)
        if key in seen:raise ValueError(code)
        seen.add(key)
    return seen


def validate_source(value,public,typ):
    kind=public['kind'];stats=public.get('stats',{})
    def count(values,key):
        if type(values) is not list or len(values)!=stats[key]:raise ValueError('DATA_'+key.upper())
    def records(rows,schema):
        for row in rows:validate(row,{'kind':'Record','schema':schema},None,'source')
    if kind=='graph':
        if type(value) is not dict or not {'nodes','edges','directed'}<=value.keys():raise ValueError('GRAPH_PAYLOAD')
        for name in ['domain','revision']:
            if name in value and value[name]!=public[name]:raise ValueError('GRAPH_'+name.upper())
        if type(value['directed']) is not bool or value['directed']!=public['directed']:raise ValueError('GRAPH_DIRECTED')
        nodes,edges=value['nodes'],value['edges'];count(nodes,'node_count');count(edges,'edge_count')
        records(nodes,public['node_schema']);records(edges,public['edge_schema'])
        node_field=public.get('node_id_field','id');src=public.get('source_field','source');dst=public.get('target_field','target')
        ids=unique([row[node_field] for row in nodes],'GRAPH_DUPLICATE_NODE')
        for edge in edges:
            if digest(edge[src]) not in ids or digest(edge[dst]) not in ids:raise ValueError('GRAPH_UNKNOWN_ENDPOINT')
        if 'edge_id' in public['edge_schema']:unique([row['edge_id'] for row in edges],'GRAPH_DUPLICATE_EDGE')
        weight=public.get('weight_field')
        if weight:
            values=[e[weight] for e in edges]
            if public.get('weight_nonnegative') is True and any(w<0 for w in values):raise ValueError('GRAPH_WEIGHT_NONNEGATIVE')
            if public.get('weight_equal') is True and values and any(w!=values[0] for w in values):raise ValueError('GRAPH_WEIGHT_EQUAL')
        if public.get('indexes') and 'edge_index' not in value:raise ValueError('GRAPH_INDEX_MISSING')
        if 'edge_index' in value:
            index=value['edge_index']
            if type(index) is not list or any(type(i) is not int for i in index) or sorted(index)!=list(range(len(edges))):raise ValueError('GRAPH_INDEX_PERMUTATION')
            # A sorted declaration asserts actual field order, independently of its bytes hash.
            declared=public.get('indexes',[])
            if declared and declared[0]['kind']=='sorted':
                from rcwg_full.runtime.values import descriptor
                def key(i):
                    result=[]
                    for field in declared[0]['fields']:
                        v=edges[i][field];t=descriptor(public['edge_schema'][field])
                        if t['kind']=='Nullable':t=t['item']
                        if v is not None and t['kind'] in {'Date','Timestamp'}:v=next(iter(native_temporal(v,t).values()))
                        result.append((v is None,v))
                    return result
                keys=[key(i) for i in index]
                if keys!=sorted(keys):raise ValueError('GRAPH_INDEX_ORDER')
    elif kind in {'node_set','id_selection','set'}:
        count(value,'item_count');validate(value,typ,None)
        if kind=='id_selection' and public['ranked']:unique([v['document_id'] for v in value],'DATA_DUPLICATE_ID')
        else:
            item=typ['item'];unique([native_temporal(v,item) for v in value],'DATA_DUPLICATE_ITEM')
    elif kind=='edge_stream':
        count(value,'edge_count');records(value,public['schema'])
    elif kind in {'record','scalar'}:
        validate(value,typ,None)
        if 'value' in public and native_temporal(value,typ)!=native_temporal(public['value'],typ):raise ValueError('DATA_PUBLIC_SCALAR_VALUE')
    elif kind=='document_index':
        from rcwg_full.runtime.documents import validate_document
        count(value,'document_count');ids=[]
        for doc in value:
            validate_document(doc)
            if doc['revision']!=public['revision']:raise ValueError('DOCUMENT_REVISION_MISMATCH')
            schema=public['schema']
            if set(schema)-set(doc):raise ValueError('DOCUMENT_SCHEMA_FIELDS')
            records([{k:doc[k] for k in schema}],schema)
            ident=doc[public.get('id_field','id')]
            if type(ident)!=type(doc['document_id']) or ident!=doc['document_id']:raise ValueError('DOCUMENT_ID_MAPPING')
            ids.append(ident)
        unique(ids,'DOCUMENT_ID_DUPLICATE')
    else:raise ValueError('SOURCE_FORMAT_TYPE_MISMATCH')
