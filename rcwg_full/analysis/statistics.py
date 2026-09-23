"""Predeclared paired template-cluster bootstrap and sign randomization."""
from collections import defaultdict
import hashlib
import math
import random
from statistics import fmean
from rcwg_full.evidence import canonical,digest
from .metrics import FAMILIES,macro


def quantile(values, p):
    values=sorted(values)
    if not values or not 0<=p<=1:raise ValueError('QUANTILE_INPUT')
    pos=(len(values)-1)*p;lo=math.floor(pos);hi=math.ceil(pos)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)


def paired_inference(left,right,*,bootstrap_seed=170029,sign_seed=290017,draws=10000,families=FAMILIES):
    if left.keys()!=right.keys():raise ValueError('UNPAIRED_TEMPLATE_SET')
    if draws!=10000:raise ValueError('PREREGISTERED_10000_DRAWS_REQUIRED')
    if not all(type(v) in {int,float} and math.isfinite(v) for v in [*left.values(),*right.values()]):raise ValueError('NONFINITE_STATISTIC')
    grouped=defaultdict(list)
    for key in sorted(left):grouped[key[0]].append(key)
    if set(grouped)!=set(families) or any(not grouped[f] for f in families):raise ValueError('FAMILY_COVERAGE_MISMATCH')
    difference={key:left[key]-right[key] for key in left};observed=macro(difference,families=families)
    brng=random.Random(bootstrap_seed);srng=random.Random(sign_seed)
    bootstrap=[];extreme=0;indexhash=hashlib.sha256();signhash=hashlib.sha256()
    for _ in range(draws):
        sample={f:[brng.randrange(len(grouped[f])) for _ in grouped[f]] for f in families}
        indexhash.update(canonical(sample)+b'\n')
        bootstrap.append(fmean(fmean(difference[grouped[f][i]] for i in sample[f]) for f in families))
        signs={f:[1 if srng.getrandbits(1) else -1 for _ in grouped[f]] for f in families}
        signhash.update(canonical(signs)+b'\n')
        perm=fmean(fmean(difference[k]*sign for k,sign in zip(grouped[f],signs[f])) for f in families)
        if abs(perm)>=abs(observed)-1e-15:extreme+=1
    return {'effect':observed,'effect_percentage_points':100*observed,
            'confidence_interval_95':[quantile(bootstrap,.025),quantile(bootstrap,.975)],
            'p_two_sided':(1+extreme)/(draws+1),'extreme_count':extreme,'draws':draws,
            'bootstrap_seed':bootstrap_seed,'sign_seed':sign_seed,
            'bootstrap_indices_sha256':indexhash.hexdigest(),'signs_sha256':signhash.hexdigest(),
            'paired_keys_sha256':digest([list(k) for k in sorted(left)]),
            'cluster_counts':{f:len(grouped[f]) for f in families},
            'assumption':'Paired template differences are sign-exchangeable/symmetric under the null; no causal identification is implied.',
            'resampling':'templates within each family; paired methods share indices; all lower-level units travel with the template'}


def holm(pvalues):
    if not pvalues or any(type(p) not in {int,float} or not math.isfinite(p) or not 0<=p<=1 for p in pvalues.values()):raise ValueError('PVALUES')
    ordered=sorted(pvalues,key=lambda k:(pvalues[k],k));maximum=0;result={}
    for rank,key in enumerate(ordered):
        maximum=max(maximum,min(1,(len(ordered)-rank)*pvalues[key]));result[key]=maximum
    return result


def hypothesis_registry():
    return {'version':'FULL001_STATISTICS_COMPAT1','status':'CANDIDATE_NOT_FORMALLY_FROZEN','family_size':18,
            'correction':'Holm','draws':10000,'bootstrap_seed':170029,'sign_seed':290017,
            'tests':[{'id':f'G{g}.{metric}','generator':f'G{g}','contrast':contrast,
                      'metric':metric,'null':'template-family-macro paired difference = 0','alternative':'two-sided',
                      'p_method':'paired template sign randomization','ci_method':'paired within-family template cluster bootstrap'}
                     for g in range(6) for metric,contrast in [('SuccessBudget','P1-P0'),('EfficientSuccess020','P1-P0'),('AdaptiveFrozen','Adaptive-Frozen')]]}
