"""One closed two-slot batch, unchanged F1 worker, append-only private archive."""
from pathlib import Path
import hashlib,io,json,os,time,zipfile
from rcwg_spec.common import canonical,digest
from rcwg_spec.generation import validate_logical_contract,parse_response
from rcwg_exec.datasets import FileRegistry
from rcwg_exec.supervisor import run_f1_supervised
from rcwg_api.vertex import count_body,parse_count,parse_generation
from rcwg_api.policy import default_config
from rcwg_api.common import strict
from .admission import Admission,SLOTS,AMOUNTS
from .transport import CloudError,MODEL
from .contracts import OLD_P0_RESULT
from .prompts import physical_body,logical_body,audit_physical_parity

def _write(root,name,raw):
    path=root/name
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open('xb') as f:f.write(raw)
    os.chmod(path,0o600)

def load_object(store,ref):
    raw,receipt=store.get(ref['object'],ref['generation'])
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise CloudError('PINNED_OBJECT_CONTENT_CHANGED')
    return raw,receipt

def archive(root):
    files={};out=io.BytesIO();total=0
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(root.rglob('*')):
            if path.is_symlink():raise CloudError('ARCHIVE_SYMLINK')
            if not path.is_file():continue
            rel=path.relative_to(root).as_posix();raw=path.read_bytes();total+=len(raw)
            if total>32*1024*1024:raise CloudError('ARCHIVE_TOTAL_SIZE')
            files[rel]=hashlib.sha256(raw).hexdigest();z.writestr(rel,raw)
        z.writestr('FILES_SHA256.json',canonical(files))
    raw=out.getvalue()
    if len(raw)>8*1024*1024:raise CloudError('ARCHIVE_COMPRESSED_SIZE')
    return raw,files

