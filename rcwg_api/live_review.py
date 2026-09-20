"""Read-only live evidence gate. Offline/synthetic archives cannot satisfy it."""
from pathlib import Path
from .common import read,strict,sha,digest,fail,ApiError
from .policy import endpoint,MODEL,validate_config
from .pilot import audit
from .vertex import Response,parse_count,parse_generation
from rcwg_spec.generation import parse_response

def review_live(directory,*,manifest_sha256,seal_sha256):
    directory=Path(directory)
    audit(directory,manifest_sha256,seal_sha256)
    report=read(directory/'report.json');manifest=read(directory/'expected_generations.json')
    if report['mode']!='LIVE' or report['real_model_service_dispatches']==0:fail('LIVE_EVIDENCE_REQUIRED')
    config=validate_config(manifest['config'])
    from .auth_binding import validate_live_binding
    validate_live_binding(config)
    auth=read(directory/'credential_audit.json')
    issued=[r for r in auth if r.get('operation')=='SHORT_LIVED_CREDENTIAL_ISSUANCE']
    if not issued or len(issued)!=report['credential_command_invocations']:fail('LIVE_AUTH_AUDIT_MISSING')
    windows=config.get('auth_mode')=='GCLOUD_USER'
    for r in issued:
        if any(r.get(k)!=config[k] for k in ('project_id','login_account','service_account')):fail('LIVE_AUTH_IDENTITY')
        if '--account='+config['login_account'] not in r['argv'] or '--project='+config['project_id'] not in r['argv']:fail('LIVE_AUTH_COMMAND_BINDING')
        if windows:
            if '--billing-project='+config['project_id'] not in r['argv'] or any('impersonat' in arg for arg in r['argv']):fail('LIVE_USER_COMMAND_BINDING')
            if r.get('auth_mode')!='GCLOUD_USER' or r.get('principal_type')!='USER':fail('LIVE_USER_IDENTITY')
        elif '--impersonate-service-account='+config['service_account'] not in r['argv']:fail('LIVE_AUTH_COMMAND_BINDING')
    captured='CREDENTIAL_CAPTURED_IN_WINDOWS_MEMORY' if windows else 'CREDENTIAL_CAPTURED_IN_MEMORY'
    if not any(r.get('status')==captured and r.get('exit_code')==0 for r in issued):fail('LIVE_AUTH_ISSUANCE_UNVERIFIED')
    calls=read(directory/'physical_requests.json')
    call_map={r['request_id']:r for r in calls}
    if len(call_map)!=len(calls):fail('LIVE_REQUEST_ID_DUPLICATE')
    versions=[];incomplete=[];executed=[];count_total=0;generate_total=0
    for slot,row in zip(manifest['expected_generations'],report['generations']):
        for stage in slot['stages']:
            base=slot['generation_id']+'.'+stage
            folder=directory/slot['generation_id']/stage
            for kind,suffix in [('countTokens','count'),('generateContent','generate')]:
                obs=call_map.get(base+'.'+suffix)
                if obs is None or obs.get('http_status')!=200:
                    incomplete.append(base+'.'+suffix);continue
                if obs['mode']!='LIVE' or obs['endpoint']!=endpoint(config,kind):fail('LIVE_ENDPOINT_BINDING')
                if not obs['dispatch_attempted'] or obs['transport_retry_index']!=0:fail('LIVE_DISPATCH_BINDING')
                body=(folder/(kind+'.response.bin')).read_bytes()
                req=(folder/(kind+'.request.json')).read_bytes()
                if sha(body)!=obs['response_sha256'] or sha(req)!=obs['request_sha256']:fail('LIVE_WIRE_HASH')
                if windows:
                    from .windows_bridge import envelope,decode_result
                    from .windows_helper import encode
                    receipt_raw=(folder/(kind+'.windows_receipt.json')).read_bytes()
                    if sha(receipt_raw)!=obs['windows_bridge_receipt_sha256']:fail('LIVE_WINDOWS_RECEIPT_HASH')
                    receipt=strict(receipt_raw)
                    reservation=read(folder/(kind+'.reservation.json'))
                    value=envelope(config,manifest_sha256,obs['request_id'],kind,req,reservation)
                    marker={k:receipt[k] for k in ('version','manifest_sha256','config_sha256','request_id','kind','request_sha256','reservation_sha256','host')}
                    marker['event']='DISPATCHING'
                    verified=decode_result(encode(marker)+b'\n'+encode(receipt),value)
                    if verified['response_sha256']!=sha(body) or verified['http_status']!=obs['http_status']:fail('LIVE_WINDOWS_RESPONSE_BINDING')
                    if receipt.get('wsl_bridge_elapsed_ns')!=obs['wsl_bridge_elapsed_ns'] or receipt['http_elapsed_ns']!=obs['windows_http_elapsed_ns']:fail('LIVE_WINDOWS_TIMING_BINDING')
                    if type(receipt.get('wsl_clock_scope')) is not str or not receipt['wsl_clock_scope'].startswith('LINUX_PID_'):fail('LIVE_LINUX_CLOCK_SCOPE')
                    # Native issuance record must be the exact one sealed with
                    # this response, not an unrelated successful credential log.
                    per_call=[r for r in receipt['auth'] if r.get('operation')=='SHORT_LIVED_CREDENTIAL_ISSUANCE']
                    if len(per_call)!=1 or per_call[0] not in issued:fail('LIVE_WINDOWS_AUTH_LINK')
                response=Response(200,body,{},obs['client_elapsed_ns'])
                if kind=='countTokens':
                    parsed=parse_count(response);count_total+=1
                    if parsed['estimated_input_tokens']>config['max_input_tokens']:fail('LIVE_INPUT_CAP')
                else:
                    parsed=parse_generation(response,config);generate_total+=1
                    version=parsed['reported_model_version'];response_id=parsed['provider_response_id']
                    if type(version) is not str or not (version==MODEL or version.startswith(MODEL+'-')):fail('LIVE_VERSION')
                    if type(response_id) is not str or not response_id or response_id.startswith('MOCK'):fail('LIVE_RESPONSE_ID')
                    versions.append(version)
                    if parsed['usage']['cost_usd_list_price_upper_estimate'] is None:fail('LIVE_USAGE_REQUIRED')
                    if parsed['status']!='PROVIDER_TEXT_READY':incomplete.append(base+'.provider_not_finished');continue
                    # The model may be wrong. Check transport fidelity independently
                    # from JSON/plan correctness; do not replace its output.
                    if (folder/'model_text.bin').exists() and (folder/'model_text.bin').read_bytes()!=parsed['text'].encode('utf8'):fail('LIVE_TEXT_CHANGED')
        execution=row.get('execution')
        if execution and execution.get('execution_started') is True and execution.get('seal_sha256'):
            from rcwg_spec.binding import ExpectedManifest
            from rcwg_exec.sealing import reopen_run
            root=directory/slot['generation_id']/'execution'
            expected=ExpectedManifest((root/'expected_manifest.json').read_bytes())
            reopen_run(root,manifest=expected,seal_sha256=execution['seal_sha256'])
            executed.append({'generation_id':slot['generation_id'],'terminal_status':execution.get('terminal_status'),
                             'verification_status':execution.get('verification',{}).get('status')})
    if len(set(versions))>1:fail('LIVE_VERSION_DRIFT')
    transport_ok=not incomplete and count_total==3 and generate_total==3
    end_to_end=transport_ok and any(r['terminal_status']=='COMPLETED' for r in executed)
    return {'status':'API001_LIVE_F1_ENGINEERING_ACCEPTED' if end_to_end else
                     'API001_LIVE_TRANSPORT_VERIFIED' if transport_ok else 'API001_LIVE_INCOMPLETE',
            'live_transport_verified':transport_ok,'live_f1_end_to_end_verified':end_to_end,
            'f1_execution_completed_independently':any(r['terminal_status']=='COMPLETED' for r in executed),
            'count_token_http_200':count_total,'generation_http_200':generate_total,
            'incomplete_stage_ids':incomplete,'execution_outcomes':executed,
            'model_answer_correctness_required_for_transport_acceptance':False,
            'invoice_cost_usd':None,'invoice_reason':'BILLING_EXPORT_NOT_SUPPLIED','formal_ready':False,
            'authenticity_basis':'TRUSTED_ADAPTER_PRIVATE_RECORDS_AND_OWNER_ATTESTATION_NOT_HASH_ALONE'}
