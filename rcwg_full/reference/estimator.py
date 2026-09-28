"""Deterministic nonnegative additive development-only cost fitting."""
import math
from rcwg_full.evidence import digest

FEATURES=('scan_bytes','comparisons','hash_probes','edge_visits','materialized_bytes','semantic_requests','reference_tokens','constant')


def fit(records,*,tolerance=1e-10,max_iterations=20000):
    if not records:raise ValueError('DEVELOPMENT_MEASUREMENTS_REQUIRED')
    modes={r.get('mode') for r in records}
    if len(modes)!=1:raise ValueError('ESTIMATOR_MODE_MIX')
    dispatches={r.get('dispatch_id') for r in records}
    if len(dispatches)!=1 or None in dispatches:raise ValueError('FIT_ONE_OPERATOR_IMPLEMENTATION')
    for record in records:
        if record.get('split')!='development':raise ValueError('TEST_DATA_LEAKAGE')
        if record.get('measured') is not True:raise ValueError('MEASURED_COST_REQUIRED')
        if record.get('mode') not in {'ENGINEERING_GOLDEN','LIVE_DEVELOPMENT'}:raise ValueError('ESTIMATOR_MODE')
        if set(record['features'])!=set(FEATURES):raise ValueError('FEATURE_SCHEMA')
        if any(type(v) not in {int,float} or not math.isfinite(v) or v<0 for v in [*record['features'].values(),record['elapsed_ns']]):raise ValueError('FEATURE_RANGE')
        if record['features']['constant']!=1:raise ValueError('CONSTANT_FEATURE')
    scale=[max([r['features'][k] for r in records]+[1]) for k in FEATURES]
    x=[[r['features'][k]/s for k,s in zip(FEATURES,scale)] for r in records];y=[r['elapsed_ns'] for r in records]
    weights=[0.]*len(FEATURES);prediction=[0.]*len(records);converged=False
    for iteration in range(max_iterations):
        maxchange=0
        for j in range(len(weights)):
            denominator=sum(row[j]**2 for row in x)
            if denominator==0:continue
            old=weights[j];new=max(0,old+sum(row[j]*(target-p) for row,target,p in zip(x,y,prediction))/denominator)
            delta=new-old;weights[j]=new
            for i,row in enumerate(x):prediction[i]+=delta*row[j]
            maxchange=max(maxchange,abs(delta))
        if maxchange<=tolerance*max(1.,max(weights)):converged=True;break
    if not converged:raise ValueError('NNLS_DID_NOT_CONVERGE')
    return {'dispatch_id':next(iter(dispatches)),'feature_schema':list(FEATURES),'scales':scale,'scaled_coefficients':weights,'training_records_hash':digest(records),
        'solver':'deterministic cyclic exact-coordinate NNLS','tolerance':tolerance,'iterations':iteration+1,
        'training_mode':next(iter(modes)),'formal_coefficients_available':False,
        'sum_squared_error':sum((a-b)**2 for a,b in zip(prediction,y))}


def predict(model,features):
    if list(model['feature_schema'])!=list(FEATURES) or set(features)!=set(FEATURES):raise ValueError('FEATURE_SCHEMA')
    if any(type(v) not in {int,float} or not math.isfinite(v) or v<0 for v in features.values()):raise ValueError('FEATURE_RANGE')
    return sum(features[k]/s*w for k,s,w in zip(FEATURES,model['scales'],model['scaled_coefficients']))


def untrained():return {'status':'UNTRAINED_NO_DEVELOPMENT_MEASUREMENTS','formal_coefficients_available':False,'coefficients':None,'feature_schema':list(FEATURES)}