def run_batch(m,*,store,vertex,root,execution_id,context):
    """Dependencies injected only by offline tests; CLI fixes native production types.

    Returned status is a runtime observation, not independent cloud acceptance.
    Exceptions never retry requests. An absent final marker is reconciled outside.
    """
    root=Path(root);root.mkdir(mode=0o700,parents=False,exist_ok=False)
    phase=m['phase'];admission=Admission(store,digest(m),execution_id,phase)
    report={'version':'CLOUD001_RUNTIME_OBSERVATION_1','phase':phase,'execution_id':execution_id,'manifest_sha256':digest(m),
            'context':context,'slots':{k:{'status':'NOT_ATTEMPTED','execution_started':False,'answer':'NOT_OBSERVED'} for k in ('p0','p1')},
            'stages':{},'reservations':[],'reservation_attempts':[],'model_dispatches':{'generate':0,'count':0},'automatic_retries':0,
            'expected_generation_denominator':2,'status':'STARTED','failure':None,'formal_ready':False,
            'measurement_scope':'ENGINEERING_DIAGNOSTIC_ONLY','budget_within':None,'invoice_cost_usd':None,
            'cloud_platform_scheduling_and_startup':'EXTERNAL_CONTROL_PLANE_REQUIRED','started_unix_ns':time.time_ns()}
    start=time.monotonic_ns();claimed=False
    def save(name,value):_write(root,name,canonical(value))
    save('manifest.json',m);save('context.json',context)
    try:
        report['claim']=admission.claim();claimed=True
        # Retrieval remains generation- and byte-pinned. The recipe has no path to prompt assembly.
        loaded={}
        for key,ref in m['inputs'].items():
            raw,receipt=load_object(store,ref);_write(root,'inputs/'+key,raw);loaded[key]=raw
        task=strict(loaded['task']);recipe=strict(loaded['recipe'])
        registry=FileRegistry(task,{recipe['source_id']:root/'inputs/records'},allowed_root=root)
        def execute(slot,plan):
            # Exact generated JSON is retained; no repair, substitution or second attempt.
            save('observations/'+slot+'/exact_model_plan.json',plan)
            result=run_f1_supervised(task,plan,registry=registry,recipe=recipe,output=root/'executions'/slot,
                condition_id='CLOUD001-DEVELOPMENT',record_id='cloud001-'+slot,generation_id='cloud001.'+slot+'.g0')
            save('observations/'+slot+'/execution.json',result)
            report['slots'][slot]={'status':result['status'],'static_status':result.get('static_status'),
                'execution_started':result.get('execution_started',False),'terminal_status':result.get('terminal_status'),
                'answer':result.get('verification',{}).get('status','NOT_OBSERVED'),'plan_sha256':digest(plan),
                'result_sha256':result.get('artifact',{}).get('content_sha256') if result.get('artifact') else None,
                'diagnostics':result.get('diagnostics',[]),'seal_sha256':result.get('seal_sha256')}
            return result
        (root/'executions').mkdir(mode=0o700)
        if phase=='replay':
            if vertex is not None:raise CloudError('REPLAY_TRANSPORT_MUST_BE_ABSENT')
            p0=execute('p0',strict(loaded['p0_plan']));p1=execute('p1',strict(loaded['p1_plan']))
            # These facts are tested again by the independent reader, not assumed from this label.
            ok=(p0.get('terminal_status')=='COMPLETED' and p0.get('verification',{}).get('status')=='PASS'
                and p0.get('artifact',{}).get('content_sha256')==OLD_P0_RESULT and p1.get('execution_started') is False
                and p1.get('status')=='PLAN_INVALID' and any(d.get('code')=='REFERENCE_SYNTAX' for d in p1.get('diagnostics',[])))
            report['status']='REPLAY_RUNTIME_OBSERVED_EXPECTED' if ok else 'REPLAY_RUNTIME_EXPECTATION_FAILED'
        else:
            def stage(key,body,prompt_evidence):
                report['stages'][key]={'status':'PREPARED','prompt':prompt_evidence}
                save('wire/'+key+'/generation_body.json',body)
                def call(suffix,kind,payload):
                    slot=key+'.'+suffix;raw=canonical(payload);request_sha=hashlib.sha256(raw).hexdigest()
                    _write(root,'wire/'+slot+'/request.json',raw)
                    report['reservation_attempts'].append({'slot':slot,'reserved_microusd_if_committed':AMOUNTS[slot]})
                    reservation=admission.reserve(slot,request_sha);report['reservations'].append(reservation)
                    # Mark possible dispatch before the network; token/transport audit refines uncertainty.
                    report['stages'][key][suffix]={'status':'RESERVED_DISPATCH_UNKNOWN','request_sha256':request_sha}
                    report['model_dispatches'][suffix]+=1
                    response=vertex.send(kind,raw)
                    _write(root,'wire/'+slot+'/response.bin',response.body)
                    observed={'status':'HTTP_OBSERVED','http_status':response.status,'request_sha256':request_sha,
                              'response_sha256':hashlib.sha256(response.body).hexdigest(),'elapsed_ns':response.elapsed_ns,
                              'headers':response.headers,'reserved_microusd':AMOUNTS[slot],'invoice_cost_usd':None,'automatic_retries':0}
                    save('wire/'+slot+'/receipt.json',observed)
                    report['stages'][key][suffix]=observed;admission.observe(slot,observed)
                    return response
                counted=parse_count(call('count','countTokens',count_body(body)))
                if counted['estimated_input_tokens']>12288:raise CloudError('INPUT_TOKEN_LIMIT_NO_GENERATION')
                generated=parse_generation(call('generate','generateContent',body),default_config('rcwg-509116'))
                save('wire/'+key+'/provider_parse.json',generated)
                report['stages'][key]['provider_status']=generated['status']
                report['stages'][key]['usage']=generated['usage']
                if generated['reported_model_version']!=MODEL:raise CloudError('REPORTED_MODEL_MISMATCH_NO_FALLBACK')
                if generated['status']!='PROVIDER_TEXT_READY':raise CloudError('PROVIDER_TEXT_NOT_READY_NO_RETRY')
                _write(root,'wire/'+key+'/exact_model_text.txt',generated['text'].encode('utf-8'))
                # Strict parsing does not remove fences, repair braces or modify references.
                parsed=parse_response(generated['text'].encode('utf-8'),kind=key.split('.')[1])
                save('wire/'+key+'/strict_parse.json',parsed)
                report['stages'][key]['status']='PARSED';return parsed['value']
            b0,e0=physical_body(task,'P0');plan0=stage('p0.physical',b0,e0);execute('p0',plan0)
            bl,el=logical_body(task);logical=stage('p1.logical',bl,el);validate_logical_contract(logical)
            save('logical_contract.json',logical)
            b1,e1=physical_body(task,'P1',logical);save('physical_parity.json',audit_physical_parity(b0,b1,task,logical))
            plan1=stage('p1.physical',b1,e1);execute('p1',plan1)
            report['status']='LIVE_RUNTIME_OBSERVED_COMPLETE'
    except Exception as e:
        # Never archive arbitrary exception strings (may contain transport or user content).
        report['status']='STOPPED_NO_RETRY';report['failure']={'exception_type':type(e).__name__,'code':getattr(e,'code',str(e) if type(e) is CloudError else 'CLOUD_OPERATION_FAILED')}
        if not claimed:report['status']='ADMISSION_NOT_ACQUIRED_NO_DISPATCH'
    report['elapsed_ns']=time.monotonic_ns()-start
    report['elapsed_scope']='SAME_CONTAINER_MONOTONIC_BATCH_INCLUDING_INPUTS_API_WORKER_VERIFIER_EXCLUDES_FINAL_ARCHIVE_UPLOAD'
    report['acknowledged_reserved_microusd']=sum(x['reservation']['reserved_microusd'] for x in report['reservations'])
    report['possibly_reserved_microusd']=sum(x['reserved_microusd_if_committed'] for x in report['reservation_attempts'])
    report['reservation_reconciliation']='INDEPENDENT_GCS_READ_REQUIRED; UNKNOWN_WRITES_ARE_NOT_REFUNDED'
    report['model_dispatch_count_scope']='CONSERVATIVE_POSSIBLE_DISPATCHES_AFTER_DURABLE_RESERVATION; AUTH_FAILURE_MAY_PRECEDE_HTTP'
    report['http_audit']=list(getattr(getattr(store,'http',None),'requests',[]))
    report['credential_audit']=list(getattr(getattr(getattr(store,'http',None),'identity',None),'audit',[]))
    report['gcs_receipts_before_archive']=list(getattr(store,'receipts',[]));save('report.json',report)
    if not claimed:return report
    raw,files=archive(root);upload_start=time.monotonic_ns()
    ar=store.create('cloud001/output/'+phase+'/archive.zip',raw)
    # The marker is last. Its absence is a missing outcome, not success.
    marker={'version':'CLOUD001_ARCHIVE_MARKER_1','execution_id':execution_id,'manifest_sha256':digest(m),'archive':ar,
            'files_sha256':files,'report_sha256':files['report.json'],'runtime_status':report['status'],
            'archive_upload_elapsed_ns':time.monotonic_ns()-upload_start,'formal_ready':False,
            'independent_review':'PENDING','platform_terminal_state':'EXTERNAL_RECONCILIATION_REQUIRED'}
    report['final_marker_receipt']=store.create('cloud001/output/'+phase+'/complete.json',canonical(marker))
    return report
