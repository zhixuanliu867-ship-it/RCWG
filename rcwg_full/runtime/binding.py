"""COMPAT1 validator adapter; original RunnerContext, manifest and seals are reused.

The binding body is inherited verbatim; only public type validation is versioned.
"""
from rcwg_spec.binding import RunnerContext,_id,_obj,_complete,_fail,_hash
from rcwg_spec.common import canonical,digest
from rcwg_spec.identity import comparison_identity
from rcwg_full.compiler.public_task import validate_public_task


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


