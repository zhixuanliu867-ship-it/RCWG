"""Pinned native entry points for the separately accounted external tracks.

No module is imported at preparation time. Live execution requires a finite,
job-bound admission callback before imports or model construction, and a fresh
durable claim. Dependency/source/receipt failures never fall back to a replay.
"""
import ast,dataclasses,importlib,importlib.util,importlib.metadata,json,math,os,re,subprocess,sys,time
from copy import deepcopy
from pathlib import Path
from rcwg_full.evidence import ROOT,read,write,digest,sha,exclusive_directory,safe_path


def registry():return json.loads(read(ROOT/'specs/full001/external_native_v1.json'))


def _record(value):
    if dataclasses.is_dataclass(value):return _record(dataclasses.asdict(value))
    if hasattr(value,'to_dict') and hasattr(value,'columns'):return _record(value.to_dict(orient='records'))
    if isinstance(value,dict):return {str(k):_record(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_record(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):return {'nonfinite':str(value)}
    if hasattr(value,'item'):return _record(value.item())
    if value is None or type(value) in {str,int,float,bool}:return value
    raise ValueError('UPSTREAM_RESULT_NOT_SERIALIZABLE')


def _graph(value):
    if set(value)!={'nodes','edges'} or not isinstance(value['nodes'],list) or not all(type(n) is str for n in value['nodes']):raise ValueError('WORFEVAL_NATIVE_GRAPH')
    for edge in value['edges']:
        if len(edge)!=2 or any(type(i) is not int or i not in range(len(value['nodes'])) for i in edge):raise ValueError('WORFEVAL_NATIVE_EDGE')


def validate_job(track,job):
    if track not in registry()['tracks']:raise ValueError('NATIVE_EXTERNAL_TRACK')
    if not isinstance(job,dict):raise ValueError('NATIVE_EXTERNAL_JOB')
    if track=='TPS-Bench':
        if set(job)!={'logs','tools'} or not job['logs'] or not isinstance(job['tools'],dict):raise ValueError('TPS_NATIVE_LOGS_TOOLS')
        if any(type(v) is not str for v in job['logs']):raise ValueError('TPS_NATIVE_LOG_TEXT')
    elif track=='WorFEval':
        if set(job)!={'metric','predicted','expected','embedding_model'} or job['metric'] not in {'graph','nodes','plan'}:raise ValueError('WORFEVAL_NATIVE_JOB')
        if job['metric']!='plan':_graph(job['predicted']);_graph(job['expected'])
        elif any(not isinstance(job[k],list) or not all(type(x) is str for x in job[k]) for k in ['predicted','expected']):raise ValueError('WORFEVAL_NATIVE_PLAN')
        if not isinstance(job['embedding_model'],dict) or not job['embedding_model'].get('local_path') or not job['embedding_model'].get('files'):raise ValueError('LOCAL_EMBEDDING_WEIGHTS_REQUIRED')
    elif track=='SemBench':
        if set(job)!={'scenario','scale_factor','query_ids','model','policy','ranking','concurrent_llm_worker'} or job['scenario']!='movie':raise ValueError('SEMBENCH_NATIVE_MOVIE_PROFILE')
        if not job['query_ids'] or any(type(i) is not int or i not in range(1,11) for i in job['query_ids']):raise ValueError('SEMBENCH_QUERY_IDS')
        # This concrete upstream class does not expose its parent's policy and
        # ranking parameters. Preserve its actual defaults instead of claiming
        # that silently ignored knobs select a different original protocol.
        if job['policy']!='approximate' or job['ranking']!='map':raise ValueError('SEMBENCH_PINNED_CLASS_DEFAULTS')
    elif track=='LOTUS':
        if set(job)!={'rows','model','steps'} or not isinstance(job['rows'],list) or not job['steps']:raise ValueError('LOTUS_NATIVE_JOB')
        allowed={'sem_filter':{'user_instruction'},'sem_extract':{'input_cols','output_cols','extract_quotes'},
                 'sem_topk':{'user_instruction','K','method'},'sem_join':{'join_instruction','right_rows'}}
        for step in job['steps']:
            if set(step)!={'operator','arguments'} or step['operator'] not in allowed or set(step['arguments'])-allowed[step['operator']]:raise ValueError('LOTUS_NATIVE_OPERATOR_ARGUMENTS')
    elif track=='DocETL':
        if set(job)!={'config','max_threads'} or not {'datasets','operations','pipeline'}<=job['config'].keys():raise ValueError('DOCETL_NATIVE_CONFIG')
        # Callable parsers/custom code require a separately extended adapter.
        if job['config'].get('parsing_tools'):raise ValueError('DOCETL_CUSTOM_CODE_OUTSIDE_PROFILE')
    digest(job) # reject non-JSON/non-finite configuration before any import
    return deepcopy(job)


def verify_checkout(track,checkout,environment):
    entry=registry()['tracks'][track];root=safe_path(checkout).resolve()
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL).decode().strip()
    if git('rev-parse','HEAD')!=entry['revision']:raise ValueError('UPSTREAM_COMMIT_MISMATCH')
    if git('diff','--name-only','HEAD'):raise ValueError('UPSTREAM_TRACKED_SOURCE_DIRTY')
    if git('ls-files','--others','--exclude-standard','*.py'):raise ValueError('UPSTREAM_UNTRACKED_PYTHON')
    for name,expected in entry['files'].items():
        if sha(read(root/name))!=expected:raise ValueError('UPSTREAM_ENTRY_SOURCE_CHANGED')
    if environment.get('python')!=sys.version.split()[0] or not environment.get('packages'):raise ValueError('UPSTREAM_ENVIRONMENT_UNBOUND')
    installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in importlib.metadata.distributions()}
    wanted={k.lower().replace('_','-'):v for k,v in environment['packages'].items()}
    if installed!=wanted:raise ValueError('UPSTREAM_DEPENDENCY_LOCK_MISMATCH')
    if environment.get('source_revision')!=entry['revision']:raise ValueError('UPSTREAM_ENVIRONMENT_SOURCE')
    return {'checkout':str(root),'revision':entry['revision'],'tree':git('rev-parse','HEAD^{tree}'),
        'entry_files':entry['files'],'environment_sha256':digest(environment)}


