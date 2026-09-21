"""Executable static contracts for all 32 WorkIR operators / 56 implementations.

Handlers derive schemas from trusted public input types. They do not run kernels,
estimate measured resources, replace algorithms, or use output declarations as
type evidence. The compiler owns region joins and cross-node lifetime analysis.
"""
from __future__ import annotations

from dataclasses import replace
import re
from rcwg_spec.common import ContractError
from .typesystem import Type, parse_type, parse_schema, row_schema, with_rows, same_type, check_declared, unwrap_ref
from .predicates import analyze_predicate, base_type, literal_type

IDENT = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
SCALARS = {"Bool", "Int64", "Float64", "Utf8", "Date", "Timestamp"}
ROW_KINDS = {"Table", "Stream", "EvidenceTable"}
ARTIFACT_KINDS = ROW_KINDS | {"Graph", "GraphView", "DocumentIndex", "DocumentStream", "ChunkStream",
                           "NodeSet", "EdgeStream", "PathSet", "IDSet", "RankedIDSet", "Set", "Record", "Result"}
# Implementations are individually dispatched, then share only semantics which
# are identical. The worklist is an independent specification and is not trusted
# as executable validator code.
REGISTRY = {
    "scan": (("sequential", "index_range"), ("columns",), ("predicate",)),
    "filter": (("vectorized", "scalar"), ("predicate",), ()),
    "project": (("column_view", "copy"), ("columns",), ()),
    "join": (("hash", "sort_merge", "block_nested"), ("keys", "join_type", "build_side"), ()),
    "aggregate": (("hash_group", "sorted_group"), ("group_by", "aggregates"), ()),
    "deduplicate": (("hash", "sort_unique"), ("keys", "keep"), ()),
    "sort": (("in_memory", "external_merge"), ("keys",), ()),
    "top_k": (("full_sort", "streaming_heap"), ("k", "keys"), ()),
    "set_op": (("hash", "sorted_merge"), ("mode",), ()),
    "graph_neighbors": (("csr", "indexed_adjacency"), ("direction", "edge_types"), ()),
    "graph_reachability": (("bfs", "dfs"), ("max_hops", "direction"), ()),
    "graph_shortest_path": (("bfs", "dijkstra"), ("target", "weight_field"), ()),
    "graph_filter": (("edge_mask", "index_filter"), ("predicate",), ()),
    "graph_subgraph": (("induced", "edge_selected"), ("mode",), ()),
    "read_documents": (("batched", "per_document"), ("fields", "batch_size"), ("id_field",)),
    "text_retrieve": (("bm25", "dense_fixed"), ("query", "limit"), ()),
    "split_documents": (("section", "token_window"), ("size", "overlap"), ()),
    "gather_context": (("neighbors", "section_header"), ("window",), ()),
    "semantic_extract": (("fixed_e0",), ("field_schema", "context_budget"), ()),
    "evidence_merge": (("by_entity", "by_document"), ("keys", "conflict_policy"), ("priority_rule",)),
    "evidence_validate": (("span_check",), ("strict",), ()),
    "materialize": (("memory", "disk"), ("format",), ()),
    "stream_read": (("arrow_batches",), ("batch_size",), ()),
    "broadcast": (("shared_ref", "copy_each"), ("consumers",), ()),
    "release": (("explicit",), (), ()),
    "cache": (("memory", "disk"), ("key_fields",), ()),
    "map": (("bounded_map",), (), ()),
    "branch": (("predicate_branch",), ("predicate",), ()),
    "loop": (("bounded_loop",), ("condition", "max_iterations"), ()),
    "collect": (("bounded_collect",), ("limit",), ()),
    "emit": (("json_artifact",), ("output_contract",), ()),
    "stats": (("metadata", "sample"), ("fields",), ("sample_size",)),
}


def _fail(code, path, detail):
    raise ContractError(code, path, detail)


def _ptr(s):
    return str(s).replace("~", "~0").replace("/", "~1")


def _object(value, required, optional, path):
    if type(value) is not dict:
        _fail("PARAMETER_TYPE", path, "parameter object required")
    if set(value) - set(required) - set(optional):
        _fail("PARAMETER_UNKNOWN", path, "parameter is not in the closed contract")
    if set(required) - set(value):
        _fail("PARAMETER_REQUIRED", path, "required parameter is absent")


def _integer(value, path, minimum=0, maximum=None):
    if type(value) is not int:
        _fail("PARAMETER_TYPE", path, "integer parameter required; Bool is not an integer")
    if value < minimum or (maximum is not None and value > maximum):
        _fail("PARAMETER_RANGE", path, "integer parameter outside the allowed range")
    return value


def _enum(value, choices, path):
    if type(value) is not str:
        _fail("PARAMETER_TYPE", path, "string enum required")
    if value not in choices:
        _fail("PARAMETER_ENUM", path, "parameter is outside the declared enum")
    return value


