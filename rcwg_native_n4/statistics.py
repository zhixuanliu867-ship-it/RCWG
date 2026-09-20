"""Preregistered engineering paired overhead; independent of formal estimands."""
import math
import random
import statistics

def overhead(pairs,*,expected=20):
    # Fixed 10,000 paired percentile bootstrap, seed frozen before observation.
    if len(pairs)!=expected or any(set(p)!={'on_ns','off_ns'} or any(type(v) is not int or v<=0 for v in p.values()) for p in pairs):
        return {'status':'INCONCLUSIVE','reason':'INCOMPLETE_OR_INVALID_PAIRS','expected':expected,'observed':len(pairs)}
    ratios=[p['on_ns']/p['off_ns']-1 for p in pairs]
    rng=random.Random(4901);samples=sorted(statistics.mean(rng.choices(ratios,k=len(ratios))) for _ in range(10000))
    lo,hi=samples[249],samples[9749];mean=statistics.mean(ratios)
    status='PASS' if hi<=0.03 else ('FAIL' if lo>0.03 else 'INCONCLUSIVE')
    # Very short/noisy host measurements cannot acquire qualification by rounding.
    if min(p['off_ns'] for p in pairs)<100_000_000:status='INCONCLUSIVE'
    return {'status':status,'mean_fraction':mean,'median_fraction':statistics.median(ratios),'paired_fractions':ratios,
            'ci95':[lo,hi],'threshold':0.03,'bootstrap_seed':4901,'bootstrap_resamples':10000,
            'formula':'mean((T_on - T_off)/T_off)','scope':'ENGINEERING_BATCH','formal_ready':False}

def classify_oom(evidence):
    """Event coincidence alone is never a sufficient causal identification."""
    if evidence.get('manual_stop'):return 'CONTROLLED_STOP'
    if evidence.get('ancestor_oom_delta',0)>0:return 'FACILITY_OR_ANCESTOR_OOM'
    if evidence.get('global_oom_confirmed'):return 'GLOBAL_OOM'
    if (evidence.get('kernel_victim_group_matches') is True and evidence.get('local_oom_delta',0)>0
        and evidence.get('local_oom_kill_delta',0)>0 and evidence.get('ancestor_events_complete') is True
        and evidence.get('hard_limit_readback_matches') is True):return 'RUN_MEMORY_LIMIT'
    return 'UNKNOWN'

def sample_gaps(samples):
    ts=[s['monotonic_ns'] for s in samples]
    gaps=[b-a for a,b in zip(ts,ts[1:])]
    return {'nominal_interval_ns':100_000_000,'actual_gaps_ns':gaps,'max_gap_ns':max(gaps) if gaps else None,
            'missing_samples':sum(s.get('memory_current_bytes') is None for s in samples)}
