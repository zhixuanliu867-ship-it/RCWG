"""Offline reread of downloaded GCS bytes; never executes or repairs a plan."""
from pathlib import Path,PurePosixPath
import hashlib,io,json,os,stat,zipfile
from rcwg_api.common import strict
from rcwg_spec.common import canonical,digest
from rcwg_spec.binding import ExpectedManifest
from rcwg_spec.compiler import validate_workflow
from rcwg_spec.generation import parse_response
from rcwg_api.vertex import Response,parse_count,parse_generation,count_body
from rcwg_api.policy import default_config
from rcwg_exec.sealing import reopen_run
from rcwg_exec.verifier import verify_f1
from .transport import CloudError,MODEL
from .contracts import OLD_P0_RESULT
from .prompts import physical_body,logical_body,audit_physical_parity

def unpack_checked(raw,marker,expected_manifest,output):
    if hashlib.sha256(raw).hexdigest()!=marker['archive']['sha256'] or marker['manifest_sha256']!=digest(expected_manifest):raise CloudError('ARCHIVE_EXTERNAL_HASH_BINDING')
    output=Path(output)
    if output.exists() or any(p.is_symlink() for p in [output,*output.parents]):raise CloudError('REVIEW_NEW_PRIVATE_DIRECTORY_REQUIRED')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist();size=0
        if len(names)!=len(set(names)) or len(names)>5000:raise CloudError('ARCHIVE_FILE_SET')
        for info in z.infolist():
            p=PurePosixPath(info.filename);size+=info.file_size
            if p.is_absolute() or any(part in ('.','..') for part in info.filename.split('/')) or '\\' in info.filename or info.is_dir() or stat.S_ISLNK(info.external_attr>>16):raise CloudError('ARCHIVE_PATH')
            if size>32*1024*1024 or info.file_size>8*1024*1024:raise CloudError('ARCHIVE_SIZE')
        files=strict(z.read('FILES_SHA256.json'))
        if files!=marker['files_sha256'] or set(files)!=set(names)-{'FILES_SHA256.json'}:raise CloudError('ARCHIVE_FILE_MANIFEST')
        for name,h in files.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=h:raise CloudError('ARCHIVE_MEMBER_HASH')
        if z.read('manifest.json')!=canonical(expected_manifest):raise CloudError('ARCHIVE_MANIFEST_CHANGED')
        output.mkdir(mode=0o700,parents=True,exist_ok=False)
        for name in names:
            p=output/name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with p.open('xb') as f:f.write(z.read(name))
            os.chmod(p,0o600)
    return output

