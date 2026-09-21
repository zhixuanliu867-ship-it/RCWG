"""Runtime scalar, record and capability checks; never infer authorization."""
import math
from datetime import date,datetime
from rcwg_full.runtime.artifacts import Artifact


def kind(typ):return typ if isinstance(typ,str) else typ['kind']


def validate(value,typ,store,path='value'):
    tag=kind(typ)
    if isinstance(value,Artifact):
        store.check(value)
        if tag in {'ArtifactRef','DatasetRef'}:return
        value=store.load(value)
    if tag=='Nullable':
        if value is None:return
        return validate(value,typ['item'],store,path)
    valid={'Int64':type(value) is int and -(2**63)<=value<2**63,
           'Float64':type(value) is float and math.isfinite(value),
           'Bool':type(value) is bool,'Utf8':type(value) is str}
    if tag in valid:
        if not valid[tag]:raise ValueError('RUNTIME_TYPE:'+path)
        if tag=='Utf8':value.encode('utf-8',errors='strict')
    elif tag in {'Date','Timestamp'}:
        if type(value) is not str:raise ValueError('RUNTIME_TYPE:'+path)
        parsed=date.fromisoformat(value) if tag=='Date' else datetime.fromisoformat(value)
        if tag=='Timestamp' and parsed.tzinfo is None:raise ValueError('TIMESTAMP_TIMEZONE')
    elif tag=='Record':
        if type(value) is not dict or set(value)!=set(typ['schema']):raise ValueError('RECORD_FIELDS:'+path)
        for field,t in typ['schema'].items():validate(value[field],t,store,path+'.'+field)
    elif tag in {'List','Set','NodeSet','IDSet','RankedIDSet'}:
        if type(value) is not list:raise ValueError('COLLECTION_TYPE:'+path)
        if tag=='List' and len(value)>typ.get('max_length',4096):raise ValueError('LIST_LIMIT')
        for i,item in enumerate(value):validate(item,typ['item'],store,path+'.'+str(i))
    # Arrow schemas and specialized domain types are checked by their adapters.


def arrow_type(typ):
    import pyarrow as pa
    if isinstance(typ,str):typ={'kind':typ}
    tag=typ['kind']
    if tag=='Nullable':return arrow_type(typ['item'])
    if tag=='List':return pa.list_(arrow_type(typ['item']))
    if tag=='Record':return pa.struct([pa.field(k,arrow_type(v),nullable=kind(v)=='Nullable') for k,v in typ['schema'].items()])
    return {'Int64':pa.int64(),'Float64':pa.float64(),'Bool':pa.bool_(),'Utf8':pa.string(),'Date':pa.date32(),'Timestamp':pa.timestamp('us',tz='UTC')}[tag]


def arrow_schema(typ):
    import pyarrow as pa
    if typ['kind'] in {'Stream','ArtifactRef','DatasetRef'}:typ=typ['item']
    return pa.schema([pa.field(k,arrow_type(v),nullable=kind(v)=='Nullable') for k,v in typ['schema'].items()])
