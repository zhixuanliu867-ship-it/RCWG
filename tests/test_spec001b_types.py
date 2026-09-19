"""Actual schema/type contracts; method counts do not include subtests."""
import unittest

from rcwg_spec.common import ContractError
from rcwg_spec.typesystem import (Type, parse_type, parse_schema, row_schema,
                                  with_rows, same_type, merge_types,
                                  check_declared, type_json, unwrap_ref)


class TypeContractTests(unittest.TestCase):
    def bad(self, operation):
        with self.assertRaises(ContractError) as caught:
            operation()
        self.assertEqual(caught.exception.code, "TYPE_MISMATCH")
        self.assertTrue(caught.exception.path.startswith("/"))

    def test_all_scalar_aliases(self):
        pairs = [("bool", "Bool"), ("int64", "Int64"), ("float64", "Float64"),
                 ("utf8", "Utf8"), ("string", "Utf8"), ("date32", "Date"),
                 ("timestamp_us", "Timestamp")]
        for source, target in pairs:
            with self.subTest(source=source):
                self.assertEqual(parse_type(source).kind, target)

    def test_no_any_or_bare_container_inference(self):
        for value in ("Any", "Table", "Record", "Graph", "Stream[Record]", "integer", "Null"):
            with self.subTest(value=value):
                self.bad(lambda: parse_type(value))

    def test_closed_descriptors_and_malformed_objects(self):
        for value in (None, True, [], 2, {"kind": []}, {"type": "int64", "extra": 4},
                      {"kind": "Record", "schema": None}, {"kind": "Int64", "schema": {}},
                      {"kind": "Unknown"}, {"kind": "Set"}, {"type": "int64", "nullable": 1}):
            with self.subTest(value=value):
                self.bad(lambda: parse_type(value))

    def test_schema_nonempty_and_identifier_validation(self):
        for value in (None, [], {}, {42: "bool"}, {"a/b": "int64"}, {"valid": "Any"}):
            with self.subTest(value=value):
                self.bad(lambda: parse_schema(value))

    def test_schema_has_derived_scalar_types(self):
        schema = parse_schema({"id": "int64", "score": {"type": "float64", "nullable": True}})
        self.assertEqual(schema["id"], Type("Int64"))
        self.assertEqual(schema["score"], Type("Nullable", item=Type("Float64")))

    def test_record_table_and_stream_roundtrip(self):
        record = parse_type({"kind": "Record", "schema": {"id": "int64"}})
        for value in (record, Type("Table", schema=record.schema), Type("Stream", item=record)):
            with self.subTest(kind=value.kind):
                self.assertTrue(same_type(value, parse_type(type_json(value))))
                self.assertEqual(row_schema(value), {"id": Type("Int64")})

    def test_explicit_stream_conversion_only(self):
        table = parse_type({"kind": "Table", "schema": {"id": "int64"}})
        stream = Type("Stream", item=Type("Record", schema=table.schema))
        self.assertFalse(same_type(table, stream))
        self.bad(lambda: merge_types(table, stream))
        self.bad(lambda: parse_type({"kind": "Stream", "item": "int64"}))

    def test_references_preserve_target_and_need_explicit_consumption(self):
        table = parse_type({"kind": "Table", "schema": {"id": "int64"}, "revision": "v1"})
        ref = Type("DatasetRef", item=table, revision="v1")
        nested = Type("ArtifactRef", item=ref)
        self.assertEqual(unwrap_ref(nested), table)
        self.assertTrue(same_type(ref, parse_type(type_json(ref))))
        self.bad(lambda: row_schema(ref))
        self.assertFalse(same_type(ref, table))

    def test_ref_kind_and_target_cannot_be_forged_by_declaration(self):
        ref = Type("DatasetRef", item=Type("Table", schema=(("x", Type("Int64")),)))
        check_declared(ref, "DatasetRef[Table]")
        self.bad(lambda: check_declared(ref, "ArtifactRef[Table]"))
        self.bad(lambda: check_declared(ref, "DatasetRef[Graph]"))

    def test_projection_derived_fields_preserves_representation(self):
        record = Type("Record", schema=(("id", Type("Int64")), ("name", Type("Utf8"))))
        for original in (record, Type("Table", schema=record.schema), Type("Stream", item=record)):
            with self.subTest(kind=original.kind):
                derived = with_rows(original, {"name": Type("Utf8")})
                self.assertEqual(original.kind, derived.kind)
                self.assertEqual(row_schema(derived), {"name": Type("Utf8")})
                self.assertIn("id", row_schema(original))

    def test_with_rows_rejects_nonrows(self):
        self.bad(lambda: with_rows(Type("Int64"), {"x": Type("Int64")}))

    def test_nullable_requires_explicit_type_and_boolean_flag(self):
        t = parse_type("Nullable[Int64]")
        self.assertEqual(t.item.kind, "Int64")
        self.assertTrue(same_type(t, parse_type({"type": "int64", "nullable": True})))
        self.bad(lambda: parse_type("Nullable[Nullable[Int64]]"))

    def test_nullable_branch_merge(self):
        a = Type("Int64")
        b = Type("Nullable", item=a)
        self.assertEqual(merge_types(a, b), b)
        self.assertEqual(merge_types(b, a), b)

    def test_nullable_row_branch_merge_retains_missingness(self):
        a = Type("Table", schema=(("id", Type("Int64")),))
        b = Type("Table", schema=(("id", Type("Nullable", item=Type("Int64"))),))
        self.assertEqual(merge_types(a, b), b)

    def test_numeric_widening_and_bool_as_int_are_rejected(self):
        for a, b in (("Int64", "Float64"), ("Bool", "Int64"), ("Date", "Timestamp")):
            with self.subTest(a=a, b=b):
                self.assertFalse(same_type(Type(a), Type(b)))
                self.bad(lambda: merge_types(Type(a), Type(b)))

    def test_explicit_union_accepts_only_listed_alternatives(self):
        u = parse_type({"kind": "Union", "members": ["int64", "utf8"]})
        self.assertEqual(merge_types(Type("Int64"), u), u)
        self.assertEqual(merge_types(u, Type("Utf8")), u)
        self.bad(lambda: merge_types(u, Type("Float64")))

    def test_union_members_reject_duplicates_empty_nested(self):
        for members in ([], ["int64"], ["Int64", "int64"], "int64",
                        ["int64", {"kind": "Union", "members": ["bool", "utf8"]}]):
            with self.subTest(members=members):
                self.bad(lambda: parse_type({"kind": "Union", "members": members}))

    def test_union_member_order_is_semantically_irrelevant(self):
        a = parse_type({"kind": "Union", "members": ["int64", "utf8"]})
        b = parse_type({"kind": "Union", "members": ["utf8", "int64"]})
        self.assertTrue(same_type(a, b))

    def test_union_subset_merge_uses_existing_explicit_supertype_only(self):
        narrow = parse_type({"kind": "Union", "members": ["int64", "utf8"]})
        wide = parse_type({"kind": "Union", "members": ["int64", "utf8", "bool"]})
        self.assertEqual(merge_types(narrow, wide), wide)
        self.assertEqual(merge_types(wide, narrow), wide)
        other = parse_type({"kind": "Union", "members": ["int64", "float64"]})
        self.bad(lambda: merge_types(narrow, other))

    def test_concrete_declarations_accept_listed_nullable_union_alternatives(self):
        check_declared(Type("Int64"), "Nullable[Int64]")
        check_declared(Type("Int64"), {"kind": "Union", "members": ["int64", "utf8"]})
        self.bad(lambda: check_declared(Type("Float64"), {"kind": "Union", "members": ["int64", "utf8"]}))
        self.bad(lambda: check_declared(Type("Nullable", item=Type("Int64")), "Int64"))

    def test_row_key_order_does_not_change_schema_identity(self):
        a = parse_type({"kind": "Table", "schema": {"a": "bool", "b": "int64"}})
        b = parse_type({"kind": "Table", "schema": {"b": "int64", "a": "bool"}})
        self.assertTrue(same_type(a, b))

    def test_no_missing_column_or_width_widening(self):
        a = parse_type({"kind": "Table", "schema": {"id": "int64"}})
        b = parse_type({"kind": "Table", "schema": {"id": "int64", "name": "utf8"}})
        self.assertFalse(same_type(a, b))
        self.bad(lambda: merge_types(a, b))
        self.bad(lambda: check_declared(a, type_json(b)))

    def test_graph_view_domain_revision_and_schema_strict(self):
        base = Type("GraphView", schema=(("weight", Type("Float64")),), domain="g", revision="v1")
        for other in (Type("GraphView", schema=base.schema, domain="h", revision="v1"),
                      Type("GraphView", schema=base.schema, domain="g", revision="v2"),
                      Type("Graph", schema=base.schema, domain="g", revision="v1")):
            with self.subTest(other=other):
                self.assertFalse(same_type(base, other))
                self.bad(lambda: merge_types(base, other))
        self.assertTrue(same_type(base, parse_type(type_json(base))))

    def test_graph_metadata_directions_and_id_types_are_checked(self):
        a = Type("Graph", domain="g", revision="v1", metadata={"directed": True, "node_id_type": Type("Int64")})
        b = Type("Graph", domain="g", revision="v1", metadata={"directed": False, "node_id_type": Type("Int64")})
        self.assertFalse(same_type(a, b))
        c = Type("Graph", domain="g", revision="v1", metadata={"directed": True, "node_id_type": Type("Utf8")})
        self.assertFalse(same_type(a, c))

    def test_graph_and_document_id_domains_are_distinct(self):
        graph = parse_type({"kind": "NodeSet", "item": "int64", "domain": "g", "revision": "v1"})
        docs = parse_type({"kind": "IDSet", "item": "int64", "domain": "d", "revision": "v1"})
        self.assertFalse(same_type(graph, docs))
        self.bad(lambda: merge_types(graph, docs))

    def test_domain_descriptors_require_valid_revision(self):
        for value in ({"kind": "NodeSet", "item": "bool", "domain": "g", "revision": "v1"},
                      {"kind": "NodeSet", "item": "int64", "domain": "g"},
                      {"kind": "Graph", "schema": {"x": "int64"}, "domain": [], "revision": "v1"}):
            with self.subTest(value=value):
                self.bad(lambda: parse_type(value))

    def test_legacy_representation_assertion_does_not_override_inference(self):
        actual = Type("Stream", item=Type("Record", schema=(("id", Type("Int64")),)))
        check_declared(actual, "Stream[Record]")
        self.bad(lambda: check_declared(actual, "Table"))
        self.bad(lambda: check_declared(actual, {"kind": "Stream", "item": {"kind": "Record", "schema": {"id": "utf8"}}}))

    def test_metadata_cannot_replace_schema_identity(self):
        a = Type("Table", schema=(("id", Type("Int64")),), metadata={"row_count": 10})
        b = Type("Table", schema=(("id", Type("Int64")),), metadata={"row_count": 100})
        self.assertTrue(same_type(a, b))
        self.assertNotIn("metadata", type_json(a))

    def test_document_id_capabilities_are_part_of_branch_and_loop_types(self):
        schema = (("doc", Type("Utf8")),)
        a = Type("Table", schema=schema, revision="v1", metadata={"id_domain": "docs:A", "id_field": "doc"})
        equivalent = Type("Table", schema=schema, revision="v1", metadata={"id_mappings": [
            {"field": "doc", "domain": "docs:A", "revision": "v1"}]})
        self.assertTrue(same_type(a, equivalent))
        for other in (Type("Table", schema=schema, revision="v1"),
                      Type("Table", schema=schema, revision="v1", metadata={"id_domain": "docs:B", "id_field": "doc"}),
                      Type("Table", schema=schema, revision="v1", metadata={"id_domain": "docs:A", "id_field": "doc", "id_revision": "v2"})):
            with self.subTest(metadata=other.metadata):
                self.assertFalse(same_type(a, other))
                self.bad(lambda: merge_types(a, other))
                self.bad(lambda: merge_types(other, a))

    def test_nested_type_descriptor_limit_is_structured(self):
        value = "int64"
        for _ in range(30):
            value = {"kind": "Set", "item": value}
        self.bad(lambda: parse_type(value))


if __name__ == "__main__":
    unittest.main()
