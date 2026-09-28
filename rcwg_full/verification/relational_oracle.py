"""Independent declarative relational expectations. Does not import runtime code."""
from collections import defaultdict


def f1_expected(number,sources):
    records=list(sources['records']);fields=['id','score']
    if number in {1,2,4,7,9,10,12}:records=[r for r in records if r['eligible'] is True]
    if number==2:records=[r for r in records if r['q'] is True]
    if number==4:records=[r for r in records if r['score'] is not None and r['score']>=0]
    if number==8:
        ids={r['id'] for alias in ['left_candidates','right_candidates'] for r in sources[alias]}
        records=[r for r in records if r['id'] in ids]
    if number in {6,8}:
        first={}
        for row in records:
            if row['entity_id'] not in first:first[row['entity_id']]=row
        records=list(first.values());fields+=['entity_id']
    if number==3:fields+=['priority']
    if number==5:
        grouped=defaultdict(list)
        for row in records:grouped[row['group_id']].append(row)
        return [{k:r[k] for k in ['id','score','group_id']} for g in sorted(grouped)
                for r in sorted(grouped[g],key=lambda r:(-r['score'],r['id']))[:3]]
    if number==9:
        groups=defaultdict(int)
        for row in records:groups[row['group_id']]+=row['amount']
        return [{'group_id':g,'total':total} for g,total in sorted(groups.items(),key=lambda x:(-x[1],x[0]))[:10]]
    if number==10:return {label:{'count':sum(r['score']>=threshold for r in records)} for label,threshold in [('low',5),('high',10)]}
    ranking=(lambda r:(-r['score'],r['priority'],r['id'])) if number==3 else (lambda r:(r['priority'],-r['score'],r['id'])) if number==11 else (lambda r:(-r['score'],r['id']))
    return [{k:r[k] for k in fields} for r in sorted(records,key=ranking)[:20]]


def f2_expected(number,sources):
    left=sources['left'];right=sources.get('right',[])
    if number==11:
        groups=defaultdict(int)
        for row in left:
            if 70<=row['timestamp']<230:groups[row['entity_id']]+=row['amount']
        return [{'entity_id':k,'total':v} for k,v in groups.items() if v>=30]
    joined=[]
    for a in left:
        if number==10 and a['eligible'] is not True:continue
        matches=[b for b in right if a['join_key'] is not None and b['join_key'] is not None and a['join_key']==b['join_key'] and (number!=6 or b['qualified'] is True)]
        if number==6:
            if matches:joined.append((a,None))
        elif number==5 and not matches:joined.append((a,None))
        else:joined.extend((a,b) for b in matches)
    if number in {1,3,5}:return [{'left_id':a['left_id'],'right_id':b['right_id'] if b else None} for a,b in joined]
    if number==6:return [{'left_id':a['left_id'],'group_id':a['group_id']} for a,b in joined]
    if number in {2,4}:
        counts=defaultdict(int)
        for a,b in joined:counts[a['join_key'] if number==2 else a['group_id']]+=1
        return [{('left.join_key' if number==2 else 'group_id'):k,'count':v} for k,v in counts.items()]
    if number==7:
        groups=defaultdict(set)
        for a,b in joined:
            ids=groups[a['group_id']]
            if b['right_entity_id'] is not None:ids.add(b['right_entity_id'])
        return [{'group_id':k,'count':len(v)} for k,v in groups.items()]
    if number in {8,9,10}:
        totals=defaultdict(int)
        for a,b in joined:
            matches=[None] if number==8 else [c for c in sources['third'] if b['right_entity_id'] is not None and b['right_entity_id']==c['entity_key']]
            for _ in matches:totals[a['group_id']]+=a['amount']
        return [{'group_id':k,'total':v} for k,v in totals.items()]
    if number==12:return {'sum':{'total':sum(a['amount'] for a,b in joined) if joined else None},'count':{'count':len(joined)}}
    raise ValueError('ORACLE_TEMPLATE')
