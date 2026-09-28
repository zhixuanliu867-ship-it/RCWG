"""Edge-scan reachability and independent path-evidence checks for controlled tasks."""
from copy import deepcopy


def reach(graph,seeds,hops,edges=None):
    reached=set(seeds);front=set(seeds)
    for _ in range(hops):
        upcoming={e['dst'] for e in (graph['edges'] if edges is None else edges) if e['src'] in front}
        front=upcoming-reached;reached|=upcoming
    return sorted(reached)


def f3_expected(args):
    number=args['number'];graph=args['graph'];edges=graph['edges']
    if number in {1,6}:return reach(graph,args['seeds'],3)
    if number in {4,7,9}:
        edges=[e for e in edges if e['type']=='allowed' and (number!=4 or 10<=e['time']<70)]
        nodes=reach(graph,args['seeds'],4,edges)
        if number==9:return sorted({r['document_id'] for r in args['node_doc'] if r['node_id'] in nodes})
        return nodes
    if number in {2,3,5,12}:
        return {'graph':graph,'seeds':args['seeds'],'targets':args['targets'],'weight_field':'weight',
                'attributes':args.get('attributes',[])}
    if number in {8,11}:
        if number==11:
            nodes={r['node_id'] for r in graph['nodes'] if r['eligible'] is True}
            edges=[e for e in edges if e['src'] in nodes and e['dst'] in nodes and e['weight']<=3]
        elif args['mode']=='induced':
            nodes=set(args['selection']);edges=[e for e in edges if e['src'] in nodes and e['dst'] in nodes]
        else:
            selected={r['edge_id'] for r in args['selection']};edges=[e for e in edges if e['edge_id'] in selected]
            nodes={v for e in edges for v in [e['src'],e['dst']]}
        result=deepcopy(graph);result.pop('edge_index',None);result['nodes']=[r for r in graph['nodes'] if r['node_id'] in nodes];result['edges']=edges
        return {'graph':result}
    if number==10:return {label:[e for e in edges if e['src'] in seeds] for label,seeds in args['queries'].items()}
    raise ValueError('GRAPH_ORACLE_TEMPLATE')


def check_graph_output(actual,expected,kind):
    from .compare import check_paths,bag_equal,check_output
    if kind=='graph_record':
        return type(actual) is dict and set(actual)=={'graph'} and check_output(actual['graph'],expected['graph'],{'comparison':'graph'})['status']=='PASS'
    if kind=='query_edges':return type(actual) is dict and actual.keys()==expected.keys() and all(bag_equal(actual[k],v) for k,v in expected.items())
    paths=actual['paths'] if kind=='enriched_paths' else actual
    valid,_=check_paths(paths,expected['graph'],expected['seeds'],expected['targets'],weight_field=expected['weight_field'])
    if not valid:return False
    if kind=='paths':return True
    if set(actual)!={'paths','attributes','edges'}:return False
    attributes={r['attribute_node_id']:r for r in expected['attributes']};edges={e['edge_id']:e for e in expected['graph']['edges']}
    node_rows=[];edge_rows=[]
    for path in paths:
        for i,ident in enumerate(path['nodes']):
            source=attributes[ident]
            node_rows.append({'target':path['target'],'node_id':ident,'ordinal':i,'value':source['value'],'source_revision':source['source_revision']})
        for i,ident in enumerate(path['edges']):edge_rows.append({'target':path['target'],'edge_ref':ident,'edge_ordinal':i,**edges[ident]})
    return bag_equal(actual['attributes'],node_rows) and bag_equal(actual['edges'],edge_rows)