def _load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module


def tps_definitions(path):
    """Use original functions, excluding upstream's import-time paid batch run."""
    tree=ast.parse(read(path));names={'extract_query_and_tools','clean_response','generate_with_gemini_eval'}
    body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SYSTEM_PROMPT' for t in n.targets)]
    if {n.name for n in body if isinstance(n,ast.FunctionDef)}!=names:raise ValueError('TPS_UPSTREAM_ENTRYPOINT_CHANGED')
    import glob
    namespace={'json':json,'re':re,'glob':glob,'os':os}
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


def dispatch(track,job,backend,output):
    """Call actual upstream APIs; injected test backends are marked separately."""
    job=validate_job(track,job);output=Path(output)
    if track=='TPS-Bench':
        logs=output/'logs';logs.mkdir();tools_file=output/'available_tools.json';write(tools_file,job['tools'])
        for i,log in enumerate(job['logs']):write(logs/f'{i:04d}.log',log.encode('utf8'))
        target=output/'upstream-scores.jsonl'
        backend['generate_with_gemini_eval'](backend['SYSTEM_PROMPT'],str(logs),str(tools_file),str(target))
        return [json.loads(line) for line in read(target).splitlines()]
    if track=='WorFEval':
        fn=getattr(backend['module'],{'graph':'t_eval_graph','nodes':'t_eval_nodes','plan':'t_eval_plan'}[job['metric']])
        return fn(job['predicted'],job['expected'],backend['embedding_model'])
    if track=='SemBench':
        runner=backend['runner_class'](use_case='movie',scale_factor=job['scale_factor'],model_name=job['model'],
            concurrent_llm_worker=job['concurrent_llm_worker'])
        # Initialization includes the upstream warmup. It is inside admission.
        return runner.execute_queries(job['query_ids'])
    if track=='LOTUS':
        pandas=backend['pandas'];lotus=backend['lotus'];frame=pandas.DataFrame(job['rows'])
        with lotus.settings.context(lm=backend['lm'],enable_cache=False):
            for step in job['steps']:
                args=deepcopy(step['arguments'])
                if step['operator']=='sem_join':args['other']=pandas.DataFrame(args.pop('right_rows'))
                frame=getattr(frame,step['operator'])(**args)
        return frame
    runner=backend['runner_class'](job['config'],max_threads=job['max_threads'])
    runner.load();data,cost=runner.run()
    return {'rows':data,'upstream_cost':cost,'upstream_token_usage':dict(runner.total_token_usage)}


