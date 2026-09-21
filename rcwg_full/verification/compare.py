"""Type-aware independent output comparisons and graph path validation."""
from collections import Counter
import math
from rcwg_full.evidence import canonical


def equivalent(actual,expected,*,abs_tol=1e-8,rel_tol=1e-6):
    if type(actual) is not type(expected):return False
    if type(expected) is float:return math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected)<=abs_tol+rel_tol*abs(expected)
    if type(expected) is dict:return actual.keys()==expected.keys() and all(equivalent(actual[k],v,abs_tol=abs_tol,rel_tol=rel_tol) for k,v in expected.items())
    if type(expected) is list:return len(actual)==len(expected) and all(equivalent(a,b,abs_tol=abs_tol,rel_tol=rel_tol) for a,b in zip(actual,expected))
    return actual==expected


def bag_equal(actual,expected,**tolerance):
    if type(actual) is not list or len(actual)!=len(expected):return False
    def floating(x):
        return type(x) is float or (type(x) is dict and any(floating(v) for v in x.values())) or (type(x) is list and any(floating(v) for v in x))
    if not any(floating(x) for x in expected):return Counter(canonical(x) for x in actual)==Counter(canonical(x) for x in expected)
    # With tolerances an exact-first greedy match is unsound. Find a full matching.
    remaining=actual;wanted=expected
    edges=[[j for j,y in enumerate(wanted) if equivalent(x,y,**tolerance)] for x in remaining]
    assigned={}
    def match(i,seen):
        for j in edges[i]:
            if j in seen:continue
            seen.add(j)
            if j not in assigned or match(assigned[j],seen):assigned[j]=i;return True
        return False
    return all(match(i,set()) for i in range(len(remaining)))


def set_equal(actual,expected):
    if type(actual) is not list:return False
    observed=[canonical(x) for x in actual];wanted={canonical(x) for x in expected}
    return len(observed)==len(set(observed)) and set(observed)==wanted


def shortest_distances(graph,seeds,weight_field=None,direction='out'):
    """Bellman-Ford oracle; independent edge scanning, no runtime heap/adjacency."""
    nodes={canonical(n['node_id']) for n in graph['nodes']};distance={n:math.inf for n in nodes}
    for seed in seeds:distance[canonical(seed)]=0
    arcs=[]
    for edge in graph['edges']:
        a,b=canonical(edge['src']),canonical(edge['dst']);w=1 if weight_field is None else edge[weight_field]
        if direction!='in' or not graph['directed']:arcs.append((a,b,w))
        if direction!='out' or not graph['directed']:arcs.append((b,a,w))
    for _ in range(max(0,len(nodes)-1)):
        changed=False
        for a,b,w in arcs:
            if distance[a]+w<distance[b]:distance[b]=distance[a]+w;changed=True
        if not changed:break
    return distance


def check_paths(actual,graph,seeds,targets,*,weight_field=None,direction='out',abs_tol=1e-8,rel_tol=1e-6):
    if type(actual) is not list:return False,'PATH_FORMAT'
    try:
        if Counter(canonical(x['target']) for x in actual)!=Counter(canonical(t) for t in targets):return False,'TARGET_COVERAGE'
        distances=shortest_distances(graph,seeds,weight_field,direction);edges={canonical(e['edge_id']):e for e in graph['edges']};seed_keys={canonical(s) for s in seeds}
        for result in actual:
            target=result['target'];distance=distances[canonical(target)];reachable=math.isfinite(distance)
            if type(result['reachable']) is not bool or result['reachable']!=reachable:return False,'REACHABILITY'
            if not reachable:
                if result['distance'] is not None or result['nodes'] or result['edges']:return False,'UNREACHABLE_REPRESENTATION'
                continue
            nodes=result['nodes'];ids=result['edges']
            if not nodes or len(nodes)!=len(ids)+1 or canonical(nodes[0]) not in seed_keys or canonical(nodes[-1])!=canonical(target):return False,'PATH_ENDPOINTS'
            if len({canonical(n) for n in nodes})!=len(nodes):return False,'PATH_CYCLE'
            measured=0.0
            for a,b,ident in zip(nodes,nodes[1:],ids):
                edge=edges[canonical(ident)];direct=(canonical(a),canonical(b));normal=(canonical(edge['src']),canonical(edge['dst']))
                allowed={normal} if direction=='out' else {normal[::-1]} if direction=='in' else {normal,normal[::-1]}
                if not graph['directed']:allowed|={normal,normal[::-1]}
                if direct not in allowed:return False,'EDGE_DIRECTION'
                measured+=1 if weight_field is None else edge[weight_field]
            if type(result['distance']) not in {int,float} or not math.isfinite(result['distance']):return False,'DISTANCE_TYPE'
            close=lambda a,b:abs(a-b)<=abs_tol+rel_tol*abs(b)
            if not close(measured,result['distance']) or not close(result['distance'],distance):return False,'DISTANCE_NOT_OPTIMAL'
        return True,None
    except (KeyError,TypeError,ValueError,OverflowError):return False,'PATH_FORMAT_OR_ID'


def check_output(actual,expected,contract):
    kind=contract['comparison'];tolerance={k:contract[k] for k in ['abs_tol','rel_tol'] if k in contract}
    try:
        if kind=='set':passed=set_equal(actual,expected)
        elif kind=='bag':passed=bag_equal(actual,expected,**tolerance)
        elif kind in {'ordered','record','scalar'}:passed=equivalent(actual,expected,**tolerance)
        elif kind=='graph':passed=actual.get('revision')==expected.get('revision') and actual.get('domain')==expected.get('domain') and equivalent(actual.get('directed'),expected.get('directed')) and bag_equal(actual['nodes'],expected['nodes'],**tolerance) and bag_equal(actual['edges'],expected['edges'],**tolerance)
        elif kind in {'paths','enriched_paths','graph_record','query_edges'}:
            from .graph_oracle import check_graph_output
            passed=check_graph_output(actual,expected,kind)
        else:return {'status':'UNKNOWN','reason':'VERIFIER_CONTRACT_UNSUPPORTED'}
    except RecursionError:return {'status':'UNKNOWN','reason':'VERIFIER_MATCHING_CAPACITY'}
    except (ValueError,TypeError,KeyError):passed=False
    return {'status':'PASS' if passed else 'FAIL','reason':None if passed else 'OUTPUT_MISMATCH'}
