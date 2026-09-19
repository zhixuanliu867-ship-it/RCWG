"""Closed public TaskInput profiles for all six families.

Only explicitly supplied public metadata is used; no file/network resolver exists
here. Legacy untagged tables remain valid but do not acquire fabricated revisions
or freeze readiness. Unknown/private fields are rejected without quoting them.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
import re

from .common import ContractError, digest
from .typesystem import Type, SCALARS, parse_type, parse_schema, same_type, type_json, pointer

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PRIVATE = frozenset({"gold", "oracle", "private", "private_data", "hidden", "hidden_verifier",
                      "reference", "reference_plan", "answer_key", "verifier_feedback",
                      "private_path", "private_bundle", "split", "stratum", "stratification"})


def _error(code, path, message):
    raise ContractError(code, path, message)


def _closed(obj, required, optional, path):
    if type(obj) is not dict:
        _error("OBJECT_REQUIRED", path, "object required")
    if not required <= obj.keys():
        _error("MISSING_FIELD", path, "required public field is absent")
    if obj.keys() - required - optional:
        _error("PUBLIC_FIELD_VIOLATION", path, "field outside the public profile")


def _text(value, path):
    if type(value) is not str or not value.strip():
        _error("STRING_REQUIRED", path, "nonempty public identifier/text required")
    return value


def _num(value, path, *, positive=False, integer=True):
    if type(value) not in ((int,) if integer else (int, float)) or (type(value) is float and not math.isfinite(value)):
        _error("INVALID_NUMBER", path, "finite numeric value required; booleans are distinct")
    if value < 0 or (positive and value == 0):
        _error("INVALID_NUMBER", path, "numeric value is outside its public range")
    return value


def _guard(obj, path="", depth=0, active=None, counter=None):
    if active is None:
        active, counter = set(), [0]
    counter[0] += 1
    if depth > 48 or counter[0] > 50000:
        _error("INPUT_LIMIT", path, "public input exceeds nesting or size limit")
    if type(obj) in {dict, list}:
        if id(obj) in active:
            _error("INPUT_INVALID", path, "cyclic object is not JSON")
        active.add(id(obj))
        if type(obj) is dict:
            for key, value in obj.items():
                if type(key) is not str:
                    _error("INPUT_INVALID", path, "JSON object keys must be strings")
                _unicode(key, path)
                if key.lower() in _PRIVATE:
                    _error("PUBLIC_FIELD_VIOLATION", path, "private metadata is not public generation input")
                # Do not include unvalidated key names in error paths.
                _guard(value, path, depth + 1, active, counter)
        else:
            for value in obj:
                _guard(value, path, depth + 1, active, counter)
        active.remove(id(obj))
    elif obj is not None and type(obj) not in {bool, int, float, str}:
        _error("INPUT_INVALID", path, "public input must contain only JSON values")
    elif type(obj) is float and not math.isfinite(obj):
        _error("INVALID_NUMBER", path, "finite JSON number required")
    elif type(obj) is int and not -(2**63) <= obj < 2**63:
        _error("INVALID_NUMBER", path, "public integer exceeds the Int64 metadata range")
    elif type(obj) is str and len(obj) > 65536:
        _error("INPUT_LIMIT", path, "public string exceeds size limit")
    elif type(obj) is str:
        _unicode(obj, path)


def _unicode(value, path):
    try:
        value.encode("utf8", errors="strict")
    except UnicodeEncodeError:
        _error("INPUT_INVALID", path, "public strings must be valid Unicode")


def _names(value, path, *, empty=False):
    if type(value) is not list or (not value and not empty):
        _error("INVALID_FIELDS", path, "field names must be a unique string array")
    for name in value:
        _text(name, path)
    if len(set(value)) != len(value):
        _error("INVALID_FIELDS", path, "duplicate field identifier")
    return value


def _idtype(value, path):
    result = parse_type(value, path)
    if result.kind not in {"Int64", "Utf8"}:
        _error("TYPE_MISMATCH", path, "IDs must be Int64 or Utf8")
    return result


def _stats(value, path, required):
    allowed = {"row_count", "node_count", "edge_count", "document_count", "item_count",
               "estimated_row_bytes", "estimated_document_bytes", "eligible_fraction_estimate",
               "estimate_source", "source", "revision"}
    _closed(value, required, allowed - required, path)
    for key, item in value.items():
        if key in {"estimate_source", "source", "revision"}:
            _text(item, pointer(path, key))
        elif key == "eligible_fraction_estimate":
            _num(item, pointer(path, key), integer=False)
            if item > 1 or "estimate_source" not in value:
                _error("INVALID_FRACTION", path, "fraction needs a public source and must be within zero and one")
        else:
            _num(item, pointer(path, key))


def _indexes(value, schema, revision, path):
    if type(value) is not list:
        _error("INDEX_INVALID", path, "indexes must be an array")
    seen = set()
    for i, index in enumerate(value):
        p = pointer(path, i)
        _closed(index, {"id", "kind", "fields", "revision", "source"}, {"model_id"}, p)
        for key in ("id", "kind", "revision", "source"):
            _text(index[key], pointer(p, key))
        if index["id"] in seen:
            _error("INDEX_INVALID", p, "index identifiers must be unique")
        seen.add(index["id"])
        if index["kind"] not in {"range", "hash", "sorted", "csr", "adjacency", "bm25", "dense_fixed"}:
            _error("INDEX_INVALID", p, "unknown public index kind")
        if index["revision"] != revision:
            _error("REVISION_MISMATCH", p, "index revision differs from its dataset")
        for name in _names(index["fields"], pointer(p, "fields")):
            if name not in schema:
                _error("FIELD_NOT_FOUND", pointer(p, "fields"), "index field is not declared in public schema")
        if index["kind"] == "dense_fixed":
            _text(index.get("model_id"), pointer(p, "model_id"))
        elif "model_id" in index:
            _error("INDEX_INVALID", p, "model identity is only valid for a dense index")


def _dataset(data, p, blockers):
    if type(data) is not dict:
        _error("OBJECT_REQUIRED", p, "dataset descriptor must be an object")
    legacy = "kind" not in data
    kind = data.get("kind", "table")
    if type(kind) is not str:
        _error("DATASET_KIND", pointer(p, "kind"), "dataset kind must be a known tag")
    fields = {
        "table": ({"schema", "stats"}, {"indexes", "id_domain", "id_field"}),
        "graph": ({"edge_schema", "node_schema", "node_id_type", "domain", "directed", "stats"},
                  {"indexes", "weight_field", "weight_nonnegative", "weight_equal", "node_id_field", "source_field", "target_field"}),
        "document_index": ({"schema", "id_type", "domain", "stats", "indexes"}, {"dense_model_id", "id_field"}),
        "node_set": ({"id_type", "domain", "stats"}, set()),
        "edge_stream": ({"schema", "domain", "stats"}, set()),
        "id_selection": ({"id_type", "domain", "ranked", "stats"}, set()),
        "scalar": ({"type"}, {"value"}),
        "record": ({"schema"}, set()),
        "set": ({"item_type", "stats"}, {"domain"}),
    }
    if kind not in fields:
        _error("DATASET_KIND", pointer(p, "kind"), "unknown public dataset tag")
    required, optional = fields[kind]
    base_required = {"id"} if legacy else {"id", "kind", "revision", "schema_source"}
    _closed(data, base_required | required,
            optional | {"data_sha256"} | ({"revision", "schema_source"} if legacy else set()), p)
    ident = _text(data["id"], pointer(p, "id"))
    if not re.fullmatch(r"dataset:[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}", ident):
        _error("INVALID_DATASET_ID", pointer(p, "id"), "dataset: identifier required")
    revision = data.get("revision")
    for name in ("revision", "schema_source"):
        if name in data:
            _text(data[name], pointer(p, name))
            if data[name] in {"UNRESOLVED", "UNKNOWN"}:
                _error("SOURCE_UNRESOLVED", pointer(p, name), "explicit source identity must be resolved")
        else:
            blockers.append({"code": "LEGACY_SOURCE_METADATA_MISSING", "path": pointer(p, name)})
    if "data_sha256" in data:
        if type(data["data_sha256"]) is not str or not _HASH.fullmatch(data["data_sha256"]):
            _error("SOURCE_HASH", pointer(p, "data_sha256"), "lowercase SHA256 required")
    else:
        blockers.append({"code": "DATA_CONTENT_HASH_NOT_PROVIDED", "path": p})
    domain = data.get("domain")
    if "domain" in data:
        _text(domain, pointer(p, "domain"))
    metadata = {"source_id": ident, "indexes": deepcopy(data.get("indexes", [])),
                "stats": deepcopy(data.get("stats", {}))}
    schema = {}
    if "schema" in data:
        schema = parse_schema(data["schema"], pointer(p, "schema"))
    if kind == "table":
        _stats(data["stats"], pointer(p, "stats"), {"row_count"})
        if ("id_domain" in data) != ("id_field" in data):
            _error("ID_MAPPING_REQUIRED", p, "document ID mapping needs domain and field together")
        if "id_domain" in data:
            _text(data["id_domain"], pointer(p, "id_domain"))
            field = _text(data["id_field"], pointer(p, "id_field"))
            if field not in schema or schema[field].kind not in {"Int64", "Utf8"}:
                _error("ID_MAPPING_REQUIRED", p, "document ID mapping must select a declared ID column")
            metadata.update(id_domain=data["id_domain"], id_field=field)
        t = Type("Table", tuple(schema.items()), revision=revision, metadata=metadata)
        result = Type("DatasetRef", item=t, revision=revision, metadata=metadata)
    elif kind == "graph":
        schema = parse_schema(data["edge_schema"], pointer(p, "edge_schema"))
        nodes = parse_schema(data["node_schema"], pointer(p, "node_schema"))
        node_id = _idtype(data["node_id_type"], pointer(p, "node_id_type"))
        if type(data["directed"]) is not bool:
            _error("TYPE_MISMATCH", pointer(p, "directed"), "directed must be boolean")
        _stats(data["stats"], pointer(p, "stats"), {"node_count", "edge_count"})
        metadata.update(node_schema=nodes, node_id_type=node_id, directed=data["directed"])
        for key, default, fields in (("node_id_field", "id", nodes), ("source_field", "source", schema), ("target_field", "target", schema)):
            field_name = _text(data.get(key, default), pointer(p, key))
            if field_name not in fields or not same_type(fields[field_name], node_id):
                _error("TYPE_MISMATCH", pointer(p, key), "graph endpoint and node identifiers must match the declared ID type")
            metadata[key] = field_name
        for key in ("weight_nonnegative", "weight_equal"):
            if key in data:
                if type(data[key]) is not bool:
                    _error("TYPE_MISMATCH", pointer(p, key), "weight fact must be boolean")
                metadata[key] = data[key]
        if "weight_field" in data:
            weight = _text(data["weight_field"], pointer(p, "weight_field"))
            if weight not in schema or schema[weight].kind not in {"Int64", "Float64"}:
                _error("FIELD_NOT_FOUND", pointer(p, "weight_field"), "weight field must be a declared nonnullable numeric edge field")
            metadata["weight_field"] = weight
        result = Type("Graph", tuple(schema.items()), domain=domain, revision=revision, metadata=metadata)
    elif kind == "document_index":
        _stats(data["stats"], pointer(p, "stats"), {"document_count"})
        metadata["id_type"] = _idtype(data["id_type"], pointer(p, "id_type"))
        id_field = _text(data.get("id_field", "id"), pointer(p, "id_field"))
        if id_field not in schema or not same_type(schema[id_field], metadata["id_type"]):
            _error("TYPE_MISMATCH", pointer(p, "id_field"), "document ID column must match the declared ID type")
        metadata["id_field"] = id_field
        if "dense_model_id" in data:
            metadata["dense_model_id"] = _text(data["dense_model_id"], pointer(p, "dense_model_id"))
        result = Type("DocumentIndex", tuple(schema.items()), domain=domain, revision=revision, metadata=metadata)
    elif kind in {"node_set", "id_selection"}:
        _stats(data["stats"], pointer(p, "stats"), {"item_count"})
        item = _idtype(data["id_type"], pointer(p, "id_type"))
        metadata["id_type"] = item
        if kind == "id_selection" and type(data["ranked"]) is not bool:
            _error("TYPE_MISMATCH", pointer(p, "ranked"), "ranked must be boolean")
        result = Type("NodeSet" if kind == "node_set" else "RankedIDSet" if data["ranked"] else "IDSet",
                      item=item, domain=domain, revision=revision, metadata=metadata)
    elif kind == "edge_stream":
        _stats(data["stats"], pointer(p, "stats"), {"edge_count"})
        result = Type("EdgeStream", tuple(schema.items()), domain=domain, revision=revision, metadata=metadata)
    elif kind == "record":
        result = Type("Record", tuple(schema.items()), revision=revision, metadata=metadata)
    elif kind == "scalar":
        result = parse_type(data["type"], pointer(p, "type"))
        inner = result.item if result.kind == "Nullable" else result
        if inner.kind not in SCALARS:
            _error("TYPE_MISMATCH", pointer(p, "type"), "scalar input must have a scalar type")
        if "value" in data:
            _scalar_value(data["value"], result, pointer(p, "value"))
        result = replace(result, metadata=metadata)
    else:
        _stats(data["stats"], pointer(p, "stats"), {"item_count"})
        item = parse_type(data["item_type"], pointer(p, "item_type"))
        result = Type("Set", item=item, domain=domain, revision=revision, metadata=metadata)
    if "indexes" in data:
        _indexes(data["indexes"], schema, revision, pointer(p, "indexes"))
    normalized = deepcopy(data)
    normalized["kind"] = kind
    source = {"id": ident, "kind": kind, "revision": revision,
              "schema_source": data.get("schema_source"), "data_sha256": data.get("data_sha256"),
              "schema_hash": digest(type_json(result))}
    return normalized, result, source


def _scalar_value(value, t, path):
    if t.kind == "Nullable":
        if value is None:
            return
        return _scalar_value(value, t.item, path)
    valid = {"Bool": type(value) is bool, "Int64": type(value) is int and -(2**63) <= value < 2**63,
             "Float64": type(value) is float and math.isfinite(value), "Utf8": type(value) is str,
             "Date": type(value) is str, "Timestamp": type(value) is str}.get(t.kind, False)
    if not valid:
        _error("TYPE_MISMATCH", path, "public scalar value does not match its declared type")
    if t.kind in {"Date", "Timestamp"}:
        from datetime import date, datetime
        try:
            if t.kind == "Date":
                date.fromisoformat(value)
            else:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    raise ValueError()
        except ValueError:
            _error("TYPE_MISMATCH", path, "ISO date or timezone-qualified timestamp required")


def _output(contract, inputs):
    p = "/output_contract"
    if type(contract) is not dict:
        _error("OBJECT_REQUIRED", p, "public output contract must be an object")
    tag = contract.get("type")
    if type(tag) is not str or tag not in {"ordered_records", "records", "evidence", "paths", "node_set", "id_set", "scalar", "record", "set"}:
        _error("OUTPUT_PROFILE", p, "unknown public output contract tag")
    common = {"id", "schema", "fields"} if tag in {"ordered_records", "records", "evidence", "record"} else {"id"}
    specific = {"ordered_records": {"k", "tie_breaker"}, "records": set(), "evidence": {"domain", "revision"},
                "paths": {"domain", "revision"}, "node_set": {"domain", "revision", "item_type"},
                "id_set": {"domain", "revision", "item_type"}, "scalar": {"value_type"},
                "record": set(), "set": {"item_type"}}[tag]
    mandatory = {"type", "mode"} | (specific if tag in {"ordered_records", "scalar", "node_set", "id_set", "set", "paths", "evidence"} else set())
    if tag != "ordered_records":
        mandatory.add("id")
    _closed(contract, mandatory, common | specific, p)
    if type(contract["mode"]) is not str or contract["mode"] not in {"exact", "evidence_supported"}:
        _error("OUTPUT_PROFILE", pointer(p, "mode"), "unknown output verification mode")
    if "id" in contract:
        _text(contract["id"], pointer(p, "id"))
    for key in ("domain", "revision"):
        if key in contract:
            _text(contract[key], pointer(p, key))
    result = deepcopy(contract)
    if tag == "scalar":
        t = parse_type(contract["value_type"], pointer(p, "value_type"))
        if t.kind not in SCALARS and not (t.kind == "Nullable" and t.item.kind in SCALARS):
            _error("TYPE_MISMATCH", p, "scalar output needs a scalar value type")
    elif tag in {"node_set", "id_set", "set"}:
        parser = _idtype if tag in {"node_set", "id_set"} else parse_type
        parser(contract["item_type"], pointer(p, "item_type"))
    elif tag != "paths" or "fields" in contract or "schema" in contract:
        if "schema" in contract and type(contract["schema"]) is not dict:
            _error("TYPE_MISMATCH", pointer(p, "schema"), "output schema must be a field map")
        fields = _names(contract.get("fields", list(contract.get("schema", {}))), pointer(p, "fields"))
        if "schema" in contract:
            schema = parse_schema(contract["schema"], pointer(p, "schema"))
            if set(schema) != set(fields):
                _error("TYPE_MISMATCH", p, "output field list and schema must match exactly")
        else:
            schema = {}
            for name in fields:
                candidates = []
                for t in inputs.values():
                    t = t.item if t.kind == "DatasetRef" else t
                    if name in dict(t.schema):
                        candidates.append(dict(t.schema)[name])
                if not candidates or any(not same_type(candidates[0], x) for x in candidates[1:]):
                    _error("OUTPUT_SCHEMA_REQUIRED", p, "output schema cannot be uniquely inferred from public data")
                schema[name] = candidates[0]
        result["fields"] = fields
        result["schema"] = {name: type_json(schema[name]) for name in fields}
    if tag == "ordered_records":
        _num(contract["k"], pointer(p, "k"))
        _text(contract["tie_breaker"], pointer(p, "tie_breaker"))
        if contract["tie_breaker"] not in result["fields"]:
            _error("TIE_BREAKER_MISSING", p, "tie breaker must be an emitted field")
    return result


def validate_public_task(task) -> dict:
    _guard(task)
    _closed(task, {"task_id", "instruction", "datasets", "resources", "output_contract", "tool_catalog_id"},
            {"notes", "information_level"}, "")
    for name in ("task_id", "instruction", "tool_catalog_id", "notes"):
        if name in task:
            _text(task[name], "/" + name)
    if "information_level" in task and (type(task["information_level"]) is not str or task["information_level"] not in {"I0", "I1", "I2"}):
        _error("INFORMATION_LEVEL", "/information_level", "unknown information level")
    if type(task["datasets"]) is not list or not task["datasets"]:
        _error("DATASETS_REQUIRED", "/datasets", "nonempty public dataset array required")
    normalized, input_types, manifest, blockers = deepcopy(task), {}, [], []
    normalized["datasets"] = []
    for i, data in enumerate(task["datasets"]):
        item, t, source = _dataset(data, "/datasets/" + str(i), blockers)
        if item["id"] in input_types:
            _error("INVALID_DATASET_ID", "/datasets/" + str(i), "duplicate dataset identifier")
        input_types[item["id"]] = t
        normalized["datasets"].append(item)
        manifest.append(source)
    r = task["resources"]
    _closed(r, {"cpu_slots", "worker_memory_limit_bytes", "wall_timeout_s"}, set(), "/resources")
    for name in ("cpu_slots", "worker_memory_limit_bytes", "wall_timeout_s"):
        _num(r[name], "/resources/" + name, positive=True, integer=name != "wall_timeout_s")
    if r["cpu_slots"] > 8:
        _error("RESOURCE_LIMIT", "/resources/cpu_slots", "RCWG 1.0 permits at most eight CPU slots")
    normalized["output_contract"] = _output(task["output_contract"], input_types)
    return {"status": "PUBLIC_TASK_VALIDATED", "profile": "RCWG_PUBLIC_TASK_SPEC001B",
            "normalized_task": normalized, "input_types": input_types, "task_input_hash": digest(task),
            "normalized_input_hash": digest(normalized), "source_manifest": manifest,
            "readiness": {"public_metadata": "COMPLETE" if not blockers else "INCOMPLETE",
                          "blockers": blockers, "formal_ready": False}, "formal_ready": False}
