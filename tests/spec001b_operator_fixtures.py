"""Explicit BOOT_ONLY contract examples, never experimental benchmark cases."""
from copy import deepcopy
from dataclasses import replace
from rcwg_spec.typesystem import Type

I, F, S, B = Type("Int64"), Type("Float64"), Type("Utf8"), Type("Bool")
SCHEMA = (("id", I), ("score", F), ("eligible", B))
RECORD = Type("Record", schema=SCHEMA)
TABLE = Type("Table", schema=SCHEMA, metadata={"indexes": [{"id": "by_id", "kind": "range", "fields": ["id"]}]})
STREAM = Type("Stream", item=RECORD)
GRAPH = Type("Graph", schema=(("source", I), ("target", I), ("weight", F), ("relation", S)),
             domain="graph:demo", revision="g1", metadata={"node_id_type": I, "node_schema": {"name": S},
             "directed": True, "edge_types": ["cites"], "weight_field": "weight", "weight_nonnegative": True, "weight_equal": True})
NODES = Type("NodeSet", item=I, domain=GRAPH.domain, revision=GRAPH.revision)
EDGES = Type("EdgeStream", schema=GRAPH.schema, domain=GRAPH.domain, revision=GRAPH.revision)
INDEX = Type("DocumentIndex", schema=(("id", S), ("title", S), ("body", S)), domain="docs:demo", revision="d1",
             metadata={"id_type": S, "id_field": "id", "dense_model_id": "fixed-e0", "indexes": [{"kind": "bm25", "id": "text"}]})
IDS = Type("IDSet", item=S, domain=INDEX.domain, revision=INDEX.revision, metadata={"id_field": "id"})
DOCS = Type("DocumentStream", schema=INDEX.schema, domain=INDEX.domain, revision=INDEX.revision, metadata=dict(INDEX.metadata))
CHUNKS = replace(DOCS, kind="ChunkStream")
EVIDENCE = Type("EvidenceTable", schema=(("entity", S), ("value", I), ("priority", I)), domain=INDEX.domain, revision=INDEX.revision)
SET = Type("Set", item=I)
PRED = {"op": "eq", "left": {"field": "eligible"}, "right": {"literal": True}}
ORDER = [{"field": "score", "direction": "desc"}, {"field": "id", "direction": "asc"}]
TASK = {"information_level": "I2", "output_contract": {"id": "public_result", "type": "ordered_records", "mode": "exact", "fields": ["id", "score"], "schema": {"id": "int64", "score": "float64"}}}

