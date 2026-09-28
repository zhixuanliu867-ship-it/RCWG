"""F4 value oracle uses definitions and Python loops, never runtime plans/kernels."""
def f4_expected(number,sources,base):
    rows=sources['records']
    if number in {6,9}:rows=[r for r in rows if r['eligible']]
    def total(data):return {'total':sum(r['amount'] for r in data)}
    def groups(data):
        result={}
        for row in data:result[row['group_id']]=result.get(row['group_id'],0)+row['amount']
        return [{'group_id':key,'total':result[key]} for key in sorted(result)]
    if number in {1,6,7}:return {'sum':total(rows),'count':{'count':len(rows)}}
    if number==2:return {'a':total(rows),'b':total(rows)}
    if number in {3,4,5}:return groups(rows)
    if number==8:return [{'id':r['id'],'value':r['amount']*2} for r in rows]
    if number==9:return {'original':groups(rows),'joined':groups([r for r in rows for w in sources['weights'] if r['group_id']==w['g']])}
    if number==10:return {branch:[{'id':r['id'],'value':r['amount']*2} for r in rows] for branch in ['fast','slow']}
    if number==11:return {'a':total(rows),'b':total(sources['other'])}
    if number==12:
        iterations=(len(rows)+15)//16 if base!=0 else 0
        return {'remaining':len(rows)-16*iterations,'iterations':iterations,'active':base!=0}
    raise ValueError('ORACLE_TEMPLATE')
