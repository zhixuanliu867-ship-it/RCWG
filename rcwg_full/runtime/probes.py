"""Frozen, bounded generation probes. Metadata never scans private source rows."""
import random
from rcwg_full.evidence import digest

SAMPLE_PROFILE={'revision':'full001-reservoir-sample-1','algorithm':'Algorithm R',
                'seed':714091,'order':'source ordinal','fields':'requested columns only'}


def probe(source,impl,params,event):
    if not hasattr(source,'public'):raise ValueError('PROBE_PUBLIC_BINDING_REQUIRED')
    result={'kind':impl,'fields':params['fields'],'public_stats':dict(source.public['stats'])}
    if impl=='metadata':
        event('generation_probe',{'implementation':impl,'source_id':source.entry['source_id'],
            'source_rows_read':0,'sample_rows':0,'logical_read_bytes':0,'physical_integrity_read_bytes':0})
        return result
    if impl!='sample' or source.entry['kind']!='table':raise ValueError('PROBE_SAMPLE_TABLE_REQUIRED')
    n=params['sample_size'];rng=random.Random(SAMPLE_PROFILE['seed']);sample=[];count=0;logical=0;physical=0
    def observed(kind,payload):
        nonlocal physical
        if kind=='source_integrity_read':physical+=payload['bytes']
        event(kind,payload)
    for batch in source.batches(columns=params['fields'],on_event=observed):
        logical+=batch.nbytes
        for row in batch.to_pylist():
            ordinal=count;count+=1
            if ordinal<n:sample.append((ordinal,row))
            else:
                slot=rng.randrange(count)
                if slot<n:sample[slot]=(ordinal,row)
    sample.sort(key=lambda pair:pair[0]);result.update(sample=[row for _,row in sample],
        source_ordinals=[i for i,_ in sample],sampling_profile=SAMPLE_PROFILE)
    event('generation_probe',{'implementation':impl,'source_id':source.entry['source_id'],
        'source_rows_read':count,'sample_rows':len(sample),'logical_read_bytes':logical,
        'physical_integrity_read_bytes':physical,'sampling_profile':SAMPLE_PROFILE,'result_sha256':digest(result)})
    return result
