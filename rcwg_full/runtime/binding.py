"""COMPAT1 validator adapter; original RunnerContext, manifest and seals are reused.

The binding body is inherited verbatim; only public type validation is versioned.
"""
from rcwg_spec.binding import RunnerContext,_id,_obj,_complete,_fail,_hash
from rcwg_spec.common import canonical,digest
from rcwg_spec.identity import comparison_identity
from rcwg_full.compiler.public_task import validate_public_task


def freeze_execution(context,task,plan,compiler_source,run_id,*,frozen_binding=None,
                     record_role='MODEL',repeat_role='PRIMARY_REPEAT',generation_id=None,repeat_id='r1'):
    """Keep E2's C0 plan bytes while binding the actual target task context.

    The inherited manifest and evidence validators are unchanged. Only the
    explicitly checked E2 task-id relation extends their pre-execution builder.
    """
    import hashlib
    from rcwg_spec.binding import freeze_expected,ExpectedManifest,_context_snapshot,_manifest,_json_contract
    from rcwg_spec.identity import execution_identity
    specification={'record_id':run_id,'record_role':record_role,'plan':plan,'compiler_source':compiler_source,
        'generation_id':generation_id or run_id,'repeat_id':repeat_id,'repeat_role':repeat_role}
    if frozen_binding is None:return freeze_expected(context,[specification])
    from rcwg_full.compiler import FullCompiler
    checked=validate_public_task(task);snapshot=_context_snapshot(context)
    if snapshot['task_input_hash']!=checked['task_input_hash']:raise ValueError('FROZEN_CONTEXT_TASK_MISMATCH')
    FullCompiler().compile(task,plan,frozen_binding=frozen_binding)
    _json_contract(plan)
    if record_role not in {'MODEL','REFERENCE'}:raise ValueError('EXPECTED_RECORD_ROLE')
    if type(compiler_source) is not bytes or not compiler_source:raise ValueError('COMPILER_SOURCE_REQUIRED')
    for key in ['record_id','generation_id','repeat_id']:_id(specification[key],'/expected/'+key)
    identity=execution_identity(snapshot['identity']['context'],plan_hash=digest(plan),
        compiler_hash=hashlib.sha256(compiler_source).hexdigest(),input_hash=snapshot['task_input_hash'],
        generation_id=specification['generation_id'],repeat_id=repeat_id,repeat_role=repeat_role)
    result=ExpectedManifest(canonical({'schema_version':'SPEC001B_EXPECTED_0.1','context':snapshot,
        'expected_records':[{'record_id':run_id,'record_role':record_role,**identity}],'formal_ready':False}))
    _manifest(result)
    return result


def build_context(task: dict, *, condition_id: str, data_manifest: list[dict],
                  runtime: dict, cache_policy: dict, verifier: dict, metric_spec: dict,
                  measurement_profile: dict, operator_registry: dict,
                  source_manifest: dict) -> RunnerContext:
    """Bind supplied runner metadata to actual validated public source identities.

    data_manifest entries are exactly id/revision/content_sha256/schema_hash.
    Their IDs, revisions, content and schema must match the public data registry.
    Each component is a nonempty JSON object with a nonempty revision. Its full
    canonical content is hashed; a caller cannot substitute a claimed hash.
    measurement_profile additionally declares event_source_id and clock_id.
    """
    checked = validate_public_task(task)
    _id(condition_id, "/condition_id")
    if type(data_manifest) is not list or not data_manifest:
        _fail("DATA_MANIFEST", "/data_manifest", "nonempty authoritative data manifest required")
    public_sources = {item["id"]: item for item in checked["source_manifest"]}
    found = set()
    for entry in data_manifest:
        _obj(entry, {"id", "revision", "content_sha256", "schema_hash"}, path="/data_manifest")
        _complete(entry, "/data_manifest")
        ident = entry["id"]
        if type(ident) is not str or ident in found or ident not in public_sources:
            _fail("DATA_MANIFEST", "/data_manifest", "manifest source identities differ")
        found.add(ident)
        public = public_sources[ident]
        _hash(entry["content_sha256"], "/data_manifest/content_sha256")
        _hash(entry["schema_hash"], "/data_manifest/schema_hash")
        if public.get("revision") is None or public.get("data_sha256") is None:
            _fail("CONTEXT_NOT_BOUND", "/data_manifest", "public source revision and content evidence required")
        if (entry["revision"] != public["revision"] or entry["content_sha256"] != public["data_sha256"]
                or entry["schema_hash"] != public["schema_hash"]):
            _fail("DATA_MANIFEST_MISMATCH", "/data_manifest", "actual and public source identities differ")
    if found != set(public_sources):
        _fail("DATA_MANIFEST", "/data_manifest", "expected public sources missing")
    components = {"runtime": runtime, "cache_policy": cache_policy, "verifier": verifier,
                  "metric_spec": metric_spec, "measurement_profile": measurement_profile,
                  "operator_registry": operator_registry, "source_manifest": source_manifest}
    for name, value in components.items():
        if type(value) is not dict or not value or "revision" not in value:
            _fail("CONTEXT_NOT_BOUND", "/" + name, "versioned authoritative metadata required")
        _complete(value, "/" + name)
        if type(value["revision"]) is not str:
            _fail("CONTEXT_NOT_BOUND", "/" + name, "metadata revision must be text")
    for field in ("event_source_id", "clock_id"):
        _id(measurement_profile.get(field), "/measurement_profile/" + field)
    if source_manifest.get("public_sources") != checked["source_manifest"]:
        _fail("SOURCE_MANIFEST_MISMATCH", "/source_manifest", "source registry must bind all public source evidence")
    # Canonical source list order is registry identity, not caller enumeration.
    manifest = sorted(data_manifest, key=lambda entry: entry["id"])
    context = {"case_id": checked["normalized_task"]["task_id"], "condition_id": condition_id,
               "data_manifest_hash": digest(manifest),
               "resource_profile_hash": digest(checked["normalized_task"]["resources"]),
               **{name + "_hash": digest(value) for name, value in components.items()}}
    snapshot = {"schema_version": "SPEC001B_BOUND_CONTEXT_0.1", "identity": comparison_identity(context),
                "task_input_hash": checked["task_input_hash"],
                "normalized_input_hash": checked["normalized_input_hash"],
                "authoritative_metadata": {"data_manifest": manifest,
                                           "resource_profile": checked["normalized_task"]["resources"],
                                           **components},
                "formal_ready": False, "runtime_enforcement": "NOT_VERIFIED"}
    return RunnerContext(canonical(snapshot))

