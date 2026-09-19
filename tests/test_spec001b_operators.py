"""Real branch contracts: legal derivation, contract violation and dispatch.

Generated method names provide stable unittest IDs for all 56 implementations.
Method counts and any subtests are reported separately by the acceptance gate.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from rcwg_spec.common import ContractError
from rcwg_spec.operators import REGISTRY, DISPATCH, validate_operator
from rcwg_spec.typesystem import Type, row_schema, same_type
from spec001b_operator_fixtures import fixture, TABLE, STREAM, RECORD, GRAPH, NODES, INDEX, IDS, DOCS, CHUNKS, EVIDENCE, I, F, S, B


def run(node, inputs, task, stage=None):
    return validate_operator(node, inputs, task=task, stage=stage or ("generation_probe" if node["operator"] == "stats" else "primary_execution"), path="/nodes/0")


class TestOperatorContracts(unittest.TestCase):
    def assert_error(self, code, node, inputs, task, **kw):
        with self.assertRaises(ContractError) as caught:
            run(node, inputs, task, **kw)
        self.assertEqual(caught.exception.code, code)
        self.assertTrue(caught.exception.path.startswith("/nodes/0"))

    def test_registry_matches_independent_approved_worklist(self):
        worklist = json.loads((Path(__file__).parents[1] / "specs/spec001b/operator_contract_worklist.json").read_text())
        declared = {o["operator"]: set(o["implementations"]) for o in worklist["operators"]}
        self.assertEqual({op: set(v[0]) for op, v in REGISTRY.items()}, declared)
        self.assertEqual(len(declared), 32)
        self.assertEqual(sum(map(len, declared.values())), 56)

    def test_all_branches_reject_wrong_input_and_output_ports(self):
        for op, (impls, _, _) in REGISTRY.items():
            for impl in impls:
                with self.subTest(op=op, implementation=impl):
                    node, inputs, task, *_ = fixture(op, impl)
                    bad_inputs = dict(inputs)
                    bad_inputs.pop(next(iter(inputs)))
                    self.assert_error("PORT_MISMATCH", node, bad_inputs, task)
                    if op not in {"map", "branch", "loop"}:
                        node["outputs"]["invented"] = "Table"
                        self.assert_error("PORT_MISMATCH", node, inputs, task)

    def test_all_branches_reject_unknown_and_missing_parameters(self):
        for op, (impls, required, _) in REGISTRY.items():
            for impl in impls:
                with self.subTest(op=op, implementation=impl):
                    node, inputs, task, *_ = fixture(op, impl)
                    node["params"]["unknown_extra"] = 1
                    self.assert_error("PARAMETER_UNKNOWN", node, inputs, task)
                    if required:
                        node["params"].pop("unknown_extra")
                        node["params"].pop(required[0])
                        self.assert_error("PARAMETER_REQUIRED", node, inputs, task)

    def test_scan_predicate_checks_original_schema_and_indexes(self):
        node, inputs, task, *_ = fixture("scan", "index_range")
        node["params"]["predicate"] = {"field": "eligible"}
        self.assertEqual(list(row_schema(run(node, inputs, task)["outputs"]["rows"])), ["id", "score"])
        inputs["source"] = Type("DatasetRef", item=replace(TABLE, metadata={}))
        self.assert_error("PRECONDITION_FAILED", node, inputs, task)
        inputs["source"] = TABLE
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_row_overloads_preserve_representation_and_aliases(self):
        evidence = replace(EVIDENCE, schema=TABLE.schema)
        for source in (TABLE, STREAM, evidence):
            for op, impl in (("filter", "scalar"), ("project", "column_view"), ("deduplicate", "sort_unique")):
                with self.subTest(kind=source.kind, operator=op):
                    node, inputs, task, *_ = fixture(op, impl)
                    inputs["rows"] = source
                    node["outputs"]["rows"] = "Stream[Record]" if source.kind == "Stream" else source.kind
                    output = run(node, inputs, task)["outputs"]["rows"]
                    self.assertEqual(output.kind, source.kind)
                    self.assertEqual((output.domain, output.revision), (source.domain, source.revision))
        node, inputs, task, *_ = fixture("project", "column_view")
        self.assertEqual(run(node, inputs, task)["alias_inputs"], {"rows": ["rows"]})
        node["implementation"] = "copy"
        self.assertEqual(run(node, inputs, task)["alias_inputs"], {})

    def test_projection_schema_is_derived_and_declarations_do_not_override(self):
        node, inputs, task, *_ = fixture("project", "copy")
        node["outputs"]["rows"] = {"kind": "Table", "schema": {"id": "float64"}}
        self.assert_error("TYPE_MISMATCH", node, inputs, task)
        node["outputs"]["rows"] = {"kind": "Table", "schema": {"id": "int64", "ghost": "utf8"}}
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_outer_join_nullable_fields_and_semi_anti_schema(self):
        node, inputs, task, *_ = fixture("join", "hash")
        for mode, nullable_sides in (("left", {"right"}), ("right", {"left"}), ("full", {"left", "right"})):
            node["params"]["join_type"] = mode
            schema = row_schema(run(node, inputs, task)["outputs"]["rows"])
            for name, t in schema.items():
                self.assertEqual(t.kind == "Nullable", name.split(".")[0] in nullable_sides)
        for mode in ("semi", "anti"):
            node["params"]["join_type"] = mode
            self.assertEqual(row_schema(run(node, inputs, task)["outputs"]["rows"]), dict(TABLE.schema))

    def test_join_rejects_prefix_collision_and_unknown_build_side(self):
        node, inputs, task, *_ = fixture("join", "sort_merge")
        node["params"]["build_side"] = "auto"
        self.assert_error("PARAMETER_ENUM", node, inputs, task)
        node["params"]["build_side"] = "right"
        inputs["left"] = replace(TABLE, schema=TABLE.schema + (("right.id", I),))
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_aggregate_count_mean_nullability_and_alias_uniqueness(self):
        node, inputs, task, *_ = fixture("aggregate", "sorted_group")
        node["params"] = {"group_by": [], "aggregates": [{"function": "count", "field": None, "as": "n"}, {"function": "mean", "field": "score", "as": "average"}]}
        schema = row_schema(run(node, inputs, task)["outputs"]["rows"])
        self.assertEqual(schema["n"], I)
        self.assertEqual(schema["average"], Type("Nullable", item=F))
        node["params"]["aggregates"][1]["as"] = "n"
        self.assert_error("PARAMETER_RANGE", node, inputs, task)

    def test_aggregate_min_max_sum_fields_and_nulls(self):
        for function in ("min", "max", "sum"):
            node, inputs, task, *_ = fixture("aggregate", "hash_group")
            node["params"] = {"group_by": [], "aggregates": [{"function": function, "field": "id", "as": "value"}]}
            self.assertEqual(row_schema(run(node, inputs, task)["outputs"]["rows"])["value"], Type("Nullable", item=I))
            node["params"]["aggregates"][0]["field"] = None
            self.assert_error("PARAMETER_REQUIRED", node, inputs, task)

    def test_keyed_aggregation_nonnullable_fields_have_nonempty_groups(self):
        for function in ("min", "max", "sum", "mean"):
            node, inputs, task, *_ = fixture("aggregate", "hash_group")
            node["params"] = {"group_by": ["eligible"], "aggregates": [{"function": function, "field": "score", "as": "total"}]}
            self.assertEqual(row_schema(run(node, inputs, task)["outputs"]["rows"])["total"], F)
            inputs["rows"] = replace(TABLE, schema=(("eligible", B), ("score", Type("Nullable", item=F))))
            self.assertEqual(row_schema(run(node, inputs, task)["outputs"]["rows"])["total"], Type("Nullable", item=F))
            inputs["rows"] = TABLE
            node["params"]["group_by"] = []
            self.assertEqual(row_schema(run(node, inputs, task)["outputs"]["rows"])["total"], Type("Nullable", item=F))

    def test_nullable_sort_requires_null_placement_and_zero_topk_legal(self):
        for op, impl in (("sort", "in_memory"), ("top_k", "streaming_heap")):
            node, inputs, task, *_ = fixture(op, impl)
            inputs["rows"] = replace(TABLE, schema=(("id", I), ("score", Type("Nullable", item=F))))
            self.assert_error("PARAMETER_REQUIRED", node, inputs, task)
            node["params"]["keys"][0]["nulls"] = "last"
            if op == "top_k":
                node["params"]["k"] = 0
            self.assertEqual(run(node, inputs, task)["outputs"]["rows"].kind, "Table")
            node["params"]["keys"][0]["direction"] = True
            self.assert_error("PARAMETER_TYPE", node, inputs, task)

    def test_set_domains_revisions_and_scalar_types(self):
        node, inputs, task, *_ = fixture("set_op", "sorted_merge")
        node["outputs"]["items"] = "NodeSet"
        inputs.update(left=NODES, right=NODES)
        self.assertEqual(run(node, inputs, task)["outputs"]["items"], NODES)
        for right in (replace(NODES, domain="different"), replace(NODES, revision="g2"), replace(NODES, item=S)):
            inputs["right"] = right
            self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_graph_view_overloads_preserve_domain_and_reject_foreign_seeds(self):
        for op in ("graph_neighbors", "graph_reachability", "graph_shortest_path"):
            node, inputs, task, *_ = fixture(op, REGISTRY[op][0][0])
            inputs["graph"] = replace(GRAPH, kind="GraphView")
            output = next(iter(run(node, inputs, task)["outputs"].values()))
            self.assertEqual((output.domain, output.revision), (GRAPH.domain, GRAPH.revision))
            inputs["seeds"] = replace(NODES, domain="unrelated")
            self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_shortest_path_proven_bad_weights_rejected_unknown_guarded(self):
        for impl, flag in (("bfs", "weight_equal"), ("dijkstra", "weight_nonnegative")):
            node, inputs, task, *_ = fixture("graph_shortest_path", impl)
            inputs["graph"] = replace(GRAPH, metadata={**GRAPH.metadata, flag: False})
            self.assert_error("PRECONDITION_FAILED", node, inputs, task)
            inputs["graph"] = replace(GRAPH, metadata={k: v for k, v in GRAPH.metadata.items() if k != flag})
            self.assertIn("WEIGHT_DOMAIN_CHECK", {g["code"] for g in run(node, inputs, task)["runtime_obligations"]})
            node["params"]["weight_field"] = None
            self.assertNotIn("WEIGHT_DOMAIN_CHECK", {g["code"] for g in run(node, inputs, task)["runtime_obligations"]})

    def test_graph_filter_node_schema_and_view_alias(self):
        node, inputs, task, *_ = fixture("graph_filter", "index_filter")
        node["params"]["predicate"] = {"op": "eq", "left": {"field": "node.name"}, "right": {"literal": "example"}}
        result = run(node, inputs, task)
        self.assertEqual(result["alias_inputs"], {"graph": ["graph"]})
        self.assertEqual(result["outputs"]["graph"].revision, GRAPH.revision)

    def test_subgraph_modes_never_conflate_node_and_edge_selection(self):
        for impl in ("induced", "edge_selected"):
            node, inputs, task, *_ = fixture("graph_subgraph", impl)
            node["params"]["mode"] = "edge_selected" if impl == "induced" else "induced"
            self.assert_error("PARAMETER_ENUM", node, inputs, task)
            node["params"]["mode"] = impl
            key = "nodes" if impl == "induced" else "edges"
            inputs[key] = replace(inputs[key], revision="other")
            self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_edge_subgraph_ignores_schema_json_key_order_not_field_types(self):
        node, inputs, task, *_ = fixture("graph_subgraph", "edge_selected")
        edges = inputs["edges"]
        inputs["edges"] = replace(edges, schema=tuple(reversed(edges.schema)))
        self.assertEqual(run(node, inputs, task)["outputs"]["graph"].domain, GRAPH.domain)
        inputs["edges"] = replace(edges, schema=tuple((name, I if name == "weight" else t) for name, t in edges.schema))
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_document_id_selection_overloads_require_explicit_mapping(self):
        node, inputs, task, *_ = fixture("read_documents", "batched")
        inputs["ids"] = replace(IDS, kind="RankedIDSet")
        self.assertEqual(run(node, inputs, task)["outputs"]["documents"].domain, INDEX.domain)
        table_ids = Type("Table", schema=(("document_id", S),), revision=INDEX.revision,
                         metadata={"id_field": "document_id", "id_domain": INDEX.domain})
        inputs["ids"] = table_ids
        self.assert_error("PARAMETER_REQUIRED", node, inputs, task)
        node["params"]["id_field"] = "document_id"
        run(node, inputs, task)
        inputs["ids"] = replace(table_ids, metadata={})
        self.assert_error("TYPE_MISMATCH", node, inputs, task)
        inputs["ids"] = NODES
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_document_domains_revisions_and_fields(self):
        node, inputs, task, *_ = fixture("read_documents", "per_document")
        for ids in (replace(IDS, domain="foreign"), replace(IDS, revision="old"), replace(IDS, item=I)):
            inputs["ids"] = ids
            self.assert_error("TYPE_MISMATCH", node, inputs, task)
        inputs["ids"] = IDS
        node["params"]["fields"] = ["hidden_answer"]
        self.assert_error("FIELD_NOT_FOUND", node, inputs, task)

    def test_dense_binding_is_facility_readiness_not_model_type_error(self):
        node, inputs, task, *_ = fixture("text_retrieve", "dense_fixed")
        inputs["index"] = replace(INDEX, metadata={"id_type": S})
        result = run(node, inputs, task)
        self.assertEqual(result["outputs"]["ids"].item, S)
        self.assertIn("DENSE_INDEX_SERVICE_BINDING_REQUIRED", {g["code"] for g in result["runtime_obligations"]})

    def test_semantic_extract_document_and_chunk_overloads_and_provenance(self):
        node, inputs, task, *_ = fixture("semantic_extract", "fixed_e0")
        for source in (DOCS, CHUNKS):
            inputs["documents"] = source
            result = run(node, inputs, task)
            self.assertEqual(result["outputs"]["evidence"].revision, INDEX.revision)
            self.assertIn("SERVICE_BINDING_REQUIRED", {g["code"] for g in result["runtime_obligations"]})
        node["params"]["field_schema"] = {"value": "invented-type"}
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_declared_priority_is_closed_typed_public_ordering(self):
        node, inputs, task, *_ = fixture("evidence_merge", "by_entity")
        node["params"]["conflict_policy"] = "declared_priority"
        self.assert_error("PARAMETER_REQUIRED", node, inputs, task)
        node["params"]["priority_rule"] = [{"field": "priority", "direction": "desc"}]
        run(node, inputs, task)
        node["params"]["priority_rule"][0]["field"] = "private_score"
        self.assert_error("FIELD_NOT_FOUND", node, inputs, task)
        node["params"]["conflict_policy"] = "reject"
        self.assert_error("PARAMETER_UNKNOWN", node, inputs, task)

    def test_evidence_validation_public_index_domain_required(self):
        node, inputs, task, *_ = fixture("evidence_validate", "span_check")
        inputs["index"] = replace(INDEX, revision="old")
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_explicit_stream_conversion_and_materialize_storage(self):
        node, inputs, task, *_ = fixture("materialize", "disk")
        inputs["rows"] = TABLE
        self.assert_error("TYPE_MISMATCH", node, inputs, task)
        inputs["rows"] = STREAM
        node["storage"] = "memory"
        self.assert_error("PARAMETER_ENUM", node, inputs, task)
        node, inputs, task, *_ = fixture("stream_read", "arrow_batches")
        for source in (TABLE, Type("ArtifactRef", item=TABLE), STREAM, GRAPH):
            inputs["artifact"] = source
            result = run(node, inputs, task)
            self.assertEqual(result["outputs"]["rows"].kind, "Stream")
            self.assertEqual(result["alias_inputs"], {"rows": ["artifact"]})
        inputs["artifact"] = S
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_broadcast_named_refs_and_copy_alias_distinction(self):
        node, inputs, task, *_ = fixture("broadcast", "shared_ref")
        result = run(node, inputs, task)
        self.assertTrue(all(same_type(t.item, TABLE) for t in result["outputs"].values()))
        self.assertEqual(result["alias_inputs"], {"one": ["artifact"], "two": ["artifact"]})
        node["implementation"] = "copy_each"
        self.assertEqual(run(node, inputs, task)["alias_inputs"], {})
        node["params"]["consumers"] = ["../file"]
        self.assert_error("PARAMETER_RANGE", node, inputs, task)

    def test_cache_memory_alias_disk_copy_and_same_run_identity(self):
        for impl, expected in (("memory", {"artifact": ["artifact"]}), ("disk", {})):
            node, inputs, task, *_ = fixture("cache", impl)
            result = run(node, inputs, task)
            self.assertEqual(result["alias_inputs"], expected)
            guard = next(x for x in result["runtime_obligations"] if x["code"] == "SAME_RUN_ONLY")
            self.assertTrue(guard["include_content_identity"] and guard["include_schema_identity"])

    def test_control_types_and_nullable_condition_obligations(self):
        node, inputs, task, *_ = fixture("map", "bounded_map")
        inputs["rows"] = TABLE
        self.assert_error("TYPE_MISMATCH", node, inputs, task)
        node, inputs, task, *_ = fixture("branch", "predicate_branch")
        inputs["condition"] = Type("Nullable", item=B)
        result = run(node, inputs, task)
        self.assertEqual(result["outputs"], {})
        self.assertIn({"code": "PREDICATE_UNKNOWN_POLICY", "path": "/nodes/0", "policy": "runtime_error"}, result["runtime_obligations"])
        inputs["condition"] = I
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_loop_scalar_and_record_conditions_and_cap_guard(self):
        node, inputs, task, *_ = fixture("loop", "bounded_loop")
        inputs["state"] = I
        node["params"]["condition"] = {"op": "lt", "left": {"field": "state"}, "right": {"literal": 10}}
        node["params"]["max_iterations"] = 16
        guard = next(g for g in run(node, inputs, task)["runtime_obligations"] if g["code"] == "CONTINUATION_AT_LIMIT")
        self.assertEqual(guard["true_at_cap"], "LOOP_LIMIT_REACHED")
        self.assertEqual(guard["false_at_cap"], "COMPLETED")
        node["params"]["max_iterations"] = True
        self.assert_error("PARAMETER_TYPE", node, inputs, task)

    def test_emit_checks_actual_fields_types_and_contract(self):
        node, inputs, task, *_ = fixture("emit", "json_artifact")
        inputs["rows"] = Type("Table", schema=(("id", I),))
        self.assert_error("FIELD_NOT_FOUND", node, inputs, task)
        inputs["rows"] = replace(TABLE, schema=(("id", I), ("score", I)))
        self.assert_error("TYPE_MISMATCH", node, inputs, task)
        inputs["rows"] = TABLE
        node["params"]["output_contract"] = "exact_ordered_topk_v1"
        run(node, inputs, task)

    def test_emit_all_public_output_tags_and_wrong_representations(self):
        examples = [
            ({"type": "ordered_records", "mode": "exact", "fields": ["id"]}, TABLE),
            ({"type": "records", "fields": ["id"]}, STREAM),
            ({"type": "evidence", "fields": ["entity"], "domain": INDEX.domain, "revision": INDEX.revision}, EVIDENCE),
            ({"type": "paths", "domain": GRAPH.domain, "revision": GRAPH.revision}, Type("PathSet", item=I, domain=GRAPH.domain, revision=GRAPH.revision)),
            ({"type": "node_set", "domain": GRAPH.domain, "revision": GRAPH.revision, "item_type": "int64"}, NODES),
            ({"type": "id_set", "domain": INDEX.domain, "revision": INDEX.revision, "item_type": "utf8"}, IDS),
            ({"type": "scalar", "value_type": "bool"}, B),
            ({"type": "record", "fields": ["id"]}, RECORD),
            ({"type": "set", "item_type": "int64"}, Type("Set", item=I)),
        ]
        for contract, source in examples:
            with self.subTest(tag=contract["type"]):
                node, inputs, task, *_ = fixture("emit", "json_artifact")
                task["output_contract"] = {"id": "public_result", **contract}
                inputs["rows"] = source
                self.assertEqual(run(node, inputs, task)["outputs"]["result"].item, source)
                inputs["rows"] = GRAPH
                self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_emit_rejects_same_domain_wrong_revision_and_item_scalar(self):
        node, inputs, task, *_ = fixture("emit", "json_artifact")
        task["output_contract"] = {"id": "public_result", "type": "node_set", "domain": GRAPH.domain, "revision": GRAPH.revision, "item_type": "int64"}
        for source in (replace(NODES, revision="old"), replace(NODES, item=S), replace(NODES, kind="PathSet")):
            inputs["rows"] = source
            self.assert_error("TYPE_MISMATCH", node, inputs, task)
        task["output_contract"] = {"id": "public_result", "type": "scalar", "value_type": "int64"}
        inputs["rows"] = B
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_join_project_document_mapping_chain_and_unmapped_counterexample(self):
        # Graph IDs become document IDs only by consuming the declared relation.
        mapping = Type("Table", schema=(("id", I), ("document_id", S)), revision=INDEX.revision,
                       metadata={"id_field": "document_id", "id_domain": INDEX.domain})
        node, inputs, task, *_ = fixture("join", "hash")
        inputs["right"] = mapping
        joined = run(node, inputs, task)["outputs"]["rows"]
        self.assertEqual(joined.metadata["id_revision"], INDEX.revision)
        node, inputs, task, *_ = fixture("project", "copy")
        node["params"]["columns"] = ["document_id"]
        inputs["rows"] = joined
        selected = run(node, inputs, task)["outputs"]["rows"]
        node, inputs, task, *_ = fixture("read_documents", "batched")
        node["params"]["id_field"] = "document_id"
        inputs["ids"] = selected
        self.assertEqual(run(node, inputs, task)["outputs"]["documents"].domain, INDEX.domain)
        inputs["ids"] = replace(selected, metadata={})
        self.assert_error("TYPE_MISMATCH", node, inputs, task)

    def test_join_collision_renames_document_mapping_and_projection_drops_it(self):
        node, inputs, task, *_ = fixture("join", "hash")
        inputs["right"] = replace(TABLE, revision=INDEX.revision, metadata={"id_field": "id", "id_domain": INDEX.domain})
        joined = run(node, inputs, task)["outputs"]["rows"]
        self.assertEqual(joined.metadata["id_mappings"][0]["field"], "right.id")
        node, inputs, task, *_ = fixture("project", "copy")
        node["params"]["columns"] = ["left.id"]
        inputs["rows"] = joined
        self.assertEqual(run(node, inputs, task)["outputs"]["rows"].metadata["id_mappings"], [])

    def test_aggregate_only_grouped_document_id_retains_mapping(self):
        node, inputs, task, *_ = fixture("aggregate", "hash_group")
        inputs["rows"] = replace(TABLE, revision=INDEX.revision, metadata={"id_field": "id", "id_domain": INDEX.domain})
        node["params"]["group_by"] = ["id"]
        self.assertEqual(run(node, inputs, task)["outputs"]["rows"].metadata["id_field"], "id")
        node["params"]["group_by"] = []
        self.assertEqual(run(node, inputs, task)["outputs"]["rows"].metadata["id_mappings"], [])

    def test_stats_stage_information_and_conditional_sample_size(self):
        node, inputs, task, *_ = fixture("stats", "sample")
        self.assert_error("STAGE_FORBIDDEN", node, inputs, task, stage="primary_execution")
        task["information_level"] = "I1"
        self.assert_error("STAGE_FORBIDDEN", node, inputs, task)
        task["information_level"] = "I2"
        node["params"].pop("sample_size")
        self.assert_error("PARAMETER_REQUIRED", node, inputs, task)
        node["implementation"] = "metadata"
        node["params"]["sample_size"] = 2
        self.assert_error("PARAMETER_UNKNOWN", node, inputs, task)


def _legal(op, impl):
    def method(self):
        node, inputs, task, expected, *_ = fixture(op, impl)
        original = deepcopy((node, inputs, task))
        result = run(node, inputs, task)
        self.assertEqual(set(result["outputs"]), set(expected))
        for port, (kind, fields) in expected.items():
            output = result["outputs"][port]
            self.assertEqual(output.kind, kind)
            if fields is not None:
                schema = dict(output.item.schema) if kind == "Stream" else dict(output.schema)
                self.assertEqual(list(schema), fields)
        self.assertEqual((node, inputs, task), original)
    return method


def _illegal(op, impl):
    def method(self):
        node, inputs, task, _, bad, code = fixture(op, impl)
        node["params"].update(bad)
        self.assert_error(code, node, inputs, task)
    return method


def _dispatch(op, impl):
    def method(self):
        node, inputs, task, *_ = fixture(op, impl)
        result = DISPATCH[op + ":" + impl](node, inputs, task=task,
                                         stage="generation_probe" if op == "stats" else "primary_execution", path="/nodes/0")
        self.assertEqual(result["dispatch_id"], op + ":" + impl)
        node["implementation"] = "unregistered_implementation"
        self.assert_error("UNKNOWN_IMPLEMENTATION", node, inputs, task)
    return method


for _op, (_impls, _, _) in REGISTRY.items():
    for _impl in _impls:
        for _label, _factory in (("legal", _legal), ("illegal", _illegal), ("dispatch", _dispatch)):
            setattr(TestOperatorContracts, "test_" + _op + "_" + _impl + "_" + _label, _factory(_op, _impl))


if __name__ == "__main__":
    unittest.main()
