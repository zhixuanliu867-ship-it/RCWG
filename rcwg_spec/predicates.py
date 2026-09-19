"""Closed, non-executing WorkIR expression type analysis.

This module builds runtime obligations, never evaluates model code or opens data.
SQL-style comparisons and Boolean operators propagate unknown (nullable Bool).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from .common import ContractError
from .typesystem import Type, same_type

SCALARS = {"Bool", "Int64", "Float64", "Utf8", "Date", "Timestamp"}
NUMERIC = {"Int64", "Float64"}
COLLECTIONS = {"List", "Set", "NodeSet", "IDSet", "RankedIDSet", "PathSet",
               "Table", "Stream", "DocumentStream", "ChunkStream", "EvidenceTable", "EdgeStream"}


def _fail(code, path, detail):
    raise ContractError(code, path, detail)


def base_type(t):
    return t.item if t.kind == "Nullable" else t


def nullable(t):
    return t.kind in {"Nullable", "Null"}


def _lift(t, unknown):
    return Type("Nullable", item=t) if unknown and t.kind != "Nullable" else t


def literal_type(value, path):
    if value is None:
        return Type("Null")
    if type(value) is bool:
        return Type("Bool")
    if type(value) is int:
        if not -(2**63) <= value < 2**63:
            _fail("PARAMETER_RANGE", path, "integer literal exceeds Int64")
        return Type("Int64")
    if type(value) is float:
        if not math.isfinite(value):
            _fail("PARAMETER_RANGE", path, "finite scalar literal required")
        return Type("Float64")
    if type(value) is str:
        return Type("Utf8")
    if type(value) is list:
        if not value:
            return Type("List", item=Type("Empty"))
        if any(type(v) not in {str, int, float, bool, type(None)} for v in value):
            _fail("PREDICATE_LITERAL", path, "only a flat scalar list is allowed")
        items = [literal_type(v, path + "/" + str(i)) for i, v in enumerate(value)]
        nonnull = [t for t in items if t.kind != "Null"]
        first = nonnull[0] if nonnull else Type("Null")
        if any(not same_type(first, t) for t in nonnull):
            _fail("TYPE_MISMATCH", path, "literal list elements must share one scalar type")
        return Type("List", item=_lift(first, len(nonnull) != len(items)))
    _fail("PREDICATE_LITERAL", path, "scalar or flat scalar-list literal required")


def analyze_predicate(ast, schema: dict[str, Type], path: str, *, require_bool=True):
    """Return inferred type and safe obligations for the finite approved AST."""
    obligations = []
    visited = 0

    def obligation(code, p, **values):
        obligations.append({"code": code, "path": p, **values})

    def closed(node, fields, p):
        if set(node) != set(fields):
            _fail("PREDICATE_SHAPE", p, "expression fields do not match the selected form")

    def boolean(t, p):
        if base_type(t).kind != "Bool":
            _fail("TYPE_MISMATCH", p, "Boolean expression required")

    def temporal_literal(node, inferred, expected, p):
        """Contextual literal typing; never convert a Utf8 field or add a node."""
        expected = base_type(expected)
        if expected.kind not in {"Date", "Timestamp"} or set(node) != {"literal"}:
            return inferred
        raw = node["literal"]
        values = raw if type(raw) is list else [raw]
        if not values or all(v is None for v in values):
            return inferred
        for i, value in enumerate(values):
            if value is None:
                continue
            if type(value) is not str:
                return inferred
            at = p + "/literal" + ("/" + str(i) if type(raw) is list else "")
            pattern = (r"[0-9]{4}-[0-9]{2}-[0-9]{2}" if expected.kind == "Date" else
                       r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})")
            if re.fullmatch(pattern, value) is None:
                _fail("PREDICATE_LITERAL", at, "strict ISO temporal literal required; timestamps include an explicit offset")
            if expected.kind == "Timestamp" and not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
                _fail("PREDICATE_LITERAL", at, "timezone offset is outside its clock range")
            try:
                if expected.kind == "Date":
                    date.fromisoformat(value)
                else:
                    datetime.fromisoformat(value)
            except ValueError:
                _fail("PREDICATE_LITERAL", at, "temporal literal is outside valid calendar or clock ranges")
            obligation("TEMPORAL_LITERAL_INTERPRETATION", at, value_type=expected.kind,
                       format="ISO8601", timezone_policy="explicit_offset" if expected.kind == "Timestamp" else "calendar_date")
        item = _lift(expected, any(v is None for v in values))
        return Type("List", item=item) if type(raw) is list else item

    def visit(node, p, depth):
        nonlocal visited
        visited += 1
        if depth > 64 or visited > 4096:
            _fail("PREDICATE_LIMIT", p, "expression depth or node limit exceeded")
        if type(node) is not dict:
            _fail("PREDICATE_SHAPE", p, "closed expression object required; strings are not executable")
        if "field" in node:
            closed(node, {"field"}, p)
            field = node["field"]
            if type(field) is not str or field not in schema:
                _fail("FIELD_NOT_FOUND", p + "/field", "expression field is not in the public schema")
            return schema[field]
        if "literal" in node:
            closed(node, {"literal"}, p)
            return literal_type(node["literal"], p + "/literal")
        op = node.get("op")
        if type(op) is not str:
            _fail("PREDICATE_OPERATOR", p + "/op", "approved expression operator required")
        if op in {"and", "or"}:
            closed(node, {"op", "args"}, p)
            args = node["args"]
            if type(args) is not list or len(args) < 2:
                _fail("PREDICATE_SHAPE", p + "/args", "Boolean junction requires at least two operands")
            types = [visit(a, p + "/args/" + str(i), depth + 1) for i, a in enumerate(args)]
            for t in types:
                boolean(t, p + "/args")
            return _lift(Type("Bool"), any(nullable(t) for t in types))
        if op in {"not", "is_null", "count"}:
            closed(node, {"op", "arg"}, p)
            t = visit(node["arg"], p + "/arg", depth + 1)
            if op == "not":
                boolean(t, p + "/arg")
                return t
            if op == "is_null":
                return Type("Bool")
            if base_type(t).kind not in COLLECTIONS:
                _fail("TYPE_MISMATCH", p + "/arg", "count requires a collection")
            obligation("COUNT_REQUIRES_FINITE_INPUT", p)
            return _lift(Type("Int64"), nullable(t))
        if op not in {"eq", "ne", "lt", "le", "gt", "ge", "in", "add", "sub", "mul", "div"}:
            _fail("PREDICATE_OPERATOR", p + "/op", "expression operator is not in the finite language")
        closed(node, {"op", "left", "right"}, p)
        left = visit(node["left"], p + "/left", depth + 1)
        right = visit(node["right"], p + "/right", depth + 1)
        if op in {"eq", "ne", "lt", "le", "gt", "ge", "in"}:
            right = temporal_literal(node["right"], right, left, p + "/right")
            if op != "in":
                left = temporal_literal(node["left"], left, right, p + "/left")
        lb, rb = base_type(left), base_type(right)
        unknown = nullable(left) or nullable(right)
        if op == "in":
            if rb.kind != "List" or lb.kind not in SCALARS | {"Null"}:
                _fail("TYPE_MISMATCH", p, "membership requires a scalar and a scalar list")
            elem = base_type(rb.item)
            if elem.kind not in {"Empty", "Null"} and lb.kind != "Null" and not same_type(lb, elem):
                _fail("TYPE_MISMATCH", p, "membership element types differ")
            return _lift(Type("Bool"), unknown or nullable(rb.item))
        if op in {"add", "sub", "mul", "div"}:
            if lb.kind not in NUMERIC or rb.kind not in NUMERIC or not same_type(lb, rb):
                _fail("TYPE_MISMATCH", p, "arithmetic requires matching numeric types; Bool is not numeric")
            obligation("ARITHMETIC_OVERFLOW_GUARD", p)
            if op == "div":
                obligation("DIVISION_BY_ZERO_GUARD", p)
            return _lift(Type("Float64") if op == "div" else lb, unknown)
        if lb.kind not in SCALARS | {"Null"} or rb.kind not in SCALARS | {"Null"}:
            _fail("TYPE_MISMATCH", p, "comparison operands must be scalar")
        if lb.kind != "Null" and rb.kind != "Null" and not same_type(lb, rb):
            _fail("TYPE_MISMATCH", p, "comparison types differ; no implicit cast is inserted")
        if op not in {"eq", "ne"} and "Bool" in {lb.kind, rb.kind}:
            _fail("TYPE_MISMATCH", p, "ordered comparison does not accept Bool")
        return _lift(Type("Bool"), unknown)

    result = visit(ast, path, 0)
    if require_bool:
        boolean(result, path)
    if nullable(result):
        obligation("THREE_VALUED_PREDICATE", path,
                   comparison_null="unknown", conjunction="false_dominates", disjunction="true_dominates")
    return result, obligations
