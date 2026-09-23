"""Bounded Arrow file construction with the same logical digest as tiny data.

This internal writer performs real I/O. The caller is responsible for admitting
the requested workload; it does not grant host or formal-data authorization.
"""
from copy import deepcopy
import hashlib
import os
from rcwg_full.evidence import canonical,digest,exclusive_directory,write
from rcwg_full.compiler.public_task import validate_public_task
from rcwg_full.runtime.values import arrow_schema,validate_arrow


def prepare_streams(task,sources,directory,*,profile,provenance,batch_rows=1024,fragment_rows=None):
    import pyarrow as pa
    if profile not in {'formal_candidate_v1','formal_builder_fixture_v1'}:raise ValueError('STREAM_BUILD_PROFILE')
    if type(batch_rows) is not int or not 1<=batch_rows<=1024:raise ValueError('BUILD_BATCH_ROWS')
    if fragment_rows is not None and (type(fragment_rows) is not int or fragment_rows<1):raise ValueError('BUILD_FRAGMENT_ROWS')
    if set(sources)!={d['id'] for d in task['datasets']}:raise ValueError('BUILD_SOURCE_SET')
    if any(d.get('indexes') and d.get('kind','table')=='table' for d in task['datasets']):raise ValueError('STREAM_INDEX_BUILDER_REQUIRED')
    out=exclusive_directory(directory);task=deepcopy(task)
    manifest={'revision':'full001-data-manifest-1','profile':profile,'sources':[],'formal_frozen':False}
    for index,public in enumerate(task['datasets']):
        if public.get('kind','table')!='table':
            from .json_stream import JsonRows,write_json_stream
            value=sources[public['id']];name=f'source-{index}.json'
            logical,physical,size,observed=write_json_stream(out/name,value,fragmented=fragment_rows is not None)
            files=[{'path':name,'sha256':physical,'bytes':size}];content=digest([{k:f[k] for k in ['sha256','bytes']} for f in files])
            public['data_sha256']=content
            manifest['sources'].append({'source_id':public['id'],'kind':public['kind'],'domain':public.get('domain'),
                'revision':public['revision'],'content_sha256':content,'logical_content_sha256':logical,
                'format':'json','logical_rows':value.count if isinstance(value,JsonRows) else len(value) if isinstance(value,list) else None,
                'physical_files':files,'indexes':[],'source':provenance,
                'license':{'status':'GENERATED_RECIPE_ONLY_NO_UPSTREAM_TEXT'},
                'provenance':{'profile':profile,'layout':'fragmented' if fragment_rows else 'contiguous'},'builder_observations':observed})
            continue
        schema=arrow_schema({'kind':'Table','schema':public['schema']})
        logical=hashlib.sha256(b'[');count=0;files=[];peak_rows=0;peak_arrow_bytes=0
        handle=writer=name=None;part_count=0;part=0
        def open_part():
            nonlocal handle,writer,name,part_count
            name=f'source-{index}-part-{part:04d}.arrow';handle=(out/name).open('xb')
            writer=pa.ipc.new_file(handle,schema);part_count=0
        def close_part():
            nonlocal handle,writer,part
            writer.close();handle.flush();os.fsync(handle.fileno());handle.close()
            with (out/name).open('rb') as f:checksum=hashlib.file_digest(f,'sha256').hexdigest()
            files.append({'path':name,'sha256':checksum,'bytes':(out/name).stat().st_size})
            handle=writer=None;part+=1
        iterator=iter(sources[public['id']]);exhausted=False
        try:
            open_part()
            while not exhausted:
                limit=min(batch_rows,fragment_rows-part_count) if fragment_rows else batch_rows
                rows=[]
                for _ in range(limit):
                    try:row=next(iterator)
                    except StopIteration:exhausted=True;break
                    if type(row) is not dict or set(row)!=set(public['schema']):raise ValueError('BUILD_ROW_FIELDS')
                    if count:logical.update(b',')
                    logical.update(canonical(row));count+=1;rows.append(row)
                if rows:
                    batch=pa.RecordBatch.from_pylist(rows,schema=schema)
                    validate_arrow(batch,{'kind':'Table','schema':public['schema']})
                    writer.write_batch(batch);part_count+=len(rows)
                    peak_rows=max(peak_rows,len(rows));peak_arrow_bytes=max(peak_arrow_bytes,batch.nbytes)
                    # The next batch is built only after these payloads are freed.
                    del batch,rows
                if fragment_rows and part_count==fragment_rows and not exhausted:
                    close_part();open_part()
            close_part()
        finally:
            if writer is not None:writer.close()
            if handle is not None:handle.close()
            if hasattr(iterator,'close'):iterator.close()
        if count!=public['stats']['row_count']:raise ValueError('BUILD_ROW_COUNT')
        logical.update(b']');content=digest([{k:f[k] for k in ['sha256','bytes']} for f in files]);public['data_sha256']=content
        manifest['sources'].append({'source_id':public['id'],'kind':'table','domain':public.get('domain'),
            'revision':public['revision'],'content_sha256':content,'logical_content_sha256':logical.hexdigest(),
            'format':'arrow_ipc','logical_rows':count,'physical_files':files,'indexes':[],
            'source':provenance,'license':{'status':'GENERATED_RECIPE_ONLY_NO_UPSTREAM_TEXT'},
            'provenance':{'profile':profile,'layout':'fragmented' if fragment_rows else 'contiguous'},
            'builder_observations':{'peak_batch_rows':peak_rows,'peak_batch_arrow_bytes':peak_arrow_bytes,
                'physical_bytes':sum(f['bytes'] for f in files),'process_peak_ram_bytes':None}})
    checked=validate_public_task(task);schemas={s['id']:s['schema_hash'] for s in checked['source_manifest']}
    for entry in manifest['sources']:entry['schema_hash']=schemas[entry['source_id']]
    write(out/'task_public.json',task);write(out/'data_manifest.json',manifest)
    return task,manifest,out/'data_manifest.json'