def _native_backend(track,job,root):
    # Only the local, weight-bound evaluator has a default constructor. Paid
    # systems require native-shaped bridges over the existing admitted service
    # transport, never a new default SDK client or a new credential route.
    if track!='WorFEval':raise PermissionError('EXISTING_SERVICE_NATIVE_BRIDGE_REQUIRED')
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'src'))
    if track=='WorFEval':
        from sentence_transformers import SentenceTransformer
        model=job['embedding_model'];model_root=safe_path(model['local_path'])
        for name,expected in model['files'].items():
            p=Path(name)
            if p.is_absolute() or '..' in p.parts or sha(read(model_root/p))!=expected:raise ValueError('EMBEDDING_WEIGHTS_CHANGED')
        return {'module':_load(root/'evaluator/graph_evaluator.py','full001_upstream_worfeval'),
            'embedding_model':SentenceTransformer(str(model_root),local_files_only=True)}


def run_admitted(track,job,*,checkout,environment,receipt,admit,output,service_backend_factory=None):
    job=validate_job(track,job);identity=verify_checkout(track,checkout,environment)
    inputs=receipt.get('input_files')
    if not isinstance(inputs,dict):raise ValueError('EXTERNAL_INPUT_FILES_REQUIRED')
    def verify_inputs():
        for name,expected in inputs.items():
            if sha(read(name))!=expected:raise ValueError('EXTERNAL_INPUT_FILE_CHANGED')
    verify_inputs()
    if track=='DocETL':
        for source in job['config']['datasets'].values():
            if source.get('type')!='file' or str(Path(source['path']).absolute()) not in inputs:raise ValueError('DOCETL_INPUT_NOT_BOUND')
    request={'schema_version':'FULL001_EXTERNAL_NATIVE_RUN_1','track':track,'job_sha256':digest(job),'input_files':inputs,
        'runtime':identity,'receipt_sha256':digest(receipt),'ledger_role':'EXTERNAL_REPLICATION',
        'primary_ledger_eligible':False,'original_reproduction_claim':False}
    if not callable(admit) or admit(deepcopy(request)) is not True:raise PermissionError('EXTERNAL_NATIVE_FINITE_ADMISSION_REQUIRED')
    if track!='WorFEval' and (not callable(service_backend_factory) or not re.fullmatch('[0-9a-f]{64}',receipt.get('service_binding_sha256',''))):
        raise PermissionError('EXISTING_SERVICE_NATIVE_BRIDGE_REQUIRED')
    # A caller must allocate output from the receipt's unique attempt ID. The
    # persisted claim is deliberately never removed, including on uncertainty.
    if not receipt.get('attempt_id') or receipt.get('job_sha256')!=request['job_sha256'] or receipt.get('runtime_sha256')!=digest(identity):raise ValueError('EXTERNAL_RECEIPT_BINDING')
    scope=safe_path(receipt['claim_directory']);scope.mkdir(parents=True,exist_ok=True)
    attempt=receipt['attempt_id']
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',attempt):raise ValueError('EXTERNAL_ATTEMPT_ID')
    claim=scope/(attempt+'.json');write(claim,request)
    out=exclusive_directory(output);write(out/'request.json',request);start=time.monotonic_ns()
    result={'status':'UNCERTAIN','ledger_role':'EXTERNAL_REPLICATION','primary_ledger_eligible':False,'formal_ready':False,
        'original_reproduction_claim':False,'request_sha256':digest(request),'paid_call_count':None,'remote_cpu_seconds':None,'remote_gpu_seconds':None,'remote_vram_bytes':None}
    try:
        if verify_checkout(track,checkout,environment)!=identity:raise ValueError('UPSTREAM_CHANGED_AFTER_ADMISSION')
        backend=service_backend_factory(track,deepcopy(job),identity,out) if service_backend_factory else _native_backend(track,job,Path(identity['checkout']))
        raw=dispatch(track,job,backend,out)
        result.update(status='COMPLETED',native_output_sha256=write(out/'native-result.json',_record(raw)))
    except Exception as exc:result.update(status='INFRA_OR_UPSTREAM_FAILURE',error_type=type(exc).__name__,error=str(exc))
    finally:
        result['observed_elapsed_ns']=time.monotonic_ns()-start
        try:
            result['upstream_identity_after']=verify_checkout(track,checkout,environment);verify_inputs()
        except Exception as exc:result.update(status='SOURCE_OR_ENVIRONMENT_CHANGED',identity_error=str(exc))
        write(out/'observation.json',result)
    return result
