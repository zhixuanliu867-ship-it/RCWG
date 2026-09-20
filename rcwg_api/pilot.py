"""Two predeclared generation attempts; each valid model plan enters EXEC unchanged.

Generation slots are frozen BEFORE unknown provider responses exist. EXEC's plan-
bound expected manifest is frozen later, before worker launch. These are different
identities; offline mock response hashes are not a live campaign prerequisite.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import os
import time
from .common import ROOT,Archive,ApiError,fail,canonical,strict,read,sha,digest,seal_tree
from .policy import validate_config,validate_approval,source_snapshot,check_exec_sources,approval_template,endpoint
from .vertex import GcloudToken,VertexTransport,make_body,count_body,parse_count,parse_generation
from .budget import Budget
from rcwg_spec.generation import build_request,parse_response
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.common import ContractError


def make_manifest(task,config,source_hashes,*,recipe_sha256=None):
    validate_public_task(task);validate_config(config)
    slots=[{'generation_id':'api001.p0.g0','protocol':'P0','stages':['physical'],'execution_repeat_id':'r0'},
           {'generation_id':'api001.p1.g0','protocol':'P1','stages':['logical','physical'],'execution_repeat_id':'r0'}]
    return {'version':'API001_EXPECTED_GENERATIONS_1','task_sha256':digest(task),'config':deepcopy(config),
            'source_sha256':deepcopy(source_hashes),'verifier_recipe_sha256':recipe_sha256,'expected_generations':slots,
            'fixed_generation_denominator':2,'planned_generate_content_requests':3,'planned_count_tokens_requests':3,
            'transport_retries':0,'regeneration_retries':0,'formal_ready':False,
            'scope':'F1_API_ENGINEERING_NOT_FROZEN_BENCHMARK'}

def prepare(output,config):
    check_exec_sources()
    from rcwg_exec.demo import prepare_fixture
    store=Archive(Path(output))
    task,plans,recipe,data=prepare_fixture(store.path/'fixture',n=257,k=20)
    sources=source_snapshot();manifest=make_manifest(task,config,sources,recipe_sha256=digest(recipe))
    store.json('expected_generations.json',manifest)
    store.json('approval.template.json',approval_template(manifest))
    return {'status':'API001_PREPARED_NOT_CALLED','manifest_sha256':digest(manifest),'formal_ready':False,
            'actual_model_requests':0,'approval_required':True}

def supervised_execution(task,plan,recipe,data_path,output,generation_id):
    # Production live path has one executor, no reference/mock fallback.
    from rcwg_exec.datasets import FileRegistry
    from rcwg_exec.supervisor import run_f1_supervised
    registry=FileRegistry(task,{recipe['source_id']:Path(data_path)},allowed_root=Path(data_path).parent)
    return run_f1_supervised(task,plan,registry=registry,recipe=recipe,output=output,
                             record_id=generation_id,generation_id=generation_id,repeat_id='r0')

def run_pilot(task,recipe,data_path,manifest,*,output,transport,mode='MOCK',approval=None,
              offline_acceptance=None,executor=None):
    if mode not in {'MOCK','LIVE'}:fail('MODE_INVALID')
    task=deepcopy(task);recipe=deepcopy(recipe);manifest=deepcopy(manifest)
    if manifest!=make_manifest(task,manifest['config'],manifest['source_sha256'],recipe_sha256=manifest.get('verifier_recipe_sha256')):fail('EXPECTED_MANIFEST_INVALID')
    config=validate_config(manifest['config'])
    if mode=='LIVE':
        if type(transport) is not VertexTransport or executor is not None:fail('LIVE_TRANSPORT_OR_EXECUTOR')
        check_exec_sources()
        if manifest.get('verifier_recipe_sha256')!=digest(recipe):fail('VERIFIER_RECIPE_NOT_PREFROZEN')
        if sha(Path(data_path).read_bytes())!=task['datasets'][0]['data_sha256']:fail('DATA_CHANGED_BEFORE_API')
        if source_snapshot()!=manifest['source_sha256']:fail('SOURCE_CHANGED')
        validate_approval(approval,manifest)
        if offline_acceptance is None:fail('OFFLINE_ACCEPTANCE_REQUIRED')
        raw=Path(offline_acceptance).read_bytes();passed=strict(raw)
        if sha(raw)!=approval['offline_api_acceptance_sha256'] or passed.get('status')!='API001_TARGET_OFFLINE_PASS':fail('OFFLINE_ACCEPTANCE_MISMATCH')
        if passed.get('source_sha256')!=manifest['source_sha256']:fail('OFFLINE_SOURCE_MISMATCH')
        from .auth_binding import validate_live_binding
        validate_live_binding(config)
        if transport.config!=config or type(transport.token_source) is not GcloudToken or transport.token_source.config!=config:
            fail('LIVE_AUTH_TRANSPORT_BINDING')
    elif getattr(transport,'mode',None)!='MOCK':fail('MOCK_CANNOT_USE_LIVE_TRANSPORT')
    executor=supervised_execution if executor is None else executor
    store=Archive(Path(output));manifest_hash=digest(manifest)
    store.json('expected_generations.json',manifest)
    if mode=='LIVE':store.json('owner_approval.json',approval)
    # One persistent binding for this prepared pilot; new output paths cannot reset
    # this budget or reuse the same request IDs. A different manifest requires a
    # newly approved preparation, not an automatic retry.
    budget=Budget(store.path.parent/'api001-budget.sqlite',manifest_hash,config)
    source_at_start=source_snapshot();rows=[];stop_reason=None;versions=[];physical_calls=[]
    transport_counter_before=getattr(transport,'dispatch_count',0)
    store.json('source_at_start.json',source_at_start)
    if mode=='LIVE':
        # Archive authentication failures with zero paid reservations and both slots.
        try:
            transport.token_source.preflight()
            transport.token_source()
        except ApiError as error:
            stop_reason=error.code

    def wire(stage_store,request_id,kind,body):
        if mode=='LIVE':
            validate_approval(approval,manifest)
            if source_snapshot()!=source_at_start:fail('SOURCE_CHANGED')
        encoded=canonical(body)
        if len(encoded)>131072:fail('REQUEST_BYTE_LIMIT')
        stage_store.put(kind+'.request.json',encoded)
        amount=budget.reserve(request_id,kind)
        stage_store.json(kind+'.reservation.json',{'request_id':request_id,'kind':kind,'amount_microusd':amount,
                       'reserved_before_io':True,'manifest_sha256':manifest_hash,'mode':mode})
        before=getattr(transport,'dispatch_count',0)
        started=time.time_ns();monotonic=time.perf_counter_ns()
        try:
            response=transport.send(kind,encoded,request_id)
        except Exception as error:
            # No request contents, credentials, URL queries or exception strings
            # enter public diagnostics. Interrupted reservations stay consumed.
            code=error.code if isinstance(error,ApiError) else 'TRANSPORT_UNCERTAIN_NO_RETRY'
            record={'request_id':request_id,'kind':kind,'endpoint':endpoint(config,kind),'mode':mode,'status':code,'started_unix_ns':started,
                    'client_elapsed_ns':time.perf_counter_ns()-monotonic,'provider_receipt':'UNKNOWN',
                    'dispatch_attempted':getattr(transport,'dispatch_count',0)>before,'request_sha256':sha(encoded),
                    'transport_retry_index':0,'regeneration_index':0}
            physical_calls.append(record)
            h=stage_store.json(kind+'.observation.json',record);budget.observe(request_id,code,h)
            raise ApiError(code) from None
        safe_headers={k:v for k,v in response.headers.items() if k.lower() in {'x-request-id','x-goog-request-id','content-type','retry-after'}}
        record={'request_id':request_id,'kind':kind,'endpoint':endpoint(config,kind),'mode':mode,'status':'HTTP_OBSERVED','http_status':response.status,
                'started_unix_ns':started,'client_elapsed_ns':response.elapsed_ns,'provider_receipt':'HTTP_RESPONSE_OBSERVED',
                'dispatch_attempted':True,'request_sha256':sha(encoded),'response_sha256':sha(response.body),
                'safe_response_headers':safe_headers,'transport_retry_index':0,'regeneration_index':0}
        physical_calls.append(record)
        stage_store.put(kind+'.response.bin',response.body)
        h=stage_store.json(kind+'.observation.json',record);budget.observe(request_id,'HTTP_'+str(response.status),h)
        return response

    for slot in manifest['expected_generations']:
        row={'generation_id':slot['generation_id'],'protocol':slot['protocol'],'status':'NOT_ATTEMPTED',
             'stages':[],'execution':None,'plan_sha256':None,'stop_reason':stop_reason}
        if stop_reason is not None:rows.append(row);continue
        attempt=Archive(store.path/slot['generation_id']);logical=None;plan=None
        try:
            for stage in slot['stages']:
                stage_store=Archive(attempt.path/stage);request_id=slot['generation_id']+'.'+stage
                assembled=build_request(task,protocol=slot['protocol'],stage=stage,generation_attempt_id=slot['generation_id'],
                         request_id=request_id,logical_contract=logical)
                # B serializer metadata remains honestly MOCK. Only its public
                # messages and byte-pinned sources are used by this LIVE adapter.
                assembly_evidence={k:assembled[k] for k in ('protocol','stage','generation_attempt_id','request_id',
                    'task_input_hash','normalized_input_hash','logical_contract_hash','planning_supplement_sha256','source_hashes','budget')}
                assembly_evidence['source_component']='SPEC_B_PUBLIC_SERIALIZER_NOT_PROVIDER_TELEMETRY'
                stage_store.json('public_assembly_source.json',assembly_evidence)
                body=make_body(assembled,config)
                counter=parse_count(wire(stage_store,request_id+'.count','countTokens',count_body(body)))
                stage_store.json('count_estimate.json',counter)
                if counter['estimated_input_tokens']>config['max_input_tokens']:fail('INPUT_TOKEN_CAP')
                response=wire(stage_store,request_id+'.generate','generateContent',body)
                parsed=parse_generation(response,config)
                observation={k:v for k,v in parsed.items() if k!='text'}
                stage_store.json('provider_observation.json',observation)
                row['stages'].append({'stage':stage,'status':parsed['status'],'provider':observation})
                if parsed['status']!='PROVIDER_TEXT_READY':fail(parsed['status'])
                raw=parsed['text'].encode('utf8');stage_store.put('model_text.bin',raw)
                # Preserve provider text even when strict RCWG parsing rejects it.
                result=parse_response(raw,kind=stage);stage_store.json('parsed.json',result)
                version=parsed['reported_model_version']
                if mode=='LIVE':
                    if type(version) is not str or not version or not (version==config['model'] or version.startswith(config['model']+'-')):
                        fail('MODEL_VERSION_UNCONFIRMED')
                    if versions and version!=versions[0]:fail('MODEL_VERSION_DRIFT')
                    if parsed['usage']['cost_usd_list_price_upper_estimate'] is None:fail('USAGE_INCOMPLETE')
                    from decimal import Decimal
                    estimated=Decimal(parsed['usage']['cost_usd_list_price_upper_estimate'])*1000000
                    if estimated>config['reservation_microusd']['generateContent']:fail('OBSERVED_COST_EXCEEDS_RESERVATION')
                    usage=parsed['usage']['provider_fields']
                    if usage['promptTokenCount']>config['max_input_tokens']:fail('OBSERVED_INPUT_OVER_CAP')
                if type(version) is str:versions.append(version)
                if stage=='logical':logical=result['value']
                else:plan=result['value']
            if plan is None:fail('PLAN_MISSING')
            row['plan_sha256']=digest(plan);attempt.json('exact_model_plan.json',plan)
            if source_snapshot()!=source_at_start:fail('SOURCE_CHANGED')
            # The private recipe is passed only to the trusted executor/verifier.
            execution=executor(task,plan,recipe,data_path,attempt.path/'execution',slot['generation_id'])
            row['execution']=execution;row['status']='GENERATION_PARSED_EXECUTION_OBSERVED'
            if mode=='LIVE' and (execution.get('terminal_status') in {'INFRA_FAILURE','UNKNOWN'} or execution.get('status')=='RUNTIME_IMPLEMENTATION_GAP'):
                stop_reason='EXECUTION_FACILITY_REVIEW_REQUIRED'
        except (ApiError,ContractError) as error:
            row['status']='GENERATION_OR_ADMISSION_FAILED';row['error_code']=error.code
            # A transport/model-format failure stops this fixed pilot. Remaining
            # planned slots remain NOT_ATTEMPTED, never removed or regenerated.
            stop_reason=error.code
        except (OSError,ValueError,TypeError,KeyError,RuntimeError,ImportError) as error:
            row['status']='API_PIPELINE_FACILITY_ERROR';row['error_code']='PIPELINE_'+type(error).__name__
            stop_reason=row['error_code']
        attempt.json('generation.json',row);rows.append(row)
    if mode=='LIVE':store.json('credential_audit.json',transport.token_source.audit)
    store.json('physical_requests.json',physical_calls)
    store.json('budget_snapshot.json',budget.summary())
    source_unchanged=source_snapshot()==source_at_start
    report={'version':'API001_REPORT_1','mode':mode,'status':'API001_MOCK_RECORDED' if mode=='MOCK' else 'API001_LIVE_RECORDED',
            'manifest_sha256':manifest_hash,'fixed_generation_denominator':2,'generations':rows,
            'planned_generate_requests':3,'planned_count_requests':3,
            'actual_generate_dispatches':sum(x['kind']=='generateContent' and x['dispatch_attempted'] for x in physical_calls),
            'actual_count_dispatches':sum(x['kind']=='countTokens' and x['dispatch_attempted'] for x in physical_calls),
            'real_model_service_dispatches':getattr(transport,'dispatch_count',0)-transport_counter_before if mode=='LIVE' else 0,
            'observed_transport_dispatches':getattr(transport,'dispatch_count',0)-transport_counter_before,
            'transport_and_ledger_counts_match':getattr(transport,'dispatch_count',0)-transport_counter_before==sum(x['dispatch_attempted'] for x in physical_calls),
            'provider_received_request_count':None,'provider_received_request_count_reason':'DISPATCH_IS_NOT_SERVER_RECEIPT',
            'reported_model_versions':sorted(set(versions)),'stop_reason':stop_reason,'source_unchanged':source_unchanged,
            'real_model_quality_statistics':'NOT_A_FORMAL_BENCHMARK','live_acceptance':'INDEPENDENT_REVIEW_REQUIRED' if mode=='LIVE' else 'NOT_EXECUTED',
            'cloud_resource_mutations':0,'iam_policy_mutations':0,
            'credential_command_invocations':getattr(getattr(transport,'token_source',None),'command_invocations',None),
            'credential_metadata_command_invocations':getattr(getattr(transport,'token_source',None),'metadata_command_invocations',None),
            'login_account':config['login_account'] if mode=='LIVE' else None,
            'service_account':config['service_account'] if mode=='LIVE' else None,
            'credential_service_http_requests':None,'credential_scope':'SHORT_LIVED_AUTHENTICATION_SEPARATE_FROM_MODEL_DISPATCHES',
            'formal_ready':False,'full_api001_accepted':False,
            'budget_within':None,'budget_reason':'REFERENCE_MEMORY_ISOLATION_NOT_VALIDATED'}
    store.json('report.json',report)
    files=seal_tree(store.path)
    seal={'version':'API001_PRIVATE_SEAL_1','manifest_sha256':manifest_hash,'files_sha256':files}
    seal_hash=store.json('seal.json',seal)
    return {'report':report,'seal_sha256':seal_hash,'reread':audit(store.path,manifest_hash,seal_hash)}

def audit(path,manifest_hash,seal_hash):
    path=Path(path);raw=(path/'seal.json').read_bytes()
    if sha(raw)!=seal_hash:fail('PILOT_SEAL_CHANGED')
    sealed=strict(raw)
    if sealed['manifest_sha256']!=manifest_hash:fail('PILOT_MANIFEST_CHANGED')
    if seal_tree(path,ignore={'seal.json'})!=sealed['files_sha256']:fail('PILOT_FILE_SET_OR_CONTENT_CHANGED')
    manifest=read(path/'expected_generations.json');report=read(path/'report.json')
    if digest(manifest)!=manifest_hash or report['manifest_sha256']!=manifest_hash:fail('PILOT_MANIFEST_CHANGED')
    ids=[s['generation_id'] for s in manifest['expected_generations']]
    if report['fixed_generation_denominator']!=len(ids) or [r['generation_id'] for r in report['generations']]!=ids:fail('PILOT_DENOMINATOR')
    for generation in report['generations']:
        if generation['plan_sha256'] is not None:
            root=path/generation['generation_id']
            plan=read(root/'exact_model_plan.json')
            parsed=read(root/'physical/parsed.json')['value']
            if plan!=parsed or digest(plan)!=generation['plan_sha256']:fail('PLAN_REPLACED')
    return {'status':'API001_EVIDENCE_REOPENED','fixed_generation_denominator':len(ids),
            'formal_ready':False,'transport_authenticity':'ADAPTER_PROVENANCE_REQUIRES_LIVE_REVIEW'}