def _string(value, path):
    if type(value) is not str or not value.strip():
        _fail("PARAMETER_TYPE", path, "nonempty string required")
    return value


def _strings(value, path, *, allow_empty=False, identifiers=False):
    if type(value) is not list or (not value and not allow_empty):
        _fail("PARAMETER_TYPE", path, "string array required")
    for i, v in enumerate(value):
        _string(v, path + "/" + str(i))
        if identifiers and not IDENT.fullmatch(v):
            _fail("PARAMETER_RANGE", path + "/" + str(i), "WorkIR identifier required")
    if len(value) != len(set(value)):
        _fail("PARAMETER_RANGE", path, "duplicate entries are not permitted")
    return value


def _fields(value, schema, path, *, allow_empty=False):
    names = _strings(value, path, allow_empty=allow_empty)
    for i, name in enumerate(names):
        if name not in schema:
            _fail("FIELD_NOT_FOUND", path + "/" + str(i), "field is not present in the inferred schema")
    return {name: schema[name] for name in names}


def _field(value, schema, path):
    _string(value, path)
    if value not in schema:
        _fail("FIELD_NOT_FOUND", path, "field is not present in the inferred schema")
    return schema[value]


def _kind(t, kinds, path):
    if t.kind not in kinds:
        _fail("TYPE_MISMATCH", path, "input representation does not satisfy the operator contract")
    return t


def _rows(t, path):
    _kind(t, ROW_KINDS, path)
    return row_schema(t, path)


def _stream(t, path):
    _kind(t, {"Stream"}, path)
    if t.item is None or t.item.kind != "Record":
        _fail("TYPE_MISMATCH", path, "Stream must carry a Record schema")
    return row_schema(t, path)


def _table(schema, original=None):
    return Type("Table", schema=tuple(schema.items()),
                domain=original.domain if original else None,
                revision=original.revision if original else None,
                metadata=dict(original.metadata) if original else {})


def _id_mappings(t):
    """Validated source mappings, distinct from a graph/table storage domain."""
    if "id_mappings" in t.metadata:
        return [dict(m) for m in t.metadata["id_mappings"]]
    if t.metadata.get("id_field") and t.metadata.get("id_domain"):
        return [{"field": t.metadata["id_field"], "domain": t.metadata["id_domain"],
                 "revision": t.metadata.get("id_revision", t.revision)}]
    return []


def _mapped(t, mappings):
    metadata = {k: v for k, v in t.metadata.items() if k not in {"id_field", "id_domain", "id_revision", "id_mappings"}}
    metadata["id_mappings"] = mappings
    # Keep legacy single-mapping fields for consumers which read typed metadata.
    if len(mappings) == 1:
        metadata.update(id_field=mappings[0]["field"], id_domain=mappings[0]["domain"], id_revision=mappings[0]["revision"])
    result = replace(t, metadata=metadata)
    if result.kind == "Stream" and result.item is not None:
        result = replace(result, item=replace(result.item, metadata=dict(metadata)))
    return result


def _as_stream(schema, original=None):
    record = Type("Record", schema=tuple(schema.items()),
                  domain=original.domain if original else None,
                  revision=original.revision if original else None,
                  metadata=dict(original.metadata) if original else {})
    return Type("Stream", item=record,
                domain=original.domain if original else None,
                revision=original.revision if original else None,
                metadata=dict(original.metadata) if original else {})


def _nullable(t):
    return t if t.kind == "Nullable" else Type("Nullable", item=t)


def _domain(a, b, path):
    if not a.domain or a.domain != b.domain or a.revision != b.revision:
        _fail("TYPE_MISMATCH", path, "data domain and revision must match explicitly")


def _sorting(keys, schema, path):
    if type(keys) is not list or not keys:
        _fail("PARAMETER_TYPE", path, "nonempty ordering-key array required")
    seen = set()
    for i, key in enumerate(keys):
        p = path + "/" + str(i)
        _object(key, {"field", "direction"}, {"nulls"}, p)
        t = _field(key["field"], schema, p + "/field")
        if key["field"] in seen:
            _fail("PARAMETER_RANGE", p, "ordering keys must be unique")
        seen.add(key["field"])
        _enum(key["direction"], {"asc", "desc"}, p + "/direction")
        if base_type(t).kind not in SCALARS:
            _fail("TYPE_MISMATCH", p, "ordering key must be scalar")
        if t.kind == "Nullable" and "nulls" not in key:
            _fail("PARAMETER_REQUIRED", p + "/nulls", "nullable ordering requires an explicit null placement")
        if "nulls" in key:
            _enum(key["nulls"], {"first", "last"}, p + "/nulls")


def _artifact(t, path):
    result = unwrap_ref(t)
    _kind(result, ARTIFACT_KINDS, path)
    return result


def _ref(t):
    return Type("ArtifactRef", item=t, domain=t.domain, revision=t.revision, metadata=dict(t.metadata))