def review(raw,marker,expected_manifest,output):
    root=unpack_checked(raw,marker,expected_manifest,output);m=expected_manifest
    read=lambda n:strict((root/n).read_bytes())
    report=read('report.json');task=read('inputs/task');recipe=read('inputs/recipe');slots={};calls=[]
    if report['manifest_sha256']!=digest(m) or report['formal_ready'] is not False or report['budget_within'] is not None or report['expected_generation_denominator']!=2:raise CloudError('REPORT_SCOPE')
    for key,ref in m['inputs'].items():
        if hashlib.sha256((root/('inputs/'+key)).read_bytes()).hexdigest()!=ref['sha256']:raise CloudError('REVIEW_INPUT_BINDING')
    for slot in ('p0','p1'):
        planfile=root/('observations/'+slot+'/exact_model_plan.json')
        if not planfile.exists():
            slots[slot]={'status':'NOT_OBSERVED','execution_started':False,'answer':'NOT_OBSERVED'};continue
        plan=strict(planfile.read_bytes());record=read('observations/'+slot+'/execution.json');compiled=validate_workflow(task,plan)
        if m['phase']=='replay' and plan!=read('inputs/'+slot+'_plan'):raise CloudError('REPLAY_PLAN_REPAIRED')
        if compiled['status']!='IR_VALIDATED':
            if record['status']!=compiled['status'] or record['execution_started'] is not False or record.get('diagnostics')!=compiled['diagnostics'] or (root/'executions'/slot).exists():raise CloudError('STATIC_REFUSAL_REVIEW')
            slots[slot]={'status':compiled['status'],'diagnostics':compiled['diagnostics'],'execution_started':False,'answer':'NOT_OBSERVED'};continue
        if not record.get('execution_started'):
            slots[slot]={'status':record['status'],'execution_started':False,'answer':'NOT_OBSERVED'};continue
        execution=root/'executions'/slot;em=ExpectedManifest((execution/'expected_manifest.json').read_bytes())
        if read('executions/'+slot+'/plan.json')!=plan or read('executions/'+slot+'/task.json')!=task:raise CloudError('EXECUTION_INPUT_BINDING')
        reopened=reopen_run(execution,manifest=em,seal_sha256=record['seal_sha256'])
        independent={'status':'NOT_OBSERVED'}
        if reopened['terminal_status']=='COMPLETED':
            independent=verify_f1(task=task,recipe=recipe,data_path=root/'inputs/records',artifact_path=execution/'worker/result.json',artifact_meta=record['artifact'])
            if independent!=record['verification']:raise CloudError('INDEPENDENT_ANSWER_MISMATCH')
        slots[slot]={'status':reopened['terminal_status'],'execution_started':True,'answer':independent['status'],
                     'result_sha256':independent.get('actual_result_sha256'),'seal_sha256':record['seal_sha256']}
    parity=None
    if m['phase']=='live':
        previous_logical=None
        for stage in ('p0.physical','p1.logical','p1.physical'):
            f=root/('wire/'+stage+'/generation_body.json')
            if not f.exists():continue
            expected_body,_=(physical_body(task,'P0') if stage=='p0.physical' else logical_body(task) if stage=='p1.logical' else physical_body(task,'P1',previous_logical))
            body=strict(f.read_bytes())
            if body!=expected_body:raise CloudError('FINAL_PROVIDER_PAYLOAD_MISMATCH')
            for suffix,kind in (('count','countTokens'),('generate','generateContent')):
                base='wire/'+stage+'.'+suffix
                request_file=root/(base+'/request.json');response_file=root/(base+'/response.bin')
                if not request_file.exists():continue
                wire=request_file.read_bytes();want=count_body(body) if suffix=='count' else body
                if wire!=canonical(want):raise CloudError('WIRE_CHANGED')
                if not response_file.exists():calls.append({'stage':stage,'kind':kind,'status':'UNKNOWN_RESPONSE'});continue
                receipt=read(base+'/receipt.json');response=response_file.read_bytes()
                if receipt['request_sha256']!=hashlib.sha256(wire).hexdigest() or receipt['response_sha256']!=hashlib.sha256(response).hexdigest():raise CloudError('WIRE_HASH')
                calls.append({'stage':stage,'kind':kind,'status':'HTTP_OBSERVED','http_status':receipt['http_status']})
                if receipt['http_status']!=200:continue
                observed=Response(receipt['http_status'],response,receipt['headers'],receipt['elapsed_ns'])
                if suffix=='count':parse_count(observed);continue
                generated=parse_generation(observed,default_config('rcwg-509116'))
                if generated!=read('wire/'+stage+'/provider_parse.json'):raise CloudError('PROVIDER_PARSE_REPLAY')
                if generated['status']!='PROVIDER_TEXT_READY' or generated['reported_model_version']!=MODEL:continue
                parsed=parse_response(generated['text'].encode(),kind=stage.split('.')[1])
                if stage=='p1.logical':
                    previous_logical=parsed['value']
                    if previous_logical!=read('logical_contract.json'):raise CloudError('LOGICAL_SUBSTITUTION')
                else:
                    slot=stage.split('.')[0]
                    if parsed['value']!=read('observations/'+slot+'/exact_model_plan.json'):raise CloudError('MODEL_PLAN_REPAIR')
        if previous_logical is not None and (root/'wire/p1.physical/generation_body.json').exists():
            parity=audit_physical_parity(read('wire/p0.physical/generation_body.json'),read('wire/p1.physical/generation_body.json'),task,previous_logical)
    else:
        if report['model_dispatches']!={'count':0,'generate':0} or (root/'wire').exists():raise CloudError('REPLAY_MODEL_REQUEST_OBSERVED')
    replay_expected=(slots['p0'].get('status')=='COMPLETED' and slots['p0'].get('answer')=='PASS' and slots['p0'].get('result_sha256')==OLD_P0_RESULT
                     and slots['p1'].get('status')=='PLAN_INVALID' and any(d.get('code')=='REFERENCE_SYNTAX' for d in slots['p1'].get('diagnostics',[]))) if m['phase']=='replay' else None
    return {'version':'CLOUD001_ARTIFACT_REVIEW_1','status':'CLOUD001_ARTIFACTS_REOPENED','phase':m['phase'],'manifest_sha256':digest(m),
            'archive_sha256':hashlib.sha256(raw).hexdigest(),'slots':slots,'transport_observations':calls,'physical_parity':parity,'replay_expected':replay_expected,
            'generation_denominator':2,'formal_ready':False,'cloud_engineering_accepted':False,
            'outstanding':['INDEPENDENT_PLATFORM_IDENTITY_IMAGE_AND_TERMINAL_RECONCILIATION','INDEPENDENT_GCS_RESERVATION_AND_GENERATION_REREAD']}

def missing_archive_reconciliation(expected_manifest,platform_terminal):
    """Use even if OOM/kill left no report; never drop expected generation slots."""
    return {'version':'CLOUD001_MISSING_ARCHIVE_RECONCILIATION_1','phase':expected_manifest['phase'],'manifest_sha256':digest(expected_manifest),
            'platform_terminal':platform_terminal,'status':'INCOMPLETE_EVIDENCE','slots':{s:{'status':'UNKNOWN','answer':'NOT_OBSERVED'} for s in ('p0','p1')},
            'generation_denominator':2,'possible_dispatches':'UNKNOWN_UNTIL_DURABLE_RESERVATIONS_READ','retry_authorized':False,'formal_ready':False}
