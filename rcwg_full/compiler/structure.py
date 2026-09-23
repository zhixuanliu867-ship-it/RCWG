"""WorkIR structural/lexical dependency analysis; NOT a complete compiler.

This module is deliberately separate from operator type/parameter validation.
A successful result has full_validation=False. It never executes or rewrites IR,
opens a dataset, calls a model, or grants formal-runtime readiness.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from rcwg_spec.common import ContractError, canonical, digest

NAME = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
MAX_JSON_BYTES = 65536
MAX_JSON_DEPTH = 64
CONTROL_REGIONS = {"map": {"body"}, "branch": {"then", "else"}, "loop": {"body"}}
PENDING = ["operator_ports_parameters", "type_inference", "predicate_typing",
           "semantic_preconditions", "dynamic_instance_guards", "alias_release_checks"]


def fail(code: str, path: str, detail: str) -> None:
    raise ContractError(code, path, detail)


def obj(x: Any, required: set[str], optional: set[str], path: str) -> dict:
    if type(x) is not dict:
        fail("IR_SHAPE", path, "object required")
    if not all(type(k) is str for k in x):
        fail("IR_SHAPE", path, "string keys required")
    if required - x.keys():
        fail("IR_SHAPE", path, "missing required fields")
    if x.keys() - required - optional:
        fail("IR_SHAPE", path, "unknown fields")
    return x


def ident(x: Any, path: str) -> str:
    if type(x) is not str or not NAME.fullmatch(x):
        fail("IR_IDENTIFIER", path, "identifier must match the WorkIR node alphabet")
    return x


def nonempty(x: Any, path: str) -> str:
    if type(x) is not str or not x.strip():
        fail("IR_SHAPE", path, "nonempty string required")
    return x


def integer(x: Any, lo: int, hi: int, path: str) -> int:
    if type(x) is not int or not lo <= x <= hi:
        fail("RESOURCE_LIMIT", path, "integer outside the declared implementation limit")
    return x


def _json_value(value: Any) -> None:
    """Reject non-JSON in-process values, cycles, surrogates and excess depth."""
    todo = [(value, 0, frozenset())]
    while todo:
        x, depth, parents = todo.pop()
        if depth > MAX_JSON_DEPTH:
            fail("IR_INPUT_LIMIT", "", "JSON nesting limit exceeded")
        t = type(x)
        if t is str:
            try:
                x.encode("utf-8", "strict")
            except UnicodeEncodeError:
                fail("INVALID_UNICODE", "", "unpaired surrogate")
        elif t is float:
            if not math.isfinite(x):
                fail("INVALID_NUMBER", "", "non-finite number")
        elif t in (int, bool, type(None)):
            continue
        elif t in (dict, list):
            if id(x) in parents:
                fail("IR_INPUT_LIMIT", "", "cyclic in-process object")
            ancestors = parents | {id(x)}
            if t is dict:
                if not all(type(k) is str for k in x):
                    fail("IR_SHAPE", "", "JSON object keys must be strings")
                children = [*x.keys(), *x.values()]
            else:
                children = x
            todo.extend((child, depth + 1, ancestors) for child in children)
        else:
            fail("IR_SHAPE", "", "non-JSON Python value")


def parse_ir_bytes(raw: bytes) -> dict:
    """Strict 64-KiB final-JSON parser. No fence extraction, repair, or retries."""
    if type(raw) is not bytes:
        fail("IR_SHAPE", "", "bytes required")
    if len(raw) > MAX_JSON_BYTES:
        fail("IR_INPUT_LIMIT", "", "final JSON exceeds 65536 bytes")
    try:
        source = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        fail("INVALID_UNICODE", "", "UTF-8 required")
    # Pre-parse depth guard; delimiters inside strings are not nesting.
    quoted = escaped = False
    depth = 0
    for ch in source:
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                fail("IR_INPUT_LIMIT", "", "JSON nesting limit exceeded")
        elif ch in "]}":
            depth -= 1
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                fail("DUPLICATE_JSON_KEY", "", "duplicate object key")
            result[k] = v
        return result
    def reject(_):
        fail("INVALID_NUMBER", "", "non-finite numeric token")
    def finite(raw_number):
        value = float(raw_number)
        if not math.isfinite(value):
            reject(raw_number)
        return value
    try:
        plan = json.loads(source, object_pairs_hook=pairs, parse_constant=reject,
                          parse_float=finite)
    except ContractError:
        raise
    except (ValueError, RecursionError):
        fail("INVALID_JSON", "", "invalid or unsupported JSON representation")
    _json_value(plan)
    if type(plan) is not dict:
        fail("IR_SHAPE", "", "root must be an object")
    return plan


def default_registry() -> dict[str, frozenset[str]]:
    path = Path(__file__).resolve().parents[2] / "specs/spec001a/operator_contracts.json"
    data = json.loads(path.read_text(encoding="utf8"))
    return {x["operator"]: frozenset(x["implementations"]) for x in data}


def analyze_structure(plan: dict, *, task_id: str, allowed_sources: set[str],
                      cpu_slots: int = 8,
                      registry: Mapping[str, frozenset[str]] | None = None) -> dict:
    """Resolve references and lexical regions on a *validated public task*.

    Top-level references: $input.name or node.port.
    Region references: $bound.name or same-scope node.port.
    A region's bindings RHS resolves in its parent scope. Only map/loop bindings
    may use their respective $item/$state intrinsic. IDs are local to a scope;
    all exported graph identities are scope-qualified. Node list order is kept.
    """
    _json_value(plan)
    if len(canonical(plan)) > MAX_JSON_BYTES:
        fail("IR_INPUT_LIMIT", "", "canonical IR exceeds byte limit")
    registry = default_registry() if registry is None else registry
    integer(cpu_slots, 1, 8, "/task/resources/cpu_slots")
    if type(allowed_sources) is not set or not all(type(x) is str for x in allowed_sources):
        fail("IR_SHAPE", "/task/datasets", "validated source-ID set required")
    obj(plan, {"ir_version", "task_id", "external_inputs", "nodes", "result"},
        {"assumptions", "limits"}, "")
    if plan["ir_version"] != "1.0":
        fail("IR_VERSION", "/ir_version", "WorkIR 1.0 required")
    if plan["task_id"] != task_id:
        fail("TASK_ID_MISMATCH", "/task_id", "task and plan IDs differ")
    ext = obj(plan["external_inputs"], set(), set(plan["external_inputs"]) if type(plan["external_inputs"]) is dict else set(), "/external_inputs")
    for k, source in ext.items():
        ident(k, "/external_inputs")
        nonempty(source, "/external_inputs/" + k)
        if source not in allowed_sources:
            fail("EXTERNAL_INPUT_MISMATCH", "/external_inputs/" + k, "source is not in the public task")
    if "assumptions" in plan:
        a = plan["assumptions"]
        if type(a) is not list or len(a) > 12:
            fail("IR_SHAPE", "/assumptions", "at most 12 strings")
        for i, x in enumerate(a):
            nonempty(x, "/assumptions/" + str(i))
    limits = obj(plan.get("limits", {}), set(), {"max_node_instances", "max_loop_iterations"}, "/limits")
    for k, maximum in (("max_node_instances", 4096), ("max_loop_iterations", 16)):
        if k in limits:
            integer(limits[k], 1, maximum, "/limits/" + k)
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    scopes: list[dict] = []
    total = 0

    def visit(nodes, *, scope, pointer, depth, bound, yields=None, expected_yields=None):
        nonlocal total
        if depth > 2:
            fail("REGION_DEPTH_LIMIT", pointer, "at most two nested region levels")
        if type(nodes) is not list or (depth == 0 and not nodes) or len(nodes) > 48:
            fail("IR_SHAPE", pointer, "bounded node array required")
        total += len(nodes)
        if total > 48:
            fail("LOGICAL_NODE_LIMIT", pointer, "global recursive logical-node cap is 48")
        by_id = {}
        positions = {}
        for i, n in enumerate(nodes):
            p = pointer + "/" + str(i)
            obj(n, {"id", "operator", "implementation", "inputs", "params", "outputs"},
                {"after", "resources", "storage", "regions", "param_bindings"}, p)
            name = ident(n["id"], p + "/id")
            if name in by_id:
                fail("DUPLICATE_NODE_ID", p + "/id", "IDs must be unique within a lexical scope")
            by_id[name], positions[name] = n, i
            op = nonempty(n["operator"], p + "/operator")
            if op not in registry:
                fail("UNKNOWN_OPERATOR", p + "/operator", "unregistered operator")
            imp = nonempty(n["implementation"], p + "/implementation")
            if imp not in registry[op]:
                fail("UNKNOWN_IMPLEMENTATION", p + "/implementation", "unregistered implementation")
            for field in ("inputs", "params", "outputs"):
                if type(n[field]) is not dict:
                    fail("IR_SHAPE", p + "/" + field, "object required")
            if not n["outputs"]:
                fail("IR_SHAPE", p + "/outputs", "output declarations required")
            for port, typ in n["outputs"].items():
                ident(port, p + "/outputs")
                nonempty(typ, p + "/outputs/" + port)
            for port in n["inputs"]:
                ident(port, p + "/inputs")
            resources = obj(n.get("resources", {}), set(), {"cpu_slots", "max_parallelism", "batch_rows"}, p + "/resources")
            for field, cap in (("cpu_slots", cpu_slots), ("max_parallelism", 8), ("batch_rows", 1048576)):
                if field in resources:
                    integer(resources[field], 1, cap, p + "/resources/" + field)
            if "storage" in n and (type(n["storage"]) is not str or n["storage"] not in {"stream", "memory", "disk", "shared_ref"}):
                fail("IR_SHAPE", p + "/storage", "unknown storage mode")
        local_edges = set()

        def resolve(ref, p):
            nonempty(ref, p)
            if ref.startswith("$input."):
                if depth != 0:
                    fail("SCOPE_VIOLATION", p, "region inputs must be explicitly bound")
                name = ref[len("$input."):]
                if name not in ext:
                    fail("UNKNOWN_REFERENCE", p, "unknown external binding")
                return None
            if ref.startswith("$bound."):
                if depth == 0:
                    fail("SCOPE_VIOLATION", p, "no bound variables at root")
                if ref[len("$bound."):] not in bound:
                    fail("UNKNOWN_REFERENCE", p, "unknown region binding")
                return None
            pieces = ref.split(".")
            if len(pieces) != 2 or not all(NAME.fullmatch(s) for s in pieces):
                fail("REFERENCE_SYNTAX", p, "expected a lexical node.port reference")
            parent, port = pieces
            if parent not in by_id or port not in by_id[parent]["outputs"]:
                fail("UNKNOWN_REFERENCE", p, "node or output port not in this scope")
            return parent

        def dependency(src, dst, kind, at):
            if src is not None:
                local_edges.add((src, dst))
                all_edges.append({"source": scope + "/" + src, "target": scope + "/" + dst,
                                  "kind": kind, "at": at})

        for i, n in enumerate(nodes):
            p = pointer + "/" + str(i)
            name, op = n["id"], n["operator"]
            all_nodes.append({"id": scope + "/" + name, "logical_id": name, "scope": scope,
                              "position": i, "operator": op, "implementation": n["implementation"]})
            for port, ref in n["inputs"].items():
                at = p + "/inputs/" + port
                dependency(resolve(ref, at), name, "data", at)
            bindings = n.get("param_bindings", [])
            if type(bindings) is not list:
                fail("PARAMETER_BINDING_SHAPE", p, "array required")
            parameters = set()
            for j, binding in enumerate(bindings):
                at = p + "/param_bindings/" + str(j)
                obj(binding, {"parameter", "ref"}, {"field"}, at)
                parameter = ident(binding["parameter"], at + "/parameter")
                if parameter in parameters or parameter in n["params"]:
                    fail("PARAMETER_BINDING_CONFLICT", at, "one source per parameter")
                parameters.add(parameter)
                if "field" in binding:
                    nonempty(binding["field"], at + "/field")
                dependency(resolve(binding["ref"], at + "/ref"), name, "param_binding", at)
            after = n.get("after", [])
            if type(after) is not list or not all(type(x) is str for x in after) or len(after) != len(set(after)):
                fail("IR_SHAPE", p + "/after", "unique local-node ID array required")
            for j, before in enumerate(after):
                at = p + "/after/" + str(j)
                if before not in by_id:
                    fail("UNKNOWN_REFERENCE", at, "after must name a local node")
                dependency(before, name, "control", at)
            if op not in CONTROL_REGIONS:
                if "regions" in n:
                    fail("REGION_FORBIDDEN", p + "/regions", "only registered control operators own regions")
                continue
            regions = obj(n.get("regions"), CONTROL_REGIONS[op], set(), p + "/regions")
            for label in sorted(regions):
                rp = p + "/regions/" + label
                region = obj(regions[label], {"bindings", "nodes", "yield"}, set(), rp)
                bindings = region["bindings"]
                if type(bindings) is not dict:
                    fail("IR_SHAPE", rp + "/bindings", "explicit bindings object required")
                for alias, ref in bindings.items():
                    ident(alias, rp + "/bindings")
                    at = rp + "/bindings/" + alias
                    if ref == "$item" and op == "map" and label == "body":
                        continue
                    if ref == "$state" and op == "loop" and label == "body":
                        continue
                    dependency(resolve(ref, at), name, "region_binding", at)
                visit(region["nodes"], scope=scope + "/" + name + ":" + label,
                      pointer=rp + "/nodes", depth=depth + 1, bound=set(bindings),
                      yields=(region["yield"], rp + "/yield"), expected_yields=set(n["outputs"]))
        if yields is not None:
            y, yp = yields
            obj(y, expected_yields, set(), yp)
            for key, ref in y.items():
                resolve(ref, yp + "/" + key)
        incoming = {name: 0 for name in by_id}
        followers = {name: [] for name in by_id}
        for src, dst in local_edges:
            incoming[dst] += 1
            followers[src].append(dst)
        ready = [(positions[k], k) for k, degree in incoming.items() if degree == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            _, n = heapq.heappop(ready)
            order.append(n)
            for child in followers[n]:
                incoming[child] -= 1
                if incoming[child] == 0:
                    heapq.heappush(ready, (positions[child], child))
        if len(order) != len(nodes):
            fail("CYCLIC_DEPENDENCY", pointer, "data, control or binding dependency cycle")
        scopes.append({"scope": scope, "serialization_order": [n["id"] for n in nodes],
                       "analysis_topological_order": order})
        return resolve

    root_resolve = visit(plan["nodes"], scope="root", pointer="/nodes", depth=0, bound=set())
    if root_resolve(plan["result"], "/result") is None:
        fail("RESULT_REFERENCE", "/result", "result must be a produced node output")
    return {"status": "STRUCTURE_PASS", "profile": "SPEC001B_STRUCTURAL_FOUNDATION_0.1",
            "full_validation": False, "formal_ready": False,
            "canonical_plan_hash": digest(plan), "logical_node_count": total,
            "nodes": all_nodes, "dependency_edges": all_edges,
            "scopes": scopes, "pending_checks": list(PENDING)}


def analyze_bytes(raw: bytes, **kwargs) -> dict:
    report = analyze_structure(parse_ir_bytes(raw), **kwargs)
    return {**report, "raw_plan_hash": hashlib.sha256(raw).hexdigest()}
