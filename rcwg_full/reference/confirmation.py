"""Independent screening and confirmation records; no timing is fabricated."""
from statistics import median
from rcwg_full.evidence import digest,write,exclusive_directory


def relative_mad(values):
    center=median(values)
    return median(abs(v-center) for v in values)/center if center>0 else float('inf')


def confirm(definitions,context,execute,directory,*,candidate_ids=None):
    ids=candidate_ids or [c['candidate_id'] for c in definitions['candidates']]
    byid={c['candidate_id']:c for c in definitions['candidates']}
    if not ids or len(ids)!=len(set(ids)) or not set(ids)<=byid.keys():raise ValueError('CONFIRMATION_CANDIDATES')
    required={'task_id','condition','data_hash','budget_hash','hardware_hash','runtime_hash','executor_hash','cache_profile','measurement_profile'}
    if set(context)!=required or any(not context[k] for k in required):raise ValueError('REFERENCE_CONTEXT')
    out=exclusive_directory(directory);ctx=digest(context)
    manifest={'definition_hash':definitions['definition_hash'],'context':context,'context_hash':ctx,'predeclared_candidate_ids':ids,
        'initial':3,'maximum':7,'extension_rule':'if relative MAD > 0.05 after first 3, append exactly 4 independent confirmations',
        'screening_in_reference_time':False,'formal_frozen':False}
    write(out/'manifest.json',manifest);observations=[];eligible=[]
    def run(candidate,role,repeat):
        request={'candidate_id':candidate['candidate_id'],'plan_hash':candidate['plan_hash'],'role':role,'repeat':repeat,'context_hash':ctx}
        stem=f'r{len(observations):04d}'
        write(out/(stem+'-request.json'),request)
        result=execute(candidate['plan'],request)
        if result.get('context_hash')!=ctx or result.get('plan_hash')!=candidate['plan_hash']:raise ValueError('CONFIRMATION_IDENTITY')
        if result.get('role')!=role:raise ValueError('CONFIRMATION_ROLE')
        record={**request,'result':result};write(out/(stem+'.json'),record);observations.append(record)
        valid=(result.get('semantic') is True and result.get('budget') is True and result.get('timing_valid') is True
               and result.get('status')=='COMPLETED' and type(result.get('exec_elapsed_ns')) is int and result['exec_elapsed_ns']>0)
        return result['exec_elapsed_ns'] if valid else None
    for ident in ids:
        candidate=byid[ident]
        if run(candidate,'REFERENCE_SCREEN',0) is None:continue
        times=[run(candidate,'TIMING_CONFIRMATION',i) for i in range(3)]
        if any(v is None for v in times):continue
        if relative_mad(times)>.05:times.extend(run(candidate,'TIMING_CONFIRMATION',i) for i in range(3,7))
        if any(v is None for v in times):continue
        stability=relative_mad(times)
        if stability>.05:continue
        eligible.append({'candidate_id':ident,'elapsed_ns':median(times),'relative_mad':stability,'confirmation_count':len(times)})
    best=min(eligible,key=lambda r:(r['elapsed_ns'],r['candidate_id'])) if eligible else None
    result={'reference_id':digest({'manifest':manifest,'observations':observations}),'context_hash':ctx,'confirmed':best is not None,
        'elapsed_ns':best['elapsed_ns'] if best else None,'chosen':best,'confirmed_candidates':eligible,
        'ref_missing':None if best else 'NO_SEMANTIC_BUDGET_VALID_STABLE_CONFIRMATION',
        'scope':'PREDECLARED_CANDIDATE_SET_NOT_GLOBAL_OPTIMUM','formal_ready':False}
    write(out/'reference.json',result);return result
