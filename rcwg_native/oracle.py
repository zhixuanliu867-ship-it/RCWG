"""Small synthetic oracle. No imports from native code or reference comparators."""
from functools import total_ordering
from .evidence import canonical,sha

@total_ordering
class Descending:
    def __init__(self,value):self.value=value
    def __eq__(self,other):return self.value==other.value
    def __lt__(self,other):return other.value<self.value

def naive_top(rows,*,eligible,k,keys,fields):
    """Repeated minimum (quadratic on purpose) using tuple keys, not a comparator."""
    remaining=[]
    for ordinal,row in enumerate(rows):
        if not eligible(row):continue
        key=[]
        for spec in keys:
            v=row[spec['field']];null_first=spec.get('nulls')=='first'
            key.append((0 if null_first else 1,None) if v is None else (1 if null_first else 0,v if spec['direction']=='asc' else Descending(v)))
        remaining.append((tuple(key)+(ordinal,),row))
    answer=[]
    for _ in range(min(k,len(remaining))):
        winner=min(range(len(remaining)),key=lambda i:remaining[i][0]);_,row=remaining.pop(winner)
        answer.append({field:row[field] for field in fields})
    return answer

def compare(actual,expected):
    actual_raw,expected_raw=canonical(actual),canonical(expected)
    return {'status':'PASS' if actual_raw==expected_raw else 'FAIL','reason':'INDEPENDENT_TYPED_ROWS',
            'expected_sha256':sha(expected_raw),'actual_sha256':sha(actual_raw),'formal_ready':False}
