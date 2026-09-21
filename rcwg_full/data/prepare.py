"""Prepare actual local files and bind their bytes to public source identities."""
from copy import deepcopy
from pathlib import Path
import json
from rcwg_full.evidence import exclusive_directory,write,sha,digest,canonical
from rcwg_spec.public_task import validate_public_task
from rcwg_full.runtime.values import arrow_schema


def prepare(task,values,directory,*,profile='engineering_tiny_v1',layout='contiguous',provenance=None):
    import pyarrow as pa
    out=exclusive_directory(directory);task=deepcopy(task);manifest={'revision':'full001-data-manifest-1','profile':profile,'sources':[],'formal_frozen':False}
    if profile not in {'engineering_tiny_v1','formal_candidate_v1'}:raise ValueError('DATA_PROFILE')
    for index,public in enumerate(task['datasets']):
        source_id=public['id'];value=values[source_id];public.setdefault('revision','engineering-v1');public.setdefault('schema_source','full001-defined-schema-v1')
        public.setdefault('kind','table');files=[]
        if isinstance(value,(pa.Table,pa.RecordBatch)):
            table=pa.Table.from_batches([value]) if isinstance(value,pa.RecordBatch) else value
            pieces=[table] if layout=='contiguous' else [table.slice(i,7) for i in range(0,table.num_rows,7)] or [table]
            for part,chunk in enumerate(pieces):
                name='source-%d-part-%04d.arrow'%(index,part);sink=pa.BufferOutputStream()
                with pa.ipc.new_file(sink,chunk.schema) as writer:writer.write_table(chunk,max_chunksize=1024)
                raw=sink.getvalue().to_pybytes();write(out/name,raw);files.append({'path':name,'sha256':sha(raw),'bytes':len(raw)})
            logical_hash=digest(table.to_pylist());logical_rows=table.num_rows;format='arrow_ipc'
        else:
            name='source-%d.json'%index;raw=canonical(value)+b'\n';write(out/name,raw);files=[{'path':name,'sha256':sha(raw),'bytes':len(raw)}]
            logical_hash=digest(value);logical_rows=len(value) if isinstance(value,list) else None;format='json'
        content=digest([{k:f[k] for k in ['sha256','bytes']} for f in files]);public['data_sha256']=content
        entry={'source_id':source_id,'kind':public['kind'],'domain':public.get('domain'),'revision':public['revision'],'content_sha256':content,
            'logical_content_sha256':logical_hash,'format':format,'logical_rows':logical_rows,'physical_files':files,'indexes':[],
            'source':provenance or {'kind':'generated_engineering_fixture'},'license':{'status':'GENERATED_RECIPE_ONLY_NO_UPSTREAM_TEXT'},'provenance':{'profile':profile,'layout':layout}}
        for j,declared in enumerate(public.get('indexes',[])):
            if declared['kind'] not in {'range','sorted'}:continue
            field=declared['fields'][0];rows=value.to_pylist();pairs=sorted((r[field],i) for i,r in enumerate(rows) if r[field] is not None)
            payload={'revision':'full001-sorted-index-1','source_content_sha256':content,'field':field,'values':[v for v,i in pairs],'ordinals':[i for v,i in pairs],'null_ordinals':[i for i,r in enumerate(rows) if r[field] is None]}
            name='source-%d-index-%d.json'%(index,j);h=write(out/name,payload)
            entry['indexes'].append({'id':declared['id'],'kind':declared['kind'],'path':name,'sha256':h,'build_sha256':sha(Path(__file__).read_bytes())})
        manifest['sources'].append(entry)
    checked=validate_public_task(task);schemas={s['id']:s['schema_hash'] for s in checked['source_manifest']}
    for entry in manifest['sources']:entry['schema_hash']=schemas[entry['source_id']]
    write(out/'task_public.json',task);write(out/'data_manifest.json',manifest)
    return task,manifest,out/'data_manifest.json'