# Explicit independent expectation: port -> (kind, exact field names or None).
# Invalid cases exercise the operator's own contract, not a registry-name enum.
FIXTURES = {
    "scan": ({"source": Type("DatasetRef", item=TABLE)}, {"columns": ["id", "score"]}, {"rows": ("Stream", ["id", "score"])}, {"columns": ["ghost"]}, "FIELD_NOT_FOUND"),
    "filter": ({"rows": STREAM}, {"predicate": PRED}, {"rows": ("Stream", ["id", "score", "eligible"])}, {"predicate": {"field": "score"}}, "TYPE_MISMATCH"),
    "project": ({"rows": TABLE}, {"columns": ["id"]}, {"rows": ("Table", ["id"])}, {"columns": ["ghost"]}, "FIELD_NOT_FOUND"),
    "join": ({"left": TABLE, "right": TABLE}, {"keys": [{"left": "id", "right": "id"}], "join_type": "inner", "build_side": "left"}, {"rows": ("Table", ["left.id", "left.score", "left.eligible", "right.id", "right.score", "right.eligible"])}, {"keys": [{"left": "id", "right": "score"}]}, "TYPE_MISMATCH"),
    "aggregate": ({"rows": TABLE}, {"group_by": ["eligible"], "aggregates": [{"function": "sum", "field": "score", "as": "total"}]}, {"rows": ("Table", ["eligible", "total"])}, {"aggregates": [{"function": "sum", "field": "eligible", "as": "total"}]}, "TYPE_MISMATCH"),
    "deduplicate": ({"rows": STREAM}, {"keys": ["id"], "keep": "first"}, {"rows": ("Stream", ["id", "score", "eligible"])}, {"keep": "arbitrary"}, "PARAMETER_ENUM"),
    "sort": ({"rows": STREAM}, {"keys": ORDER}, {"rows": ("Table", ["id", "score", "eligible"])}, {"keys": [{"field": "ghost", "direction": "asc"}]}, "FIELD_NOT_FOUND"),
    "top_k": ({"rows": STREAM}, {"keys": ORDER, "k": 2}, {"rows": ("Table", ["id", "score", "eligible"])}, {"k": -1}, "PARAMETER_RANGE"),
    "set_op": ({"left": SET, "right": SET}, {"mode": "union"}, {"items": ("Set", None)}, {"mode": "append"}, "PARAMETER_ENUM"),
    "graph_neighbors": ({"graph": GRAPH, "seeds": NODES}, {"direction": "out", "edge_types": ["cites"]}, {"edges": ("EdgeStream", ["source", "target", "weight", "relation"])}, {"edge_types": ["unknown_relation"]}, "PARAMETER_ENUM"),
    "graph_reachability": ({"graph": GRAPH, "seeds": NODES}, {"direction": "both", "max_hops": 2}, {"nodes": ("NodeSet", None)}, {"max_hops": True}, "PARAMETER_TYPE"),
    "graph_shortest_path": ({"graph": GRAPH, "seeds": NODES}, {"target": [2, 3], "weight_field": "weight"}, {"paths": ("PathSet", None)}, {"target": "not-an-integer-id"}, "TYPE_MISMATCH"),
    "graph_filter": ({"graph": GRAPH}, {"predicate": {"op": "gt", "left": {"field": "weight"}, "right": {"literal": 0.0}}}, {"graph": ("GraphView", ["source", "target", "weight", "relation"])}, {"predicate": {"field": "missing"}}, "FIELD_NOT_FOUND"),
    "graph_subgraph": ({"graph": GRAPH, "nodes": NODES}, {"mode": "induced"}, {"graph": ("Graph", ["source", "target", "weight", "relation"])}, {"mode": "invalid"}, "PARAMETER_ENUM"),
    "read_documents": ({"index": INDEX, "ids": IDS}, {"fields": ["id", "body"], "batch_size": 4}, {"documents": ("DocumentStream", ["id", "body"])}, {"batch_size": 0}, "PARAMETER_RANGE"),
    "text_retrieve": ({"index": INDEX}, {"query": "contract example", "limit": 4}, {"ids": ("RankedIDSet", None)}, {"limit": True}, "PARAMETER_TYPE"),
    "split_documents": ({"documents": DOCS}, {"size": 20, "overlap": 2}, {"chunks": ("ChunkStream", ["id", "title", "body"])}, {"overlap": 20}, "PARAMETER_RANGE"),
    "gather_context": ({"chunks": CHUNKS}, {"window": 1}, {"chunks": ("ChunkStream", ["id", "title", "body"])}, {"window": -1}, "PARAMETER_RANGE"),
    "semantic_extract": ({"documents": CHUNKS}, {"field_schema": {"entity": "utf8", "value": "int64"}, "context_budget": 128}, {"evidence": ("EvidenceTable", ["entity", "value"])}, {"context_budget": 0}, "PARAMETER_RANGE"),
    "evidence_merge": ({"evidence": EVIDENCE}, {"keys": ["entity"], "conflict_policy": "keep_all"}, {"evidence": ("EvidenceTable", ["entity", "value", "priority"])}, {"conflict_policy": "first_wins"}, "PARAMETER_ENUM"),
    "evidence_validate": ({"evidence": EVIDENCE, "index": INDEX}, {"strict": True}, {"evidence": ("EvidenceTable", ["entity", "value", "priority"])}, {"strict": 1}, "PARAMETER_TYPE"),
    "materialize": ({"rows": STREAM}, {"format": "arrow_ipc"}, {"rows": ("Table", ["id", "score", "eligible"])}, {"format": "pickle"}, "PARAMETER_ENUM"),
    "stream_read": ({"artifact": Type("ArtifactRef", item=TABLE)}, {"batch_size": 10}, {"rows": ("Stream", ["id", "score", "eligible"])}, {"batch_size": 0}, "PARAMETER_RANGE"),
    "broadcast": ({"artifact": TABLE}, {"consumers": ["one", "two"]}, {"one": ("ArtifactRef", None), "two": ("ArtifactRef", None)}, {"consumers": ["one", "one"]}, "PARAMETER_RANGE"),
    "release": ({"artifact": TABLE}, {}, {"done": ("ControlToken", None)}, {"artifact": "not-a-parameter"}, "PARAMETER_UNKNOWN"),
    "cache": ({"artifact": TABLE}, {"key_fields": ["id"]}, {"artifact": ("ArtifactRef", None)}, {"key_fields": ["missing"]}, "FIELD_NOT_FOUND"),
    "map": ({"rows": STREAM}, {}, {}, {"parallelism": 2}, "PARAMETER_UNKNOWN"),
    "branch": ({"condition": B}, {"predicate": {"field": "condition"}}, {}, {"predicate": {"literal": 1}}, "TYPE_MISMATCH"),
    "loop": ({"state": RECORD}, {"condition": {"field": "eligible"}, "max_iterations": 3}, {}, {"max_iterations": 17}, "PARAMETER_RANGE"),
    "collect": ({"rows": STREAM}, {"limit": 5}, {"rows": ("Table", ["id", "score", "eligible"])}, {"limit": -1}, "PARAMETER_RANGE"),
    "emit": ({"rows": TABLE}, {"output_contract": "public_result"}, {"result": ("Result", ["id", "score", "eligible"])}, {"output_contract": "private-oracle"}, "PARAMETER_ENUM"),
    "stats": ({"source": Type("DatasetRef", item=TABLE)}, {"fields": ["score"]}, {"stats": ("Stats", None)}, {"fields": ["missing"]}, "FIELD_NOT_FOUND"),
}


def fixture(operator, implementation):
    inputs, params, expected, bad, code = deepcopy(FIXTURES[operator])
    if operator == "graph_subgraph" and implementation == "edge_selected":
        inputs.pop("nodes")
        inputs["edges"] = EDGES
        params["mode"] = "edge_selected"
    if operator == "stats" and implementation == "sample":
        params["sample_size"] = 2
    declarations = {}
    for port, (kind, _) in expected.items():
        declarations[port] = "Stream[Record]" if kind == "Stream" else "ArtifactRef[Table]" if kind == "ArtifactRef" else kind
    node = {"id": "test", "operator": operator, "implementation": implementation, "params": params,
            "inputs": {k: "producer." + k for k in inputs}, "outputs": declarations}
    if operator in {"materialize", "cache"}:
        node["storage"] = implementation
    return node, inputs, deepcopy(TASK), expected, bad, code
