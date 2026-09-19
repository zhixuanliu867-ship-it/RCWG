"""Finite AST typing and three-valued runtime obligations; no expression eval."""
from copy import deepcopy
import unittest
from rcwg_spec.common import ContractError
from rcwg_spec.predicates import analyze_predicate
from rcwg_spec.typesystem import Type

I, F, B, S = Type("Int64"), Type("Float64"), Type("Bool"), Type("Utf8")
SCHEMA = {"n": I, "f": F, "flag": B, "maybe": Type("Nullable", item=B),
          "missing_n": Type("Nullable", item=I), "name": S, "items": Type("Set", item=I),
          "date": Type("Date"), "time": Type("Timestamp")}


class TestPredicateContracts(unittest.TestCase):
    def analyze(self, expr, **kw):
        return analyze_predicate(expr, SCHEMA, "/predicate", **kw)

    def invalid(self, expr, code="TYPE_MISMATCH", **kw):
        with self.assertRaises(ContractError) as caught:
            self.analyze(expr, **kw)
        self.assertEqual(caught.exception.code, code)
        self.assertTrue(caught.exception.path.startswith("/predicate"))

    def test_scalar_field_and_bool_literal(self):
        self.assertEqual(self.analyze({"field": "flag"})[0], B)
        self.assertEqual(self.analyze({"literal": True})[0], B)

    def test_unknown_field_is_structured(self):
        self.invalid({"field": "missing"}, "FIELD_NOT_FOUND")

    def test_code_string_never_executed(self):
        self.invalid("__import__('os').system('never')", "PREDICATE_SHAPE")

    def test_unknown_operator_and_closed_ast_fields(self):
        self.invalid({"op": "execute", "arg": {"literal": True}}, "PREDICATE_OPERATOR")
        self.invalid({"literal": True, "code": "ignored"}, "PREDICATE_SHAPE")

    def test_all_comparison_operators(self):
        for op in ("eq", "ne", "lt", "le", "gt", "ge"):
            with self.subTest(op=op):
                self.assertEqual(self.analyze({"op": op, "left": {"field": "n"}, "right": {"literal": 3}})[0], B)

    def test_bool_is_never_numeric(self):
        for op in ("eq", "lt", "add", "div"):
            with self.subTest(op=op):
                self.invalid({"op": op, "left": {"field": "flag"}, "right": {"literal": 1}}, require_bool=False)

    def test_numeric_types_do_not_silently_widen(self):
        self.invalid({"op": "add", "left": {"field": "n"}, "right": {"literal": 1.0}}, require_bool=False)

    def test_nullable_comparison_and_null_literal_propagate_unknown(self):
        for right in ({"literal": 0}, {"literal": None}):
            t, guards = self.analyze({"op": "eq", "left": {"field": "missing_n"}, "right": right})
            self.assertEqual(t, Type("Nullable", item=B))
            self.assertIn("THREE_VALUED_PREDICATE", {g["code"] for g in guards})

    def test_three_valued_boolean_rules_recorded(self):
        for op in ("and", "or"):
            t, guards = self.analyze({"op": op, "args": [{"field": "maybe"}, {"literal": False}]})
            self.assertEqual(t, Type("Nullable", item=B))
            guard = next(g for g in guards if g["code"] == "THREE_VALUED_PREDICATE")
            self.assertEqual(guard["conjunction"], "false_dominates")
            self.assertEqual(guard["disjunction"], "true_dominates")

    def test_not_requires_boolean_and_preserves_nullability(self):
        self.assertEqual(self.analyze({"op": "not", "arg": {"field": "maybe"}})[0], Type("Nullable", item=B))
        self.invalid({"op": "not", "arg": {"field": "n"}})

    def test_is_null_returns_nonnullable_boolean(self):
        self.assertEqual(self.analyze({"op": "is_null", "arg": {"field": "missing_n"}})[0], B)

    def test_boolean_junction_non_boolean_and_empty_rejected(self):
        self.invalid({"op": "and", "args": [{"literal": True}, {"field": "n"}]})
        self.invalid({"op": "or", "args": []}, "PREDICATE_SHAPE")

    def test_arithmetic_all_operators_and_overflow_obligations(self):
        for op in ("add", "sub", "mul", "div"):
            t, guards = self.analyze({"op": op, "left": {"field": "n"}, "right": {"literal": 2}}, require_bool=False)
            self.assertEqual(t, F if op == "div" else I)
            self.assertIn("ARITHMETIC_OVERFLOW_GUARD", {g["code"] for g in guards})

    def test_division_zero_retains_runtime_guard(self):
        t, guards = self.analyze({"op": "div", "left": {"field": "n"}, "right": {"literal": 0}}, require_bool=False)
        self.assertEqual(t, F)
        self.assertIn("DIVISION_BY_ZERO_GUARD", {g["code"] for g in guards})

    def test_arithmetic_nullable_propagation(self):
        t, _ = self.analyze({"op": "mul", "left": {"field": "missing_n"}, "right": {"literal": 2}}, require_bool=False)
        self.assertEqual(t, Type("Nullable", item=I))

    def test_membership_typed_lists_nulls_and_empty(self):
        for values, nullable in (([1, 2], False), ([1, None], True), ([], False)):
            t, _ = self.analyze({"op": "in", "left": {"field": "n"}, "right": {"literal": values}})
            self.assertEqual(t, Type("Nullable", item=B) if nullable else B)

    def test_membership_mismatched_mixed_and_nested_lists_rejected(self):
        for values, code in ((["text"], "TYPE_MISMATCH"), ([1, True], "TYPE_MISMATCH"), ([[1]], "PREDICATE_LITERAL")):
            self.invalid({"op": "in", "left": {"field": "n"}, "right": {"literal": values}}, code)

    def test_count_collections_has_finite_input_obligation(self):
        t, guards = self.analyze({"op": "count", "arg": {"field": "items"}}, require_bool=False)
        self.assertEqual(t, I)
        self.assertIn("COUNT_REQUIRES_FINITE_INPUT", {g["code"] for g in guards})
        self.invalid({"op": "count", "arg": {"field": "n"}}, require_bool=False)

    def test_nonfinite_and_int_overflow_literals_rejected(self):
        for v in (float("inf"), float("nan"), 2**63, -(2**63)-1):
            self.invalid({"literal": v}, "PARAMETER_RANGE", require_bool=False)

    def test_ast_cycle_and_depth_are_bounded(self):
        expr = {"op": "not"}
        expr["arg"] = expr
        self.invalid(expr, "PREDICATE_LIMIT")

    def test_composite_expression_and_inputs_unchanged(self):
        expr = {"op": "and", "args": [{"field": "flag"}, {"op": "gt", "left": {"op": "add", "left": {"field": "n"}, "right": {"literal": 2}}, "right": {"literal": 0}}]}
        before = deepcopy(expr)
        self.assertEqual(self.analyze(expr)[0], B)
        self.assertEqual(expr, before)

    def test_iso_date_literal_context_is_typed_without_mutating_ast(self):
        for left, right in (({"field": "date"}, {"literal": "2026-09-19"}),
                            ({"literal": "2024-02-29"}, {"field": "date"})):
            expr = {"op": "ge", "left": left, "right": right}
            original = deepcopy(expr)
            t, guards = self.analyze(expr)
            self.assertEqual(t, B)
            self.assertEqual(expr, original)
            self.assertIn("TEMPORAL_LITERAL_INTERPRETATION", {g["code"] for g in guards})

    def test_iso_timestamp_requires_offset_and_preserves_microseconds(self):
        for value in ("2026-09-19T01:02:03Z", "2026-09-19T09:02:03.123456+08:00"):
            t, guards = self.analyze({"op": "eq", "left": {"field": "time"}, "right": {"literal": value}})
            self.assertEqual(t, B)
            self.assertEqual(guards[0]["value_type"], "Timestamp")
            self.assertEqual(guards[0]["timezone_policy"], "explicit_offset")

    def test_temporal_membership_lists_and_nulls(self):
        t, guards = self.analyze({"op": "in", "left": {"field": "date"}, "right": {"literal": ["2026-09-19", None]}})
        self.assertEqual(t, Type("Nullable", item=B))
        self.assertEqual(guards[0]["value_type"], "Date")

    def test_invalid_date_clock_and_ambiguous_timestamp_literals_rejected(self):
        for field, value in (("date", "2026-02-29"), ("date", "2026-9-19"), ("date", "2026-13-01"),
                             ("time", "2026-09-19T01:02:03"), ("time", "2026-09-19 01:02:03Z"),
                             ("time", "2026-09-19T25:02:03Z"), ("time", "2026-09-19T01:02:03.1234567Z"),
                             ("time", "2026-09-19T01:02:03+08:60")):
            with self.subTest(field=field, value=value):
                self.invalid({"op": "eq", "left": {"field": field}, "right": {"literal": value}}, "PREDICATE_LITERAL")

    def test_temporal_context_does_not_cast_utf8_fields_or_numeric_literals(self):
        self.invalid({"op": "eq", "left": {"field": "date"}, "right": {"field": "name"}})
        self.invalid({"op": "eq", "left": {"field": "date"}, "right": {"literal": 20260919}})
        self.invalid({"op": "eq", "left": {"field": "date"}, "right": {"field": "time"}})


if __name__ == "__main__":
    unittest.main()
