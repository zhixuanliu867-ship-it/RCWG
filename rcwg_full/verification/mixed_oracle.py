"""Independent F6 relation closure and source-language evidence verification."""
from copy import deepcopy
from collections import defaultdict
import re
from rcwg_full.evidence import canonical
from .document_oracle import verify_document_result,_span
from .compare import check_paths


def f6_expected(args):
    number=args['template'];graph=args['graph'];docs=args['documents'];mapping=args['mapping']
    facts={};secondary={};roots={}
    for doc in docs:
        text=doc['canonical_text'];node,entity=re.search(r'Node (\d+) denotes ([^.]+)\.',text).groups()
        roots[int(node)]=doc
        a=re.search(r'Condition A for ([^ ]+) is (supported|refuted|unknown)\. Value (\d+) mg\.',text)
        b=re.search(r'Condition B for ([^ ]+) is (supported|refuted|unknown)\.',text)
        if entity!=a[1] or entity!=b[1]:raise ValueError('CONTROLLED_SOURCE_ENTITY')
        facts[doc['document_id']]={'query_id':'q-A','paper_id':doc['document_id'],'entity_id':entity,'status':a[2],
            'value':int(a[3]),'evidence':[_span(doc,a[0])]}
        secondary[doc['document_id']]={**deepcopy(facts[doc['document_id']]),'query_id':'q-B','status':b[2],
            'evidence':[_span(doc,b[0]),_span(doc,'Value '+a[3]+' mg.')]}
    filtered={**graph,'edges':[e for e in graph['edges'] if e['type']=='allowed' and (number!=3 or 20<=e['time']<60)]}
    seeds=[0];stages={};hops=3
    if number==6:
        doc=roots[0];match=re.search(r'The next entity node is (\d+)\.',doc['canonical_text']);seeds=[int(match[1])];hops=2
        stages['extract_seed']=[{'query_id':'q-next','paper_id':doc['document_id'],'entity_id':facts[doc['document_id']]['entity_id'],
            'target_node':seeds[0],'evidence':[_span(doc,match[0])]}]
    # Synchronous edge relaxation is independent of runtime BFS/DFS/CSR traversal.
    distances={s:0 for s in seeds}
    for step in range(hops):
        new=dict(distances)
        for edge in filtered['edges']:
            if edge['src'] in distances:new[edge['dst']]=min(new.get(edge['dst'],hops+1),distances[edge['src']]+1)
        distances=new
    selected=[r['document_id'] for r in mapping if r['node_key']>0 and distances.get(r['node_key'],hops+1)<=hops]
    rows=[deepcopy(facts[i]) for i in selected]
    stages['extract']=list(facts.values()) if number==2 else deepcopy(rows)
    result=[r for r in rows if r['status']=='supported']
    if number==8:result=rows
    if number in {7,10}:
        b_rows=[deepcopy(secondary[i]) for i in selected]
        if number==10:
            stages={'extract_a':stages.pop('extract'),'extract_b':b_rows}
            result={'dose_branch':result,'rate_branch':[r for r in b_rows if r['status']=='supported']}
        else:
            stages['extract_b']=b_rows;b_ids={r['paper_id'] for r in b_rows if r['status']=='supported'}
            result=[{'id':r['paper_id']} for r in result if r['paper_id'] not in b_ids]
    if number in {5,11}:
        score={r['document_id']:r['score'] for r in mapping}
        result=[{**r,'score':score[r['paper_id']]} for r in result]
        result=sorted(result,key=lambda r:(-r['score'],r['paper_id']))[:2]
    if number==9:
        groups=defaultdict(list);by_id={r['document_id']:r for r in mapping}
        for row in result:groups[by_id[row['paper_id']]['group_id']].append(row['value'])
        result=[{'group_id':g,'count_entities':len(values),'total_value':sum(values)} for g,values in sorted(groups.items()) if len(values)==2]
    return {'result':result,'stages':stages,'ordered':number in {5,11},
        'paths':{'graph':filtered,'seeds':[0],'targets':[n['node_id'] for n in graph['nodes'] if n['node_id']!=0]} if number==4 else None}


def verify_mixed_result(actual,expected,documents,*,events=None):
    paths=expected.get('paths')
    if paths:
        if type(actual) is not dict or set(actual)!={'paths','facts'}:return {'status':'FAIL','reason':'MIXED_PATH_FORMAT'}
        passed,reason=check_paths(actual['paths'],paths['graph'],paths['seeds'],paths['targets'],weight_field='weight')
        result=verify_document_result(actual['facts'],expected,documents,events=events)
        result['path_check']={'status':'PASS' if passed else 'FAIL','reason':reason}
        if not passed:result['status']='FAIL'
        return result
    result=verify_document_result(actual,expected,documents,events=events)
    if expected['ordered'] and result['status']=='PASS':
        if [r['paper_id'] for r in actual]!=[r['paper_id'] for r in expected['result']]:result.update(status='FAIL',reason='EXPLICIT_RANK_ORDER')
    return result
