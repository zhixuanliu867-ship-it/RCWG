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
        seen=set()
        for i,item in enumerate(value):
            ident=item
            if tag=='RankedIDSet' and isinstance(item,dict):
                if set(item)!={'document_id','score'} or type(item['score']) is not float or not math.isfinite(item['score']):raise ValueError('RANKED_ID_FORMAT')
                ident=item['document_id']
            validate(ident,typ['item'],store,path+'.'+str(i))
            if tag=='RankedIDSet':
                identity=(type(ident).__name__,ident)
                if identity in seen:raise ValueError('RANKED_ID_DUPLICATE')
                seen.add(identity)
    # Arrow schemas and specialized domain types are checked by their adapters.


def arrow_type(typ):
    import pyarrow as pa
    if isinstance(typ,str):
        from rcwg_full.compiler.typesystem import parse_type,type_json
        typ=type_json(parse_type(typ,'/runtime/arrow_type'))
    tag=typ['kind']
    if tag=='Nullable':return arrow_type(typ['item'])
    if tag=='List':return pa.list_(arrow_type(typ['item']))
    if tag=='Record':return pa.struct([pa.field(k,arrow_type(v),nullable=kind(v)=='Nullable') for k,v in typ['schema'].items()])
    return {'Int64':pa.int64(),'Float64':pa.float64(),'Bool':pa.bool_(),'Utf8':pa.string(),'Date':pa.date32(),'Timestamp':pa.timestamp('us',tz='UTC')}[tag]


def arrow_schema(typ):
    import pyarrow as pa
    if typ['kind'] in {'Stream','ArtifactRef','DatasetRef'}:typ=typ['item']
    return pa.schema([pa.field(k,arrow_type(v),nullable=kind(v)=='Nullable') for k,v in typ['schema'].items()])


def validate_arrow(value,typ):
    """Validate actual buffers, not a nullable flag or a manifest assertion."""
    import pyarrow as pa
    import pyarrow.compute as pc
    while typ['kind'] in {'Stream','ArtifactRef','DatasetRef'}:typ=typ['item']
    schema=typ['schema']
    if len(value.column_names)!=len(schema) or set(value.column_names)!=set(schema):raise ValueError('DATA_SCHEMA_FIELDS')
    def column(array,descriptor,path):
        if isinstance(descriptor,str):
            from rcwg_full.compiler.typesystem import parse_type,type_json
            descriptor=type_json(parse_type(descriptor,'/runtime/arrow_type'))
        tag=kind(descriptor)
        if not array.type.equals(arrow_type(descriptor)):raise ValueError('DATA_SCHEMA_TYPE:'+path)
        if tag=='Nullable':
            return column(pc.drop_null(array),descriptor['item'],path)
        if array.null_count:raise ValueError('DATA_NON_NULLABLE:'+path)
        if tag=='Float64' and len(array) and not pc.all(pc.is_finite(array)).as_py():raise ValueError('DATA_NONFINITE:'+path)
        if tag=='List':
            if len(array) and pc.max(pc.list_value_length(array)).as_py()>descriptor['max_length']:raise ValueError('LIST_LIMIT:'+path)
            column(pc.list_flatten(array),descriptor['item'],path+'[]')
        elif tag=='Record':
            for name,child in descriptor['schema'].items():column(pc.struct_field(array,name),child,path+'.'+name)
    for name,descriptor in schema.items():column(value.column(name),descriptor,name)
