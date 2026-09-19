"""Public TaskInput acceptance for F1--F6, identities and privacy failures."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import uuid

from rcwg_spec.common import ContractError, digest
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.typesystem import Type

ROOT = Path(__file__).resolve().parents[1]


def example(family):
    return json.loads((ROOT / "specs" / "spec001b" / "examples" / ("public_" + family + ".json")).read_text(encoding="utf8"))


class PublicInputTests(unittest.TestCase):
    def assert_valid(self, family):
        task = example(family)
        before = deepcopy(task)
        report = validate_public_task(task)
        self.assertEqual(report["status"], "PUBLIC_TASK_VALIDATED")
        self.assertEqual(task, before)
        self.assertEqual(report["task_input_hash"], digest(task))
        self.assertEqual(len(report["input_types"]), len(task["datasets"]))
        self.assertFalse(report["formal_ready"])
        self.assertTrue(all(x["schema_hash"] for x in report["source_manifest"]))
        return report

    def invalid(self, task, code=None):
        with self.assertRaises(ContractError) as caught:
            validate_public_task(task)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertTrue(caught.exception.path == "" or caught.exception.path.startswith("/"))
        return caught.exception

    def test_f1_valid(self):
        self.assert_valid("F1")

    def test_f2_valid(self):
        self.assert_valid("F2")

    def test_f3_valid(self):
        self.assert_valid("F3")

    def test_f4_valid(self):
        self.assert_valid("F4")

    def test_f5_valid(self):
        self.assert_valid("F5")

    def test_f6_valid(self):
        self.assert_valid("F6")

    def test_f1_invalid_schema(self):
        task = example("F1")
        task["datasets"][0]["schema"]["id"] = "Any"
        self.invalid(task, "TYPE_MISMATCH")

    def test_f2_invalid_output(self):
        task = example("F2")
        task["output_contract"]["schema"] = {"region": "Unknown"}
        self.invalid(task, "TYPE_MISMATCH")

    def test_f3_invalid_graph_endpoint_type(self):
        task = example("F3")
        task["datasets"][0]["edge_schema"]["source"] = "utf8"
        self.invalid(task, "TYPE_MISMATCH")

    def test_f4_invalid_scalar_bool_as_integer(self):
        task = example("F4")
        task["datasets"][1]["value"] = 1
        self.invalid(task, "TYPE_MISMATCH")

    def test_f5_invalid_index_revision(self):
        task = example("F5")
        task["datasets"][0]["indexes"][0]["revision"] = "different"
        self.invalid(task, "REVISION_MISMATCH")

    def test_f6_invalid_document_id_mapping(self):
        task = example("F6")
        task["datasets"][-1]["id_field"] = "missing"
        self.invalid(task, "ID_MAPPING_REQUIRED")

    def privacy(self, family, location):
        task = example(family)
        canary = uuid.uuid4().hex
        if location == "top":
            task["gold"] = canary
        else:
            task["datasets"][0][location]["oracle"] = {"answer": canary}
        exc = self.invalid(task, "PUBLIC_FIELD_VIOLATION")
        self.assertNotIn(canary, str(exc))
        self.assertNotIn("answer", str(exc))

    def test_f1_private_counterexample(self):
        self.privacy("F1", "top")

    def test_f2_private_counterexample(self):
        self.privacy("F2", "schema")

    def test_f3_private_counterexample(self):
        self.privacy("F3", "stats")

    def test_f4_private_counterexample(self):
        self.privacy("F4", "stats")

    def test_f5_private_counterexample(self):
        self.privacy("F5", "schema")

    def test_f6_private_counterexample(self):
        self.privacy("F6", "node_schema")

    def test_legacy_table_normalizes_without_mutation_or_fabricated_identity(self):
        task = json.loads((ROOT / "specs/reference_v1_0/examples/task_input.json").read_text())
        original = deepcopy(task)
        report = validate_public_task(task)
        self.assertEqual(task, original)
        self.assertEqual(report["normalized_task"]["datasets"][0]["kind"], "table")
        self.assertNotEqual(report["task_input_hash"], report["normalized_input_hash"])
        self.assertIsNone(report["source_manifest"][0]["revision"])
        self.assertEqual(report["readiness"]["public_metadata"], "INCOMPLETE")
        self.assertEqual(report["normalized_task"]["output_contract"]["schema"]["id"], {"kind": "Int64"})

    def test_public_kinds_derive_concrete_type_and_domain(self):
        graph = self.assert_valid("F3")["input_types"]
        self.assertEqual(graph["dataset:graph:v1"].metadata["node_id_type"], Type("Int64"))
        self.assertEqual(graph["dataset:graph:v1"].domain, graph["dataset:seeds:v1"].domain)
        docs = self.assert_valid("F5")["input_types"]
        self.assertEqual(docs["dataset:documents:v1"].kind, "DocumentIndex")
        self.assertEqual(docs["dataset:ids:v1"].kind, "IDSet")
        table = self.assert_valid("F1")["input_types"]["dataset:records:v1"]
        self.assertEqual(table.kind, "DatasetRef")
        self.assertEqual(table.item.kind, "Table")

    def test_source_revision_required_on_explicit_tag(self):
        for field in ("revision", "schema_source"):
            task = example("F1")
            del task["datasets"][0][field]
            with self.subTest(field=field):
                self.invalid(task, "MISSING_FIELD")

    def test_source_unknown_and_hash_shape(self):
        for field, value, code in (("revision", "UNRESOLVED", "SOURCE_UNRESOLVED"),
                                   ("schema_source", None, "STRING_REQUIRED"),
                                   ("data_sha256", "not-a-hash", "SOURCE_HASH")):
            task = example("F1")
            task["datasets"][0][field] = value
            with self.subTest(field=field):
                self.invalid(task, code)

    def test_data_content_identity_recorded_but_not_execution_claimed(self):
        task = example("F1")
        task["datasets"][0]["data_sha256"] = digest({"BOOT_ONLY": "declared public fixture identity"})
        report = validate_public_task(task)
        self.assertEqual(report["source_manifest"][0]["data_sha256"], task["datasets"][0]["data_sha256"])
        self.assertEqual(report["readiness"]["public_metadata"], "COMPLETE")
        self.assertFalse(report["formal_ready"])

    def test_resources_strict_and_capped(self):
        for field, value in (("cpu_slots", True), ("cpu_slots", 9), ("wall_timeout_s", 0),
                             ("worker_memory_limit_bytes", -1), ("wall_timeout_s", float("nan"))):
            task = example("F1")
            task["resources"][field] = value
            with self.subTest(field=field, value=value):
                self.invalid(task)

    def test_duplicate_sources_and_unknown_tags(self):
        task = example("F1")
        task["datasets"].append(deepcopy(task["datasets"][0]))
        self.invalid(task, "INVALID_DATASET_ID")
        task = example("F1")
        task["datasets"][0]["kind"] = "AnySource"
        self.invalid(task, "DATASET_KIND")

    def test_malformed_objects_are_structured(self):
        for value in (None, [], 1, "task", {"task_id": "x"}):
            with self.subTest(value=value):
                self.invalid(value)
        for field, value in (("datasets", [None]), ("datasets", []), ("resources", []),
                             ("output_contract", None)):
            task = example("F1")
            task[field] = value
            with self.subTest(field=field):
                self.invalid(task)

    def test_output_shape_errors_never_escape_as_internal_error(self):
        for patch in ({"mode": []}, {"schema": None}, {"fields": [None]}, {"type": []},
                      {"k": True}, {"fields": ["id", "id"]}, {"tie_breaker": "missing"}):
            task = example("F1")
            task["output_contract"].update(patch)
            with self.subTest(patch=patch):
                self.invalid(task)

    def test_ambiguous_inferred_output_schema_is_rejected(self):
        task = example("F2")
        del task["output_contract"]["schema"]
        task["output_contract"]["fields"] = ["customer"]
        task["datasets"][1]["schema"]["customer"] = "utf8"
        self.invalid(task, "OUTPUT_SCHEMA_REQUIRED")

    def test_unknown_field_names_and_values_are_redacted(self):
        task = example("F1")
        key, value = uuid.uuid4().hex, uuid.uuid4().hex
        task["datasets"][0][key] = value
        exc = self.invalid(task, "PUBLIC_FIELD_VIOLATION")
        self.assertNotIn(key, str(exc))
        self.assertNotIn(value, str(exc))

    def test_no_private_family_or_split_fields(self):
        for key in ("family", "split", "stratum", "reference_plan", "hidden_verifier"):
            task = example("F1")
            task[key] = "held_out"
            with self.subTest(key=key):
                self.invalid(task, "PUBLIC_FIELD_VIOLATION")

    def test_unicode_nonfinite_huge_and_cycles_are_structured(self):
        for value in ("\ud800", float("inf"), 10**5000):
            task = example("F1")
            task["instruction"] = value
            self.invalid(task)
        task = example("F1")
        task["\ud800"] = "x"
        self.invalid(task)
        task = example("F1")
        task["datasets"].append(task)
        self.invalid(task)

    def test_index_fields_identity_and_model_are_checked(self):
        for patch in ({"fields": ["missing"]}, {"model_id": "x"}, {"source": ""}, {"kind": "unknown"}):
            task = example("F1")
            task["datasets"][0]["indexes"][0].update(patch)
            with self.subTest(patch=patch):
                self.invalid(task)
        task = example("F5")
        del task["datasets"][0]["indexes"][1]["model_id"]
        self.invalid(task, "STRING_REQUIRED")

    def test_explicit_edge_stream_and_ranked_id_selection(self):
        task = example("F3")
        data = {"id": "dataset:edges:v1", "kind": "edge_stream", "revision": "dev-v1",
                "schema_source": "public:BOOT_ONLY", "domain": "graph:BOOT_ONLY",
                "schema": {"source": "int64", "target": "int64"}, "stats": {"edge_count": 2}}
        task["datasets"].append(data)
        report = validate_public_task(task)
        self.assertEqual(report["input_types"][data["id"]].kind, "EdgeStream")
        task = example("F5")
        task["datasets"][1]["ranked"] = True
        self.assertEqual(validate_public_task(task)["input_types"]["dataset:ids:v1"].kind, "RankedIDSet")

    def test_normalization_is_stable_for_explicit_public_profiles(self):
        first = validate_public_task(example("F1"))
        second = validate_public_task(first["normalized_task"])
        self.assertEqual(first["normalized_input_hash"], second["normalized_input_hash"])

    def test_nonrow_output_tags_are_concrete_and_closed(self):
        for contract in (
                {"id": "scalar_v1", "type": "scalar", "mode": "exact", "value_type": "bool"},
                {"id": "record_v1", "type": "record", "mode": "exact", "schema": {"n": "int64"}},
                {"id": "set_v1", "type": "set", "mode": "exact", "item_type": "int64"},
                {"id": "path_v1", "type": "paths", "mode": "exact", "domain": "g", "revision": "v1"},
                {"id": "ids_v1", "type": "id_set", "mode": "exact", "domain": "d", "revision": "v1", "item_type": "utf8"}):
            with self.subTest(tag=contract["type"]):
                task = example("F4")
                task["output_contract"] = contract
                self.assertEqual(validate_public_task(task)["status"], "PUBLIC_TASK_VALIDATED")
                bad = deepcopy(task)
                bad["output_contract"]["k"] = 2
                self.invalid(bad, "PUBLIC_FIELD_VIOLATION")

    def test_evidence_output_needs_revision_and_identity(self):
        for field in ("domain", "revision", "id"):
            task = example("F5")
            del task["output_contract"][field]
            with self.subTest(field=field):
                self.invalid(task, "MISSING_FIELD")

    def test_nullable_and_union_fields_accepted_without_any(self):
        task = example("F4")
        task["datasets"][2]["schema"] = {
            "n": {"type": "int64", "nullable": True},
            "code": {"kind": "Union", "members": ["int64", "utf8"]}}
        t = validate_public_task(task)["input_types"]["dataset:state:v1"]
        self.assertEqual(dict(t.schema)["n"].kind, "Nullable")
        self.assertEqual(dict(t.schema)["code"].kind, "Union")

    def test_public_scalar_dates_timestamps_and_nullability(self):
        for typ, value in (("date32", "2026-09-19"), ("timestamp_us", "2026-09-19T12:00:00+00:00"),
                           ({"type": "int64", "nullable": True}, None), ("int64", 2), ("float64", 2.0)):
            task = example("F4")
            task["datasets"][1].update(type=typ, value=value)
            with self.subTest(typ=typ):
                self.assertEqual(validate_public_task(task)["status"], "PUBLIC_TASK_VALIDATED")
        for typ, value in (("date32", "2026-02-30"), ("timestamp_us", "2026-09-19T12:00:00"),
                           ("int64", True), ("float64", 2), ("bool", None)):
            task = example("F4")
            task["datasets"][1].update(type=typ, value=value)
            with self.subTest(typ=typ):
                self.invalid(task, "TYPE_MISMATCH")

    def test_graph_weight_and_document_id_facts_are_checked(self):
        task = example("F3")
        task["datasets"][0]["weight_nonnegative"] = 1
        self.invalid(task, "TYPE_MISMATCH")
        task = example("F5")
        task["datasets"][0]["id_type"] = "int64"
        self.invalid(task, "TYPE_MISMATCH")

    def test_stats_metadata_is_closed_and_estimate_source_is_required(self):
        task = example("F1")
        task["datasets"][0]["stats"] = {"row_count": 4, "eligible_fraction_estimate": 0.5}
        self.invalid(task, "INVALID_FRACTION")
        task["datasets"][0]["stats"]["estimate_source"] = "public:BOOT_ONLY"
        self.assertEqual(validate_public_task(task)["status"], "PUBLIC_TASK_VALIDATED")
        task["datasets"][0]["stats"]["custom"] = "unapproved"
        self.invalid(task, "PUBLIC_FIELD_VIOLATION")

    def mapping_workflow(self, *, loop=False):
        task = example("F5")
        task["datasets"] = [task["datasets"][0]]
        for name in ("a", "b"):
            task["datasets"].append({"id": "dataset:" + name + ":v1", "kind": "table", "revision": "dev-v1",
                                     "schema_source": "public:BOOT_ONLY", "schema": {"doc_id": "utf8"},
                                     "stats": {"row_count": 2}, "id_field": "doc_id", "id_domain": "documents:BOOT_ONLY"})
        task["datasets"].append({"id": "dataset:flag:v1", "kind": "scalar", "revision": "dev-v1",
                                 "schema_source": "public:BOOT_ONLY", "type": "bool", "value": True})
        def node(name, op, impl, inputs, params, outputs):
            return dict(id=name, operator=op, implementation=impl, inputs=inputs, params=params, outputs=outputs)
        nodes = []
        for name in ("a", "b"):
            nodes.extend([
                node("scan_" + name, "scan", "sequential", {"source": "$input." + name}, {"columns": ["doc_id"]}, {"rows": "Stream[Record]"}),
                node(name, "collect", "bounded_collect", {"rows": "scan_" + name + ".rows"}, {"limit": 4}, {"rows": "Table"})])
        if loop:
            control = node("choose", "loop", "bounded_loop", {"state": "a.rows"},
                           {"condition": {"literal": False}, "max_iterations": 1}, {"state": "Table"})
            control["regions"] = {"body": {"bindings": {"other": "b.rows", "state": "$state"}, "nodes": [], "yield": {"state": "$bound.other"}}}
            ref = "choose.state"
        else:
            control = node("choose", "branch", "predicate_branch", {"condition": "$input.flag"},
                           {"predicate": {"field": "condition"}}, {"rows": "Table"})
            control["regions"] = {label: {"bindings": {"rows": name + ".rows"}, "nodes": [], "yield": {"rows": "$bound.rows"}}
                                  for label, name in (("then", "a"), ("else", "b"))}
            ref = "choose.rows"
        nodes.extend([control,
                      node("read", "read_documents", "batched", {"index": "$input.docs", "ids": ref},
                           {"fields": ["text"], "batch_size": 2, "id_field": "doc_id"}, {"documents": "DocumentStream"}),
                      node("extract", "semantic_extract", "fixed_e0", {"documents": "read.documents"},
                           {"field_schema": task["output_contract"]["schema"], "context_budget": 128}, {"evidence": "EvidenceTable"}),
                      node("emit", "emit", "json_artifact", {"rows": "extract.evidence"},
                           {"output_contract": "document_evidence_v1"}, {"result": "Result"})])
        plan = dict(ir_version="1.0", task_id=task["task_id"],
                    external_inputs={"docs": "dataset:documents:v1", "a": "dataset:a:v1", "b": "dataset:b:v1", "flag": "dataset:flag:v1"},
                    nodes=nodes, result="emit.result")
        return task, plan

    def test_branch_cannot_launder_document_mapping_capability(self):
        from rcwg_spec.compiler import validate_workflow
        task, plan = self.mapping_workflow()
        good = validate_workflow(task, plan)
        self.assertEqual(good["status"], "IR_VALIDATED", good["diagnostics"])
        task["datasets"][2]["id_domain"] = "documents:unrelated"
        bad = validate_workflow(task, plan)
        self.assertEqual(bad["status"], "PLAN_INVALID", bad["diagnostics"])
        self.assertEqual(bad["diagnostics"][0]["code"], "TYPE_MISMATCH")

    def test_loop_cannot_launder_document_mapping_capability(self):
        from rcwg_spec.compiler import validate_workflow
        task, plan = self.mapping_workflow(loop=True)
        good = validate_workflow(task, plan)
        self.assertEqual(good["status"], "IR_VALIDATED", good["diagnostics"])
        for key in ("id_domain", "id_field"):
            del task["datasets"][2][key]
        bad = validate_workflow(task, plan)
        self.assertEqual(bad["status"], "PLAN_INVALID", bad["diagnostics"])
        self.assertEqual(bad["diagnostics"][0]["code"], "TYPE_MISMATCH")

    def test_graph_edge_schema_object_order_does_not_change_compilation(self):
        from rcwg_spec.compiler import validate_workflow
        task = example("F3")
        graph = task["datasets"][0]
        task["datasets"].append({"id": "dataset:edges:v1", "kind": "edge_stream", "revision": graph["revision"],
                                 "schema_source": graph["schema_source"], "domain": graph["domain"],
                                 "schema": dict(reversed(list(graph["edge_schema"].items()))), "stats": {"edge_count": 2}})
        plan = {"ir_version": "1.0", "task_id": task["task_id"],
                "external_inputs": {"graph": "dataset:graph:v1", "edges": "dataset:edges:v1", "seeds": "dataset:seeds:v1"},
                "nodes": [
                    {"id": "subgraph", "operator": "graph_subgraph", "implementation": "edge_selected",
                     "inputs": {"graph": "$input.graph", "edges": "$input.edges"}, "params": {"mode": "edge_selected"}, "outputs": {"graph": "Graph"}},
                    {"id": "reach", "operator": "graph_reachability", "implementation": "bfs", "inputs": {"graph": "subgraph.graph", "seeds": "$input.seeds"},
                     "params": {"direction": "out", "max_hops": 3}, "outputs": {"nodes": "NodeSet"}},
                    {"id": "emit", "operator": "emit", "implementation": "json_artifact", "inputs": {"rows": "reach.nodes"},
                     "params": {"output_contract": "reachable_v1"}, "outputs": {"result": "Result"}}], "result": "emit.result"}
        report = validate_workflow(task, plan)
        self.assertEqual(report["status"], "IR_VALIDATED", report["diagnostics"])
        task["datasets"][-1]["schema"]["weight"] = "int64"
        wrong_type = validate_workflow(task, plan)
        self.assertEqual(wrong_type["status"], "PLAN_INVALID", wrong_type["diagnostics"])


if __name__ == "__main__":
    unittest.main()
