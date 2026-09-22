"""Frozen-file factory for the managed campaign runner; no implicit installs."""
from pathlib import Path
import json
from rcwg_full.evidence import digest,read,sha,source_hashes
from .sealing import check_expected,relative_file
from .admission import admit
from .runner import CampaignRunner,PreparedNativeExecutor


def run_from_manifest(manifest_path,receipts,*,resume=False):
    admission=admit(manifest_path,receipts)
    if admission['blockers']:return admission
    manifest=check_expected(manifest_path);root=Path(manifest_path).parent
    freeze=json.loads(read(root/'freeze.json'))
    entry=freeze.get('runner',{})
    raw=read(relative_file(root,entry['file']))
    if sha(raw)!=entry['sha256']:raise ValueError('RUNNER_CONFIG_HASH')
    config=json.loads(raw)
    if config.get('revision')!='FULL001_RUNNER_1' or config.get('source_hash')!=digest(source_hashes()):raise ValueError('RUNNER_SOURCE_BINDING')
    def artifact(key):
        item=config[key];raw=read(relative_file(root,item['file']))
        if sha(raw)!=item['sha256']:raise ValueError('RUNNER_ARTIFACT_HASH:'+key)
        return json.loads(raw)
    registry=artifact('services');catalog=artifact('tasks');legacy=artifact('existing_api_config')
    host_scope=artifact('host_scope');paid_scope=artifact('paid_scope')
    if any(digest(value)!=freeze['authorization_scopes'][key] for key,value in [('host',host_scope),('paid_services',paid_scope)]):raise ValueError('RUNNER_AUTHORIZATION_SCOPE')
    from rcwg_full.services.bindings import registry as validate_registry
    services=validate_registry(registry,live=True)
    if paid_scope.get('service_snapshot_hash')!=services['snapshot_hash'] or paid_scope.get('expected_manifest_hash')!=manifest['manifest_hash']:
        raise ValueError('PAID_SERVICE_SCOPE_BINDING')
    build=relative_file(root,config['native_build'])
    if sha(read(build/'BUILD.json'))!=config['native_build_sha256']:raise ValueError('NATIVE_BUILD_BINDING')
    for item in catalog.values():
        for key in ['task_path','data_manifest','private_verifier']:
            item[key]=str(relative_file(root,item[key]))
        if item.get('reference_plan'):item['reference_plan']=str(relative_file(root,item['reference_plan']))
    # Only approved, existing API001 auth routes are constructed. No credentials
    # are copied to the worker, run configuration or request evidence.
    from rcwg_api.budget import Budget
    from rcwg_api.vertex import VertexTransport,GcloudToken
    from rcwg_api.windows_bridge import WindowsUserTransport
    from rcwg_full.services.transport import ExistingVertexTransport,ExistingWindowsTransport,ExistingCloudTransport
    from rcwg_full.services.client import ServiceClient,RequestIndex,FixedSemanticService,generate
    execution=root/'execution';execution_parent=root/'service-evidence';execution_parent.mkdir(exist_ok=True,mode=0o700)
    budget=Budget(execution_parent/'budget.sqlite3',digest(paid_scope),paid_scope['budget'])
    clients={};indexes=[]
    try:
        for slot,binding in services['bindings'].items():
            if binding['count_method']!='PROVIDER_COUNT':raise PermissionError('FROZEN_LOCAL_TOKENIZER_ADAPTER_REQUIRED')
            if legacy.get('adapter')=='CLOUD001_EXISTING':
                from rcwg_cloud.transport import MetadataIdentity,CloudHTTP
                identity=MetadataIdentity();identity.verify('live');transport=ExistingCloudTransport(binding,CloudHTTP(identity))
            elif legacy.get('auth_mode')=='GCLOUD_USER':
                existing=WindowsUserTransport(legacy,digest(paid_scope));transport=ExistingWindowsTransport(binding,existing)
            else:
                existing=VertexTransport(legacy,GcloudToken(legacy));transport=ExistingVertexTransport(binding,existing)
            index=RequestIndex(execution_parent/slot);indexes.append(index)
            clients[slot]=ServiceClient(binding,transport,budget,index,mode='LIVE',scope_hash=digest(paid_scope),receipt=receipts['paid_services'])
        templates=artifact('executor_templates')
        executors={slot:FixedSemanticService(clients[slot],templates[slot]) for slot in ['E0','E1']}
        def generation(slot,attempt_id,dependencies,directory):
            item=catalog[slot['task_id']];raw=read(item['task_path'])
            if sha(raw)!=item['task_sha256']:raise ValueError('TASK_SOURCE_CHANGED')
            task=json.loads(raw)
            from .transforms import public_guidance
            result=generate(task,slot,clients[slot['generator']],attempt_id,
                            guidance=public_guidance(task) if slot.get('generation_stage')=='GUIDED_PHYSICAL' else None)
            if result['status'] in {'MODEL_FAILURE','PLAN_INVALID'}:result['failure_class']='CONFIRMED_PLAN'
            return result
        executor=PreparedNativeExecutor(catalog,build,'FORMAL',host_scope=host_scope,host_receipt=receipts['host'],admission=admission,semantic_services=executors)
        slots=[]
        for item in [manifest['primary'],*manifest['diagnostics'].values()]:
            slots.extend(json.loads(line) for line in read(relative_file(root,item['file'])).splitlines())
        from .diagnostics import controls
        external={}
        for definition in controls():
            task_id=f"{definition['template_id']}-b{definition['base_id']}-{definition['condition']}"
            item=catalog[task_id];raw=read(item['reference_plan'])
            if sha(raw)!=item['reference_plan_sha256']:raise ValueError('CONTROL_REFERENCE_IDENTITY')
            plan=json.loads(raw);external[definition['control_plan_id']]={'status':'COMPLETED','plan':plan,'plan_hash':digest(plan),
                'model_snapshot_hash':digest(clients['E0'].binding),'origin':'PREDECLARED_REFERENCE_CONTROL'}
        runner=CampaignRunner(execution,slots,manifest_hash=manifest['manifest_hash'],spec_hash=manifest['spec_hash'],
                              mode='FORMAL',generate=generation,execute=executor,resume=resume,external_dependencies=external)
        try:return runner.run()
        finally:runner.close()
    finally:
        for index in indexes:index.close()