def _public_index(t, path):
    indexes = [index for index in t.metadata.get("indexes", []) if index.get("kind") in {"range", "sorted"}]
    if not indexes:
        _fail("PRECONDITION_FAILED", path, "this implementation requires a declared public range/sorted index")
    return indexes


def validate_operator(node, inputs: dict[str, Type], *, task: dict, stage: str, path: str):
    """Validate one node and derive its outputs; controls return no outputs yet."""
    if type(node) is not dict:
        _fail("PORT_MISMATCH", path, "operator node object required")
    op, impl = node.get("operator"), node.get("implementation")
    if type(op) is not str or op not in REGISTRY:
        _fail("UNKNOWN_OPERATOR", path + "/operator", "operator is not registered")
    implementations, required, optional = REGISTRY[op]
    if type(impl) is not str or impl not in implementations:
        _fail("UNKNOWN_IMPLEMENTATION", path + "/implementation", "implementation is not registered for this operator")
    p = path + "/params"
    params = node.get("params")
    _object(params, required, optional, p)
    if type(inputs) is not dict or not all(isinstance(t, Type) for t in inputs.values()):
        _fail("TYPE_MISMATCH", path + "/inputs", "resolved input types are required")
    outputs, obligations, aliases = {}, [], {}

    def ports(names, *, captures=False):
        if not set(names) <= set(inputs) or (not captures and set(inputs) != set(names)):
            _fail("PORT_MISMATCH", path + "/inputs", "input port set does not match this implementation")
        if not all(type(k) is str and IDENT.fullmatch(k) for k in inputs):
            _fail("PORT_MISMATCH", path + "/inputs", "input port names must be identifiers")

    def inp(name):
        return path + "/inputs/" + name

    def obligation(code, **values):
        obligations.append({"code": code, "path": path, **values})

    def pred(value, schema, where, *, unknown_policy="reject_row"):
        t, guards = analyze_predicate(value, schema, where)
        obligations.extend(guards)
        if t.kind == "Nullable":
            obligation("PREDICATE_UNKNOWN_POLICY", policy=unknown_policy)

    if op == "scan":
        ports({"source"})
        ref = _kind(inputs["source"], {"DatasetRef"}, inp("source"))
        source = _kind(unwrap_ref(ref), {"Table"}, inp("source"))
        schema = row_schema(source, inp("source"))
        selected = _fields(params["columns"], schema, p + "/columns")
        if "predicate" in params:
            pred(params["predicate"], schema, p + "/predicate")
        if impl == "index_range":
            indexes = _public_index(source, inp("source"))
            # No index-selection parameter exists in WorkIR 1.0. Resolve the
            # first public declaration deterministically and record its identity.
            obligation("INDEX_AVAILABLE_AT_RUNTIME", index_id=indexes[0]["id"])
        outputs["rows"] = _as_stream(selected, source)
        outputs["rows"] = _mapped(outputs["rows"], [m for m in _id_mappings(source) if m["field"] in selected])
        aliases["rows"] = ["source"]
    elif op in {"filter", "project", "deduplicate", "sort", "top_k", "aggregate"}:
        ports({"rows"})
        source = inputs["rows"]
        schema = _rows(source, inp("rows"))
        if op == "filter":
            pred(params["predicate"], schema, p + "/predicate")
            outputs["rows"] = source
            # Filtering may retain row views. Conservatively preserve backing
            # storage until EXEC-001 supplies a materialization/copy event.
            aliases["rows"] = ["rows"]
            obligation("PREDICATE_THREE_VALUED_EVALUATION")
        elif op == "project":
            selected = _fields(params["columns"], schema, p + "/columns")
            outputs["rows"] = with_rows(source, selected)
            outputs["rows"] = _mapped(outputs["rows"], [m for m in _id_mappings(source) if m["field"] in selected])
            if impl == "column_view" or source.kind == "Stream":
                aliases["rows"] = ["rows"]
        elif op == "deduplicate":
            _fields(params["keys"], schema, p + "/keys")
            _enum(params["keep"], {"first", "last"}, p + "/keep")
            outputs["rows"] = source
            if source.kind == "Stream":
                aliases["rows"] = ["rows"]
            obligation("TRAVERSAL_ORDER_EVIDENCE", keep=params["keep"])
        elif op in {"sort", "top_k"}:
            _sorting(params["keys"], schema, p + "/keys")
            if op == "top_k":
                _integer(params["k"], p + "/k")
                obligation("EXACT_OUTPUT_AND_TIE_CHECK")
            else:
                obligation("MEMORY_OR_EXTERNAL_SORT_IO", implementation=impl)
            outputs["rows"] = replace(_table(schema, source),
                                      metadata={**source.metadata, "order": params["keys"]})
        else:
            grouped = _fields(params["group_by"], schema, p + "/group_by", allow_empty=True)
            specs = params["aggregates"]
            if type(specs) is not list or not specs:
                _fail("PARAMETER_TYPE", p + "/aggregates", "nonempty aggregate array required")
            result = dict(grouped)
            for i, spec in enumerate(specs):
                ap = p + "/aggregates/" + str(i)
                _object(spec, {"function", "field", "as"}, set(), ap)
                fn = _enum(spec["function"], {"count", "sum", "min", "max", "mean"}, ap + "/function")
                alias = _string(spec["as"], ap + "/as")
                if alias in result:
                    _fail("PARAMETER_RANGE", ap + "/as", "aggregate aliases and grouping fields must be unique")
                ft = None if spec["field"] is None else _field(spec["field"], schema, ap + "/field")
                if fn != "count" and ft is None:
                    _fail("PARAMETER_REQUIRED", ap + "/field", "this aggregation requires a field")
                if fn in {"sum", "mean"} and base_type(ft).kind not in {"Int64", "Float64"}:
                    _fail("TYPE_MISMATCH", ap + "/field", "numeric aggregate requires a numeric field")
                if ft is not None and base_type(ft).kind not in SCALARS:
                    _fail("TYPE_MISMATCH", ap + "/field", "aggregate field must be scalar")
                # A keyed group is created only for at least one input row. Its
                # nonnullable aggregate field therefore has at least one value.
                # Global aggregation can be empty; nullable fields can be all
                # null even in a nonempty keyed group. Neither becomes zero.
                if fn == "count":
                    result[alias] = Type("Int64")
                else:
                    aggregate_type = Type("Float64") if fn == "mean" else base_type(ft)
                    result[alias] = _nullable(aggregate_type) if not grouped or ft.kind == "Nullable" else aggregate_type
            outputs["rows"] = _table(result)
            outputs["rows"] = _mapped(outputs["rows"], [m for m in _id_mappings(source) if m["field"] in grouped])
            obligation("ORDER_AND_OVERFLOW_POLICY", implementation=impl)
    elif op == "join":
        ports({"left", "right"})
        left = _rows(inputs["left"], inp("left"))
        right = _rows(inputs["right"], inp("right"))
        keys = params["keys"]
        if type(keys) is not list or not keys:
            _fail("PARAMETER_TYPE", p + "/keys", "nonempty join-key array required")
        seen = set()
        for i, pair in enumerate(keys):
            kp = p + "/keys/" + str(i)
            _object(pair, {"left", "right"}, set(), kp)
            a = _field(pair["left"], left, kp + "/left")
            b = _field(pair["right"], right, kp + "/right")
            if not same_type(base_type(a), base_type(b)):
                _fail("TYPE_MISMATCH", kp, "join-key scalar types must agree without a cast")
            if base_type(a).kind not in SCALARS:
                _fail("TYPE_MISMATCH", kp, "join key must be scalar")
            pair_id = (pair["left"], pair["right"])
            if pair_id in seen:
                _fail("PARAMETER_RANGE", kp, "duplicate join key")
            seen.add(pair_id)
        mode = _enum(params["join_type"], {"inner", "left", "right", "full", "semi", "anti"}, p + "/join_type")
        _enum(params["build_side"], {"left", "right"}, p + "/build_side")
        if mode in {"semi", "anti"}:
            result = dict(left)
        else:
            result = {}
            overlap = set(left) & set(right)
            for side, fields in (("left", left), ("right", right)):
                for name, t in fields.items():
                    key = side + "." + name if name in overlap else name
                    if key in result:
                        _fail("TYPE_MISMATCH", path + "/outputs", "prefixed join field collides with an existing field")
                    result[key] = _nullable(t) if mode == "full" or (mode == "left" and side == "right") or (mode == "right" and side == "left") else t
        outputs["rows"] = _table(result)
        mappings = []
        for side, original in (("left", inputs["left"]), ("right", inputs["right"])):
            if mode in {"semi", "anti"} and side == "right":
                continue
            for mapping in _id_mappings(original):
                name = mapping["field"]
                renamed = side + "." + name if mode not in {"semi", "anti"} and name in set(left) & set(right) else name
                if renamed in result:
                    mappings.append({**mapping, "field": renamed})
        outputs["rows"] = _mapped(outputs["rows"], mappings)
        obligation("JOIN_MEMORY_AND_SPILL_GUARD", implementation=impl)
        if impl == "sort_merge":
            obligation("SORT_INPUT_OR_COSTED_LOCAL_SORT")
    elif op == "set_op":
        ports({"left", "right"})
        a, b = inputs["left"], inputs["right"]
        _kind(a, {"Set", "NodeSet", "IDSet"}, inp("left"))
        _kind(b, {a.kind}, inp("right"))
        if not same_type(a, b):
            _fail("TYPE_MISMATCH", inp("right"), "set element types, domains and revisions must match")
        _enum(params["mode"], {"union", "intersection", "difference"}, p + "/mode")
        outputs["items"] = a
    elif op.startswith("graph_"):
        names = {"graph"}
        if op in {"graph_neighbors", "graph_reachability", "graph_shortest_path"}:
            names.add("seeds")
        if op == "graph_subgraph":
            names.add("nodes" if impl == "induced" else "edges")
        ports(names)
        graph = _kind(inputs["graph"], {"Graph", "GraphView"}, inp("graph"))
        edge_schema = dict(graph.schema)
        if "seeds" in names:
            seeds = _kind(inputs["seeds"], {"NodeSet"}, inp("seeds"))
            _domain(graph, seeds, inp("seeds"))
            node_id_type = graph.metadata.get("node_id_type")
            if node_id_type is not None and seeds.item is not None and not same_type(seeds.item, node_id_type):
                _fail("TYPE_MISMATCH", inp("seeds"), "seed ID type differs from graph node ID type")
        if op in {"graph_neighbors", "graph_reachability"}:
            _enum(params["direction"], {"in", "out", "both"}, p + "/direction")
            if op == "graph_neighbors":
                edge_types = _strings(params["edge_types"], p + "/edge_types", allow_empty=True)
                known = graph.metadata.get("edge_types")
                if known is not None and not set(edge_types) <= set(known):
                    _fail("PARAMETER_ENUM", p + "/edge_types", "edge relation is not in the public graph domain")
                outputs["edges"] = Type("EdgeStream", schema=graph.schema, domain=graph.domain, revision=graph.revision, metadata=dict(graph.metadata))
                obligation("DIRECTION_TIME_AND_RELATION_FILTERS")
            else:
                _integer(params["max_hops"], p + "/max_hops")
                outputs["nodes"] = inputs["seeds"]
                obligation("FINITE_HOP_CORRECTNESS", includes_depth_zero=True)
        elif op == "graph_shortest_path":
            expected_id = graph.metadata.get("node_id_type")
            if expected_id is None:
                _fail("INPUT_METADATA_REQUIRED", inp("graph"), "public graph node ID type is required")
            targets = params["target"] if type(params["target"]) is list else [params["target"]]
            if not targets:
                _fail("PARAMETER_RANGE", p + "/target", "at least one target ID required")
            for i, target in enumerate(targets):
                if not same_type(literal_type(target, p + "/target/" + str(i)), expected_id):
                    _fail("TYPE_MISMATCH", p + "/target", "target ID type differs from graph node ID type")
            weight = params["weight_field"]
            if weight is not None:
                wt = _field(weight, edge_schema, p + "/weight_field")
                if wt.kind not in {"Int64", "Float64"}:
                    _fail("TYPE_MISMATCH", p + "/weight_field", "weight must be a non-null numeric field")
                flag = "weight_equal" if impl == "bfs" else "weight_nonnegative"
                declared = graph.metadata.get("weight_field")
                verified = graph.metadata.get(flag) if declared in {None, weight} else None
                if verified is False:
                    _fail("PRECONDITION_FAILED", p + "/weight_field", "public metadata contradicts the shortest-path algorithm prerequisite")
                if verified is not True:
                    obligation("WEIGHT_DOMAIN_CHECK", requirement=flag, weight_field=weight)
            outputs["paths"] = Type("PathSet", item=expected_id, domain=graph.domain, revision=graph.revision, metadata=dict(graph.metadata))
            obligation("UNREACHABLE_AND_TIE_RULE")
        elif op == "graph_filter":
            schema = dict(edge_schema)
            schema.update({"edge." + k: v for k, v in edge_schema.items()})
            schema.update({"node." + k: v for k, v in graph.metadata.get("node_schema", {}).items()})
            pred(params["predicate"], schema, p + "/predicate")
            outputs["graph"] = replace(graph, kind="GraphView")
            aliases["graph"] = ["graph"]
            if impl == "index_filter":
                obligation("GRAPH_INDEX_READINESS")
        else:
            _enum(params["mode"], {impl}, p + "/mode")
            port = "nodes" if impl == "induced" else "edges"
            selection = _kind(inputs[port], {"NodeSet" if impl == "induced" else "EdgeStream"}, inp(port))
            _domain(graph, selection, inp(port))
            if port == "edges" and not same_type(Type("Record", schema=selection.schema), Type("Record", schema=graph.schema)):
                _fail("TYPE_MISMATCH", inp(port), "edge selection schema must match the graph")
            if port == "nodes" and selection.item is not None and not same_type(selection.item, graph.metadata.get("node_id_type")):
                _fail("TYPE_MISMATCH", inp(port), "node selection ID type differs from graph")
            outputs["graph"] = replace(graph, kind="Graph")
    elif op == "read_documents":
        ports({"index", "ids"})
        index = _kind(inputs["index"], {"DocumentIndex"}, inp("index"))
        ids = _kind(inputs["ids"], {"IDSet", "RankedIDSet", "Table"}, inp("ids"))
        id_type = index.metadata.get("id_type")
        if ids.kind == "Table":
            if "id_field" not in params:
                _fail("PARAMETER_REQUIRED", p + "/id_field", "table ID selection requires an explicit public domain mapping")
            schema = row_schema(ids, inp("ids"))
            ft = _field(params["id_field"], schema, p + "/id_field")
            mappings = [m for m in _id_mappings(ids) if m["field"] == params["id_field"]]
            if len(schema) != 1 or len(mappings) != 1 or mappings[0]["domain"] != index.domain:
                _fail("TYPE_MISMATCH", inp("ids"), "single-column ID selection must explicitly map to the document domain")
            if mappings[0]["revision"] != index.revision:
                _fail("TYPE_MISMATCH", inp("ids"), "document revision differs from ID selection revision")
        else:
            _domain(index, ids, inp("ids"))
            ft = ids.item
            if "id_field" in params:
                declared = ids.metadata.get("id_field")
                if declared is None or params["id_field"] != declared:
                    _fail("FIELD_NOT_FOUND", p + "/id_field", "selection has no matching public ID field")
        if id_type is not None and (ft is None or not same_type(ft, id_type)):
            _fail("TYPE_MISMATCH", inp("ids"), "document ID scalar types differ")
        selected = _fields(params["fields"], dict(index.schema), p + "/fields")
        _integer(params["batch_size"], p + "/batch_size", 1)
        outputs["documents"] = Type("DocumentStream", schema=tuple(selected.items()), domain=index.domain, revision=index.revision, metadata=dict(index.metadata))
        obligation("DOCUMENT_REVISION_MATCH", implementation=impl)
    elif op == "text_retrieve":
        ports({"index"})
        index = _kind(inputs["index"], {"DocumentIndex"}, inp("index"))
        _string(params["query"], p + "/query")
        _integer(params["limit"], p + "/limit")
        if impl == "dense_fixed":
            dense = index.metadata.get("dense_model_id") or any(i.get("kind") == "dense_fixed" and i.get("model_id") for i in index.metadata.get("indexes", []))
            if not dense:
                obligation("DENSE_INDEX_SERVICE_BINDING_REQUIRED", readiness="NOT_BOUND")
        outputs["ids"] = Type("RankedIDSet", item=index.metadata.get("id_type"), domain=index.domain, revision=index.revision, metadata=dict(index.metadata))
        obligation("APPROXIMATE_CANDIDATE_COVERAGE")
    elif op in {"split_documents", "gather_context", "semantic_extract"}:
        port = "chunks" if op == "gather_context" else "documents"
        ports({port})
        allowed = {"ChunkStream"} if op == "gather_context" else ({"DocumentStream", "ChunkStream"} if op == "semantic_extract" else {"DocumentStream"})
        source = _kind(inputs[port], allowed, inp(port))
        if op == "split_documents":
            size = _integer(params["size"], p + "/size", 1)
            _integer(params["overlap"], p + "/overlap", 0, size - 1)
            outputs["chunks"] = replace(source, kind="ChunkStream")
            obligation("TOKENIZER_SPAN_COORDINATE_CHECK", implementation=impl)
            if impl == "token_window":
                obligation("FROZEN_TOKENIZER_REQUIRED")
        elif op == "gather_context":
            _integer(params["window"], p + "/window")
            outputs["chunks"] = source
            obligation("PUBLIC_CONTEXT_READ_LEDGER", implementation=impl)
            obligation("PROVENANCE_RETENTION")
        else:
            if type(params["field_schema"]) is not dict or not params["field_schema"]:
                _fail("PARAMETER_TYPE", p + "/field_schema", "nonempty typed field map required")
            schema = parse_schema(params["field_schema"], p + "/field_schema")
            _integer(params["context_budget"], p + "/context_budget", 1)
            outputs["evidence"] = Type("EvidenceTable", schema=tuple(schema.items()), domain=source.domain, revision=source.revision, metadata=dict(source.metadata))
            for code in ("SERVICE_BINDING_REQUIRED", "CONTEXT_LIMIT", "PROVENANCE_RETENTION"):
                obligation(code)
    elif op in {"evidence_merge", "evidence_validate"}:
        ports({"evidence", "index"} if op == "evidence_validate" else {"evidence"})
        evidence = _kind(inputs["evidence"], {"EvidenceTable"}, inp("evidence"))
        schema = row_schema(evidence, inp("evidence"))
        if op == "evidence_merge":
            _fields(params["keys"], schema, p + "/keys")
            policy = _enum(params["conflict_policy"], {"keep_all", "reject", "declared_priority"}, p + "/conflict_policy")
            if policy == "declared_priority":
                if "priority_rule" not in params:
                    _fail("PARAMETER_REQUIRED", p + "/priority_rule", "declared priority requires a public ordering rule")
                _sorting(params["priority_rule"], schema, p + "/priority_rule")
            elif "priority_rule" in params:
                _fail("PARAMETER_UNKNOWN", p + "/priority_rule", "priority rule applies only to declared_priority")
            obligation("CONFLICT_AND_PROVENANCE_CHECK", policy=policy)
        else:
            index = _kind(inputs["index"], {"DocumentIndex"}, inp("index"))
            _domain(evidence, index, inp("index"))
            if type(params["strict"]) is not bool:
                _fail("PARAMETER_TYPE", p + "/strict", "strict must be Boolean")
            obligation("PUBLIC_SPAN_VALIDATION", strict=params["strict"])
        outputs["evidence"] = evidence
    elif op in {"materialize", "collect"}:
        ports({"rows"})
        source = inputs["rows"]
        schema = _stream(source, inp("rows"))
        if op == "materialize":
            _enum(params["format"], {"arrow_ipc", "parquet"}, p + "/format")
            if node.get("storage") != impl:
                _fail("PARAMETER_ENUM", path + "/storage", "storage must agree with materialization implementation")
            obligation("BUFFER_AND_SPILL_LEDGER", storage=impl)
        else:
            _integer(params["limit"], p + "/limit")
            obligation("LIMIT_WITHOUT_SILENT_TRUNCATION")
        outputs["rows"] = _table(schema, source)
    elif op in {"stream_read", "broadcast", "release", "cache"}:
        ports({"artifact"})
        source = _artifact(inputs["artifact"], inp("artifact"))
        if op == "stream_read":
            _integer(params["batch_size"], p + "/batch_size", 1)
            if source.kind in ROW_KINDS | {"Record"}:
                schema = row_schema(source, inp("artifact"))
            elif source.kind in {"Graph", "GraphView", "EdgeStream", "DocumentStream", "ChunkStream"}:
                schema = dict(source.schema)
            else:
                _fail("TYPE_MISMATCH", inp("artifact"), "artifact has no row-readable schema")
            outputs["rows"] = _as_stream(schema, source)
            aliases["rows"] = ["artifact"]
            obligation("METERED_READ")
        elif op == "broadcast":
            consumers = _strings(params["consumers"], p + "/consumers", identifiers=True)
            outputs = {consumer: _ref(source) for consumer in consumers}
            if impl == "shared_ref":
                aliases = {consumer: ["artifact"] for consumer in consumers}
            obligation("ALIAS_OR_COPY_LEDGER", implementation=impl)
        elif op == "release":
            outputs["done"] = Type("ControlToken")
            obligation("LAST_CONSUMER_GUARD")
        else:
            # Keys name public fields; arbitrary user text never becomes a file
            # path or a cross-run cache key. Content/schema identity is mandatory.
            schema = row_schema(source, inp("artifact")) if source.kind in ROW_KINDS | {"Record"} else dict(source.schema)
            _fields(params["key_fields"], schema, p + "/key_fields")
            outputs["artifact"] = _ref(source)
            if impl == "memory":
                aliases["artifact"] = ["artifact"]
            obligation("SAME_RUN_ONLY", include_content_identity=True, include_schema_identity=True)
            if impl == "disk" and node.get("storage") not in {None, "disk"}:
                _fail("PARAMETER_ENUM", path + "/storage", "disk cache requires disk storage when specified")
    elif op in {"map", "branch", "loop"}:
        port = {"map": "rows", "branch": "condition", "loop": "state"}[op]
        ports({port}, captures=op != "map")
        if op == "map":
            _stream(inputs[port], inp(port))
            for code in ("GLOBAL_INSTANCE_COUNTER", "GLOBAL_CPU_SLOTS", "BOUNDED_BACKPRESSURE"):
                obligation(code)
        elif op == "branch":
            if base_type(inputs[port]).kind != "Bool":
                _fail("TYPE_MISMATCH", inp(port), "branch condition must be Bool or Nullable Bool")
            pred(params["predicate"], dict(inputs), p + "/predicate", unknown_policy="runtime_error")
            obligation("BRANCH_SELECTION_EVENT")
        else:
            state = inputs[port]
            schema = {**dict(state.schema), "state": state} if state.kind == "Record" else {"state": state}
            schema.update({k: v for k, v in inputs.items() if k != "state"})
            pred(params["condition"], schema, p + "/condition", unknown_policy="runtime_error")
            _integer(params["max_iterations"], p + "/max_iterations", 1, 16)
            obligation("GLOBAL_INSTANCE_COUNTER")
            obligation("CONTINUATION_AT_LIMIT", false_at_cap="COMPLETED", true_at_cap="LOOP_LIMIT_REACHED",
                       condition_semantics="continue_while_true", check_initial=True, check_after_last_update=True)
        return {"outputs": {}, "runtime_obligations": obligations, "alias_inputs": {}, "dispatch_id": op + ":" + impl}
    elif op == "emit":
        ports({"rows"})
        source = unwrap_ref(inputs["rows"])
        contract = task.get("output_contract", {})
        representations = {"ordered_records": ROW_KINDS, "records": ROW_KINDS, "evidence": {"EvidenceTable"},
                           "paths": {"PathSet"}, "node_set": {"NodeSet"}, "id_set": {"IDSet", "RankedIDSet"},
                           "scalar": SCALARS | {"Nullable"}, "record": {"Record"}, "set": {"Set"}}
        tag = contract.get("type")
        if tag not in representations:
            _fail("TYPE_MISMATCH", p + "/output_contract", "public output representation is not supported")
        _kind(source, representations[tag], inp("rows"))
        if tag == "scalar" and not same_type(source, parse_type(contract.get("value_type"), p + "/output_contract/value_type")):
            _fail("TYPE_MISMATCH", inp("rows"), "scalar output type differs from the public contract")
        if "item_type" in contract and not same_type(source.item, parse_type(contract["item_type"], p + "/output_contract/item_type")):
            _fail("TYPE_MISMATCH", inp("rows"), "output element type differs from the public contract")
        selected = _string(params["output_contract"], p + "/output_contract")
        names = {contract.get("id"), contract.get("contract_id")}
        if contract.get("type") == "ordered_records" and contract.get("mode") == "exact":
            names.add("exact_ordered_topk_v1")
        if selected not in names:
            _fail("PARAMETER_ENUM", p + "/output_contract", "output contract does not name the public task contract")
        fields = contract.get("fields", [])
        schema = row_schema(source, inp("rows")) if source.kind in ROW_KINDS | {"Record"} else dict(source.schema)
        if fields:
            _fields(fields, schema, p + "/output_contract")
        expected = contract.get("schema")
        if expected:
            parsed = parse_schema(expected, p + "/output_contract/schema")
            for name, expected_type in parsed.items():
                if name not in schema:
                    _fail("FIELD_NOT_FOUND", inp("rows"), "emitted schema is missing a public output field")
                if not same_type(schema[name], expected_type):
                    _fail("TYPE_MISMATCH", inp("rows"), "emitted field type differs from the public output contract")
        expected_domain = contract.get("domain")
        if expected_domain is not None and source.domain != expected_domain:
            _fail("TYPE_MISMATCH", inp("rows"), "output domain does not match the public contract")
        if "revision" in contract and source.revision != contract["revision"]:
            _fail("TYPE_MISMATCH", inp("rows"), "output revision does not match the public contract")
        outputs["result"] = Type("Result", item=source, schema=tuple(schema.items()), domain=source.domain, revision=source.revision)
        obligation("RESULT_ARTIFACT_HASH")
        obligation("INDEPENDENT_VERIFICATION")
    elif op == "stats":
        ports({"source"})
        ref = _kind(inputs["source"], {"DatasetRef"}, inp("source"))
        source = unwrap_ref(ref)
        schema = row_schema(source, inp("source")) if source.kind in ROW_KINDS else dict(source.schema)
        _fields(params["fields"], schema, p + "/fields")
        visibility = task.get("information_level", task.get("information_condition", task.get("condition", {}).get("information_level") if type(task.get("condition")) is dict else None))
        if stage != "generation_probe" or visibility != "I2":
            _fail("STAGE_FORBIDDEN", path, "stats is permitted only for generation_probe with public I2")
        if impl == "sample":
            if "sample_size" not in params:
                _fail("PARAMETER_REQUIRED", p + "/sample_size", "sample implementation requires a positive sample size")
            _integer(params["sample_size"], p + "/sample_size", 1)
        elif "sample_size" in params:
            _fail("PARAMETER_UNKNOWN", p + "/sample_size", "metadata implementation does not sample")
        outputs["stats"] = Type("Stats")
        obligation("PROBE_GENERATION_BUDGET")
    else:  # An added registry name without a handler is a facility bug.
        raise RuntimeError("operator registry lacks an executable handler")

    declared = node.get("outputs")
    if type(declared) is not dict or set(declared) != set(outputs):
        _fail("PORT_MISMATCH", path + "/outputs", "output ports do not match the selected implementation")
    for port, actual in outputs.items():
        check_declared(actual, declared[port], path + "/outputs/" + _ptr(port))
    return {"outputs": outputs, "runtime_obligations": obligations,
            "alias_inputs": aliases, "dispatch_id": op + ":" + impl}


def _bind_contract(operator, implementation):
    def contract(node, inputs, *, task, stage, path):
        if node.get("operator") != operator or node.get("implementation") != implementation:
            _fail("UNKNOWN_IMPLEMENTATION", path, "bound contract dispatch does not match the node")
        return validate_operator(node, inputs, task=task, stage=stage, path=path)
    contract.__name__ = operator + "__" + implementation
    contract.__qualname__ = contract.__name__
    return contract


DISPATCH = {op + ":" + impl: _bind_contract(op, impl)
            for op, (implementations, _, _) in REGISTRY.items() for impl in implementations}
