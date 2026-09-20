"""Independent fixture oracle; deliberately imports no execution kernel helpers.

Only the declared F1 eligibility / score-desc / id-asc recipe is implemented.
Other tasks require an independently reviewed verifier; they do not get PASS.
This module never repairs the submitted workflow or returns feedback to a model.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
from rcwg_spec.common import canonical, digest
from .files import open_regular
from .errors import ExecFault

RECIPE='F1_ELIGIBLE_SCORE_DESC_ID_ASC_V1'
def verify_f1(*,task,recipe,data_path:Path,artifact_path:Path,artifact_meta:dict,max_rows=100000):
    out={'status':'UNKNOWN','verifier_revision':RECIPE,'reason':None}
    contract=task.get('output_contract',{})
    required={'revision','source_id','source_sha256','task_input_hash','k','fields'}
    if type(recipe) is not dict or set(recipe)!=required or recipe.get('revision')!=RECIPE:
        return {**out,'reason':'VERIFIER_RECIPE_UNSUPPORTED'}
    if (recipe['task_input_hash']!=digest(task) or type(recipe['k']) is not int or recipe['k']<0
        or recipe['fields']!=['id','score'] or contract.get('fields')!=['id','score']
        or contract.get('type')!='ordered_records' or contract.get('mode')!='exact'
        or contract.get('k')!=recipe['k'] or contract.get('tie_breaker')!='id'):
        return {**out,'reason':'VERIFIER_CONTRACT_MISMATCH'}
    sources=[s for s in task['datasets'] if s['id']==recipe['source_id']]
    if len(sources)!=1 or sources[0].get('data_sha256')!=recipe['source_sha256']:
        return {**out,'reason':'VERIFIER_SOURCE_MISMATCH'}
    try:
        # Parse independently of the worker. Trusted dev fixtures are bounded.
        with os.fdopen(open_regular(data_path),'rb') as stream:
            if os.fstat(stream.fileno()).st_size>128*1024*1024:
                return {**out,'reason':'VERIFIER_BYTE_CAP'}
            raw=stream.read()
        if hashlib.sha256(raw).hexdigest()!=recipe['source_sha256']:
            return {**out,'reason':'VERIFIER_DATA_CHANGED'}
        data=[]
        for line in raw.splitlines():
            row=json.loads(line)
            if (type(row) is not dict or set(row)!= {'id','score','eligible'}
                or type(row['id']) is not int or not -(2**63)<=row['id']<2**63
                or type(row['score']) is not float or not math.isfinite(row['score'])
                or type(row['eligible']) is not bool):
                return {**out,'reason':'VERIFIER_INPUT_INVALID'}
            data.append(row)
            if len(data)>max_rows:return {**out,'reason':'VERIFIER_REFERENCE_CAP'}
        eligible=[r for r in data if r['eligible'] is True]
        chosen=sorted(eligible,key=lambda r:(-r['score'],r['id']))[:recipe['k']]
        expected=[{'id':r['id'],'score':r['score']} for r in chosen]
        with os.fdopen(open_regular(artifact_path),'rb') as stream:actual_raw=stream.read()
        if (type(artifact_meta.get('serialized_bytes')) is not int or type(artifact_meta.get('rows')) is not int
            or hashlib.sha256(actual_raw).hexdigest()!=artifact_meta.get('content_sha256')
            or len(actual_raw)!=artifact_meta.get('serialized_bytes')):
            return {**out,'reason':'ARTIFACT_HASH_MISMATCH'}
        actual=json.loads(actual_raw)
        # Canonical bytes distinguish Bool/Int and Float/Int, unlike loose ==.
        if canonical(actual)!=actual_raw:return {**out,'reason':'ARTIFACT_NOT_CANONICAL'}
        if type(actual) is not list or artifact_meta.get('rows')!=len(actual):
            return {**out,'reason':'ARTIFACT_METADATA_MISMATCH'}
        ok=canonical(expected)==actual_raw
        return {**out,'status':'PASS' if ok else 'FAIL',
                'reason':'EXACT_ORDERED_RESULT' if ok else 'OUTPUT_CONTRACT_VIOLATION',
                'expected_result_sha256':digest(expected),'actual_result_sha256':hashlib.sha256(actual_raw).hexdigest(),
                'eligible_rows':len(eligible),'expected_rows':len(expected),'actual_rows':len(actual),
                'recipe_sha256':digest(recipe),'formal_ready':False}
    except (ExecFault,OSError,ValueError,TypeError,KeyError,OverflowError,UnicodeError,RecursionError):
        return {**out,'reason':'VERIFIER_ERROR'}
