#!/usr/bin/env python3
"""Expand the existing NATIVE001 resource-pair grid, without executing it.

Usage: python tools/expand_resource_slots.py --output <NEW_FILE.json>
This planning tool never runs a workload, writes cgroups or calls a service.
The proposal still requires concrete input/plan/binary bindings and owner approval.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random

BASE_COMMIT='456a30d0d242ec005bfb9e25fdc7a45c72aa9af8'
PAIR_GRID={
    'seeds':[17,29,101], 'rows':[1024,16384,65536], 'k':[8,128],
    'memory_bytes':[67108864,134217728],
    'implementation_pairs':[['full_sort','streaming_heap'],['scalar','vectorized'],['column_view','copy']],
    'run_order_seed':901,'repeats':3,
}

def expand() -> dict:
    rng=random.Random(PAIR_GRID['run_order_seed'])
    pairs=[]
    keys=('seeds','rows','k','memory_bytes','implementation_pairs')
    for seed,rows,k,memory,pair in itertools.product(*(PAIR_GRID[key] for key in keys)):
        for repeat in range(PAIR_GRID['repeats']):
            payload={'seed':seed,'rows':rows,'k':k,'memory_bytes':memory,'implementations':pair,'repeat':repeat}
            raw=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
            payload['pair_id']='n4p_'+hashlib.sha256(raw).hexdigest()[:20]
            pairs.append(payload)
    rng.shuffle(pairs)
    slots=[]
    for item in pairs:
        sides=list(item['implementations']);rng.shuffle(sides)
        for side,impl in enumerate(sides):
            slots.append({**item,'run_id':item['pair_id']+'_'+str(side),
                          'ordinal':len(slots),'implementation':impl,'side_order':side,
                          'execution_status':'NOT_RUN','artifact_binding':'REQUIRED_BEFORE_APPROVAL'})
    return {'schema':'RCWG_N4_RESOURCE_SLOT_PROPOSAL_V1','status':'DESIGN_EXPANSION_ONLY',
            'approved':False,'source_commit':BASE_COMMIT,'source_path':'specs/native001/test_manifest.json',
            'interpretation':'Full Cartesian expansion of the existing grid; freeze non-varied branches separately.',
            'grid':PAIR_GRID,'expected_pairs':len(pairs),'expected_workload_slots':len(slots),
            'includes_calibration_or_warmup':False,
            'requirements_before_execution':['concrete input and WorkIR hashes','fixed non-varied implementations',
                                             'source/compiler/binary/host binding','separate calibration and warmup denominator',
                                             'exact owner-approved finite execution plan'],
            'automatic_retries':0,'formal_ready':False,'slots':slots}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    output=a.output.absolute()
    if any(p.is_symlink() for p in (output,*output.parents)):
        raise SystemExit('SYMLINK_PATH_REJECTED')
    proposal=expand()
    if proposal['expected_pairs']!=324 or len(proposal['slots'])!=648:
        raise SystemExit('UNEXPECTED_GRID_SIZE')
    if len({s['run_id'] for s in proposal['slots']})!=648:
        raise SystemExit('DUPLICATE_RUN_ID')
    with output.open('x',encoding='utf-8') as stream:
        json.dump(proposal,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'output':str(output),'pairs':324,'workload_slots':648,'executed':0,'approved':False}))
    return 0

if __name__=='__main__':raise SystemExit(main())
