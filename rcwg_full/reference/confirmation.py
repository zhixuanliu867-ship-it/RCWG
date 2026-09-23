"""Durable independent screening/confirmation; uncertainty never causes resend."""
import json
import uuid
from statistics import median
from rcwg_full.evidence import digest,sha,read,write,exclusive_directory,safe_path,source_hashes


class ConfirmationPaused(RuntimeError):pass


def relative_mad(values):
    center=median(values)
    return median(abs(v-center) for v in values)/center if center>0 else float('inf')


def context_identity(context):
    from rcwg_spec.binding import RunnerContext
    if isinstance(context,RunnerContext):return context.as_dict(),context.comparison_context_hash
    required={'task_id','condition','data_hash','budget_hash','hardware_hash','runtime_hash','executor_hash','cache_profile','measurement_profile'}
    if type(context) is not dict or set(context)!=required or any(not context[k] for k in required):raise ValueError('REFERENCE_CONTEXT')
    return context,digest(context)


def confirm(definitions,context,execute,directory,*,candidate_ids=None,resume=False):
    ids=[c['candidate_id'] for c in definitions['candidates']] if candidate_ids is None else candidate_ids
    byid={c['candidate_id']:c for c in definitions['candidates']}
    if len(byid)!=len(definitions['candidates']) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=byid.keys():raise ValueError('CONFIRMATION_CANDIDATES')
    if any(digest(c['plan'])!=c['plan_hash'] for c in byid.values()):raise ValueError('CONFIRMATION_PLAN_HASH')
    context,ctx=context_identity(context);sources=source_hashes()
    out=safe_path(directory) if resume else exclusive_directory(directory)
    prior=json.loads(read(out/'manifest.json')) if resume else None
    manifest={'revision':'FULL001_REFERENCE_CONFIRMATION_2','run_id':prior['run_id'] if prior else str(uuid.uuid4()),
        'definition_hash':definitions['definition_hash'],'definitions_payload_hash':digest(definitions),
        'source_hash':digest(sources),'context':context,'context_hash':ctx,'predeclared_candidate_ids':ids,
        'initial':3,'maximum':7,'extension_rule':'if relative MAD > 0.05 after first 3, append exactly 4 independent confirmations',
        'screening_in_reference_time':False,'formal_frozen':False}
    if resume:
        if prior!=manifest:raise ValueError('CONFIRMATION_RESUME_IDENTITY')
    else:write(out/'manifest.json',manifest)
    observations=[];eligible=[];completed=set()
    def run(candidate,role,repeat):
        if source_hashes()!=sources:raise ConfirmationPaused('SOURCE_CHANGED')
        request={'candidate_id':candidate['candidate_id'],'plan_hash':candidate['plan_hash'],'role':role,'repeat':repeat,'context_hash':ctx}
        request['attempt_id']=str(uuid.uuid5(uuid.UUID(manifest['run_id']),digest(request)))
        stem=f'r{len(observations):04d}';request_file=out/(stem+'-request.json');record_file=out/(stem+'.json');commit_file=out/(stem+'-commit.json')
        if request_file.exists():
            if json.loads(read(request_file))!=request:raise ValueError('CONFIRMATION_REQUEST_CHANGED')
            if not record_file.exists() or not commit_file.exists():raise ConfirmationPaused('REQUEST_WITHOUT_COMMITTED_OUTCOME:'+stem)
            commit=json.loads(read(commit_file))
            if commit!={'request_sha256':sha(read(request_file)),'record_sha256':sha(read(record_file))}:raise ValueError('CONFIRMATION_OUTCOME_CHANGED')
            record=json.loads(read(record_file))
            if {k:record.get(k) for k in request}!=request:raise ValueError('CONFIRMATION_RECORD_IDENTITY')
            result=record['result']
        else:
            if record_file.exists() or commit_file.exists():raise ValueError('CONFIRMATION_ORPHAN_OUTCOME')
            write(request_file,request)
            try:result=execute(candidate['plan'],dict(request))
            except Exception as exc:result={**request,'status':'INFRA_FAILURE','exception_type':type(exc).__name__,'message':str(exc),'reconciliation_required':True}
            record={**request,'result':result};write(record_file,record)
            write(commit_file,{'request_sha256':sha(read(request_file)),'record_sha256':sha(read(record_file))})
        observations.append(record)
        if type(result) is not dict or any(result.get(k)!=request[k] for k in ['context_hash','plan_hash','role']):raise ValueError('CONFIRMATION_IDENTITY')
        if result.get('status') in {'INFRA_FAILURE','UNKNOWN','SENT_UNCONFIRMED','SERVICE_DRIFT','NOT_AUTHORIZED'} or result.get('reconciliation_required'):
            raise ConfirmationPaused('ATTEMPT_REQUIRES_RECONCILIATION:'+stem)
        valid=(result.get('semantic') is True and result.get('budget') is True and result.get('timing_valid') is True
               and result.get('status')=='COMPLETED' and type(result.get('exec_elapsed_ns')) is int and result['exec_elapsed_ns']>0)
        return result['exec_elapsed_ns'] if valid else None
    paused=None
    try:
        for ident in ids:
            candidate=byid[ident]
            if run(candidate,'REFERENCE_SCREEN',0) is None:completed.add(ident);continue
            times=[run(candidate,'TIMING_CONFIRMATION',i) for i in range(3)]
            if any(v is None for v in times):completed.add(ident);continue
            if relative_mad(times)>.05:times.extend(run(candidate,'TIMING_CONFIRMATION',i) for i in range(3,7))
            completed.add(ident)
            if any(v is None for v in times):continue
            stability=relative_mad(times)
            if stability>.05:continue
            eligible.append({'candidate_id':ident,'elapsed_ns':median(times),'relative_mad':stability,'confirmation_count':len(times)})
    except ConfirmationPaused as exc:paused=str(exc)
    best=min(eligible,key=lambda r:(r['elapsed_ns'],r['candidate_id'])) if eligible and paused is None else None
    result={'reference_id':digest({'manifest':manifest,'observations':observations}),'context_hash':ctx,'confirmed':best is not None,
        'status':'PAUSED_RECONCILIATION' if paused else 'COMPLETE','paused_reason':paused,'completed_candidate_ids':sorted(completed),
        'elapsed_ns':best['elapsed_ns'] if best else None,'chosen':best,'confirmed_candidates':eligible,
        'ref_missing':None if best else paused or 'NO_SEMANTIC_BUDGET_VALID_STABLE_CONFIRMATION',
        'scope':'PREDECLARED_CANDIDATE_SET_NOT_GLOBAL_OPTIMUM','formal_ready':False}
    if paused:write(out/('paused-'+str(uuid.uuid4())+'.json'),result)
    elif (out/'reference.json').exists():
        if json.loads(read(out/'reference.json'))!=result:raise ValueError('CONFIRMATION_REFERENCE_CHANGED')
    else:write(out/'reference.json',result)
    return result
