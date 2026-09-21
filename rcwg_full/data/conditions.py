"""Reread sibling condition bytes; a builder's assertion is not an invariant proof."""
from copy import deepcopy
import json
from pathlib import Path
from rcwg_full.evidence import digest,read,sha,safe_path


def check_group(directories):
    if set(directories)!={'C0','C1','C2','C3'}:raise ValueError('FOUR_CONDITIONS_REQUIRED')
    cases={};errors=[]
    for condition,directory in directories.items():
        directory=safe_path(directory);task=json.loads(read(directory/'task_public.json'));manifest=json.loads(read(directory/'data_manifest.json'))
        from rcwg_full.runtime.catalog import DataCatalog
        try:logical=DataCatalog(directory/'data_manifest.json').bind(task).audit()
        except (ValueError,KeyError,TypeError) as exc:
            errors.append(condition+':SOURCE_VALIDATION:'+str(exc));logical={}
        rows={}
        for entry in manifest['sources']:
            physical=[]
            for record in entry['physical_files']+entry.get('indexes',[]):
                rel=Path(record['path'])
                if rel.is_absolute() or '..' in rel.parts:raise ValueError('SOURCE_PATH')
                actual=sha(read(directory/rel))
                if actual!=record['sha256']:errors.append(condition+':PHYSICAL_HASH:'+entry['source_id'])
                physical.append(actual)
            rows[entry['source_id']]={'logical':logical.get(entry['source_id']),'physical':physical,'schema':entry['schema_hash']}
        cases[condition]={'task':task,'sources':rows}
    a,b=deepcopy(cases['C0']['task']),deepcopy(cases['C2']['task'])
    for task in [a,b]:task.pop('task_id',None)
    if a['resources']['worker_memory_limit_bytes']==b['resources']['worker_memory_limit_bytes']:errors.append('C2_RAM_NOT_CHANGED')
    b['resources']['worker_memory_limit_bytes']=a['resources']['worker_memory_limit_bytes']
    if a!=b:errors.append('C2_CHANGED_NON_RAM_TASK_FIELDS')
    if cases['C0']['sources']!=cases['C2']['sources']:errors.append('C2_DATA_INDEX_OR_SCHEMA_CHANGED')
    a,b=cases['C0']['sources'],cases['C3']['sources']
    if a.keys()!=b.keys():errors.append('C3_SOURCE_SET_CHANGED')
    else:
        if any(a[k]['logical']!=b[k]['logical'] or a[k]['schema']!=b[k]['schema'] for k in a):errors.append('C3_LOGICAL_CONTENT_OR_SCHEMA_CHANGED')
        if all(a[k]['physical']==b[k]['physical'] for k in a):errors.append('C3_NO_PHYSICAL_LAYOUT_CHANGE')
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'condition_source_proofs':{k:v['sources'] for k,v in cases.items()},
            'tasks_hash':digest({k:v['task'] for k,v in cases.items()}),'scope':'C2_EXACT_PHYSICAL_IDENTITY_C3_LOGICAL_IDENTITY_AND_PHYSICAL_CHANGE',
            'C1':'SEPARATE_TEMPLATE_AXIS_TEST_REQUIRED','formal_data_frozen':False}
