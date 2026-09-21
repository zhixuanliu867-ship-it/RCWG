"""Schema-carrying SPEC-001B types; no implicit representation/numeric casts.

Bare legacy declarations are representation assertions only. They can never be
used as inferred types or supply missing public schemas.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import re

from rcwg_spec.common import ContractError


# Preserve the legacy immutable Type value class; parsing is profile-specific.
from rcwg_spec.typesystem import Type


SCALARS = frozenset({"Bool", "Int64", "Float64", "Utf8", "Date", "Timestamp"})
ALIASES = {"bool": "Bool", "int64": "Int64", "float64": "Float64",
           "utf8": "Utf8", "string": "Utf8", "date32": "Date",
           "timestamp_us": "Timestamp"}
ROWS = frozenset({"Record", "Table", "EvidenceTable", "Graph", "GraphView",
                  "EdgeStream", "DocumentIndex", "DocumentStream", "ChunkStream"})
DOMAIN_TYPES = frozenset({"Graph", "GraphView", "NodeSet", "EdgeStream", "PathSet",
                         "DocumentIndex", "DocumentStream", "ChunkStream", "IDSet",
                         "RankedIDSet", "EvidenceTable"})
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}\Z")


def pointer(path, field_name):
    return path.rstrip("/") + "/" + str(field_name).replace("~", "~0").replace("/", "~1")


def _fail(path, detail="incompatible or incomplete type"):
    raise ContractError("TYPE_MISMATCH", path, detail)


def _closed(value, required, optional, path):
    if type(value) is not dict:
        _fail(path, "type descriptor must be an object")
    if not required <= value.keys() or value.keys() - required - optional:
        _fail(path, "missing or unknown type descriptor fields")


def parse_schema(mapping, path="/schema") -> dict[str, Type]:
    if type(mapping) is not dict or not mapping:
        _fail(path, "nonempty field schema required")
    result = {}
    for name, descriptor in mapping.items():
        if type(name) is not str or not IDENT.fullmatch(name):
            _fail(path, "invalid field identifier")
        result[name] = parse_type(descriptor, pointer(path, name))
    return result


def parse_type(spec, path="/type") -> Type:
    return _parse(spec, path, 0)


def _parse(spec, path, depth):
    if depth > 24:
        _fail(path, "type descriptor nesting limit exceeded")
    if type(spec) is str:
        kind = ALIASES.get(spec, spec)
        if kind in SCALARS or kind in {"ControlToken", "Result", "Stats"}:
            return Type(kind)
        match = re.fullmatch(r"(Nullable|Set|DatasetRef|ArtifactRef|Stream)\[(.+)\]", spec)
        if match:
            item = _parse(match[2], path, depth + 1)
            return _container(match[1], item, path)
        _fail(path, "unknown type or missing concrete schema")
    if type(spec) is not dict:
        _fail(path, "string or object type descriptor required")
    if "type" in spec:
        _closed(spec, {"type"}, {"nullable"}, path)
        base = _parse(spec["type"], pointer(path, "type"), depth + 1)
        nullable = spec.get("nullable", False)
        if type(nullable) is not bool:
            _fail(pointer(path, "nullable"), "nullable must be boolean")
        return _container("Nullable", base, path) if nullable else base
    kind = spec.get("kind")
    if type(kind) is not str:
        _fail(path, "kind must name a concrete type")
    kind = ALIASES.get(kind, kind)
    if kind in SCALARS or kind in {"ControlToken", "Result", "Stats"}:
        _closed(spec, {"kind"}, set(), path)
        return Type(kind)
    if kind in {"Nullable", "Set", "DatasetRef", "ArtifactRef", "Stream"}:
        _closed(spec, {"kind", "item"}, {"domain", "revision"} if kind != "Nullable" else set(), path)
        result = _container(kind, _parse(spec["item"], pointer(path, "item"), depth + 1), path)
        if kind != "Nullable":
            _identity(spec, path, required=False)
            result = replace(result, domain=spec.get("domain"), revision=spec.get("revision"))
        return result
    if kind == "List":
        _closed(spec, {"kind", "item", "max_length"}, set(), path)
        bound=spec["max_length"]
        if type(bound) is not int or not 0 <= bound <= 4096:
            _fail(path, "List requires an explicit bound between zero and 4096")
        item=_parse(spec["item"], pointer(path, "item"), depth+1)
        return Type("List", item=item, metadata={"max_length":bound})
    if kind == "Union":
        _closed(spec, {"kind", "members"}, set(), path)
        if type(spec["members"]) is not list or not 2 <= len(spec["members"]) <= 16:
            _fail(path, "union needs two to sixteen distinct explicit members")
        members = tuple(_parse(x, pointer(pointer(path, "members"), i), depth + 1)
                        for i, x in enumerate(spec["members"]))
        if any(x.kind == "Union" for x in members):
            _fail(path, "nested unions must be explicitly flattened")
        for i, member in enumerate(members):
            if any(same_type(member, other) for other in members[:i]):
                _fail(path, "duplicate union member")
        return Type("Union", members=members)
    if kind in ROWS:
        identity = {"domain", "revision"} if kind in DOMAIN_TYPES else set()
        _closed(spec, {"kind", "schema"} | identity, {"domain", "revision"} - identity, path)
        _identity(spec, path, required=bool(identity))
        # Keep depth bounded even for Record nested in Record.
        raw = spec["schema"]
        if type(raw) is not dict or not raw:
            _fail(pointer(path, "schema"), "nonempty field schema required")
        schema = []
        for name, descriptor in raw.items():
            if type(name) is not str or not IDENT.fullmatch(name):
                _fail(pointer(path, "schema"), "invalid field identifier")
            schema.append((name, _parse(descriptor, pointer(pointer(path, "schema"), name), depth + 1)))
        return Type(kind, tuple(schema), domain=spec.get("domain"), revision=spec.get("revision"))
    if kind in {"NodeSet", "PathSet", "IDSet", "RankedIDSet"}:
        _closed(spec, {"kind", "item", "domain", "revision"}, set(), path)
        _identity(spec, path, required=True)
        item = _parse(spec["item"], pointer(path, "item"), depth + 1)
        if item.kind not in {"Int64", "Utf8"}:
            _fail(path, "ID domain requires Int64 or Utf8 IDs")
        return Type(kind, item=item, domain=spec["domain"], revision=spec["revision"])
    _fail(path, "unknown concrete type")


def _identity(spec, path, *, required):
    for name in ("domain", "revision"):
        if (required or name in spec) and (type(spec.get(name)) is not str or not spec[name].strip()):
            _fail(pointer(path, name), "nonempty domain/revision identity required")
    if "domain" in spec and "revision" not in spec:
        _fail(path, "a domain requires an explicit revision")


def _container(kind, item, path):
    if kind == "Stream" and item.kind != "Record":
        _fail(path, "Stream item must be a concrete Record")
    if kind == "Nullable" and item.kind in {"Nullable", "ControlToken"}:
        _fail(path, "invalid nullable inner type")
    return Type(kind, item=item)


def unwrap_ref(t: Type) -> Type:
    while t.kind in {"DatasetRef", "ArtifactRef"} and t.item is not None:
        t = t.item
    return t


def row_schema(t: Type, path="/type") -> dict[str, Type]:
    # References must be explicitly unwrapped by the operator that consumes them.
    if t.kind == "Stream" and t.item is not None and t.item.kind == "Record":
        return dict(t.item.schema)
    if t.kind in ROWS and t.schema:
        return dict(t.schema)
    _fail(path, "a concrete row-bearing value is required")


def with_rows(t: Type, schema) -> Type:
    fields = tuple(schema.items()) if isinstance(schema, dict) else tuple(schema)
    if t.kind == "Stream" and t.item is not None and t.item.kind == "Record":
        return replace(t, item=replace(t.item, schema=fields))
    if t.kind in ROWS:
        return replace(t, schema=fields)
    _fail("/type", "cannot attach row schema to this representation")


def same_type(a: Type, b: Type) -> bool:
    if not isinstance(a, Type) or not isinstance(b, Type):
        return False
    if (a.kind, a.domain, a.revision) != (b.kind, b.domain, b.revision):
        return False
    if bool(a.item is None) != bool(b.item is None):
        return False
    if a.item is not None and not same_type(a.item, b.item):
        return False
    if a.kind == "List" and a.metadata.get("max_length") != b.metadata.get("max_length"):
        return False
    # Schema object order is not a field/type distinction. Traversal order is a
    # separate runtime obligation and cannot be inferred from JSON key order.
    if set(dict(a.schema)) != set(dict(b.schema)):
        return False
    if any(not same_type(t, dict(b.schema)[name]) for name, t in a.schema):
        return False
    if a.kind in {"Table", "Stream", "Record", "EvidenceTable"} and _mapping_identity(a) != _mapping_identity(b):
        return False
    if a.kind == "Union":
        return len(a.members) == len(b.members) and all(any(same_type(x, y) for y in b.members) for x in a.members)
    if a.kind in {"Graph", "GraphView"}:
        for key in ("directed", "node_id_type", "node_schema"):
            if key in a.metadata and key in b.metadata and a.metadata[key] != b.metadata[key]:
                return False
    return True


def _mapping_identity(t):
    """Document-ID mappings are semantic capabilities, not mere estimates.

    A branch/loop cannot promote untagged or differently tagged text to IDs in
    the selected document corpus by inheriting another arm's metadata.
    """
    mappings = t.metadata.get("id_mappings")
    if mappings is None:
        if t.metadata.get("id_field") and t.metadata.get("id_domain"):
            mappings = [{"field": t.metadata["id_field"], "domain": t.metadata["id_domain"],
                         "revision": t.metadata.get("id_revision", t.revision)}]
        else:
            mappings = []
    return frozenset((m.get("field"), m.get("domain"), m.get("revision")) for m in mappings)


def merge_types(a: Type, b: Type, path="/type") -> Type:
    if same_type(a, b):
        return a
    if a.kind == "Nullable" and a.item is not None and same_type(a.item, b):
        return a
    if b.kind == "Nullable" and b.item is not None and same_type(b.item, a):
        return b
    if a.kind == "Union" and any(same_type(x, b) for x in a.members):
        return a
    if b.kind == "Union" and any(same_type(x, a) for x in b.members):
        return b
    if a.kind == b.kind == "Union":
        if all(any(same_type(x, y) for y in a.members) for x in b.members):
            return a
        if all(any(same_type(x, y) for y in b.members) for x in a.members):
            return b
    # Row fields may acquire explicit nullability; representation/domain and the
    # complete field set must stay fixed. No guessed columns or numeric widening.
    if (a.kind, a.domain, a.revision) == (b.kind, b.domain, b.revision):
        if a.kind == "Stream" and a.item and b.item:
            if _mapping_identity(a) != _mapping_identity(b):
                _fail(path, "branch document-ID mapping capabilities must agree")
            return replace(a, item=merge_types(a.item, b.item, pointer(path, "item")))
        if a.kind in {"Record", "Table", "EvidenceTable"} and set(dict(a.schema)) == set(dict(b.schema)):
            if _mapping_identity(a) != _mapping_identity(b):
                _fail(path, "branch document-ID mapping capabilities must agree")
            return replace(a, schema=tuple((name, merge_types(t, dict(b.schema)[name], pointer(path, name)))
                                            for name, t in a.schema))
    _fail(path, "branch types require the same schema/domain or an explicit nullable/union alternative")


def check_declared(actual: Type, declaration, path="/type"):
    if type(declaration) is str:
        bare = {"Record", "Table", "Graph", "GraphView", "NodeSet", "EdgeStream", "PathSet",
                "DocumentIndex", "DocumentStream", "ChunkStream", "EvidenceTable", "IDSet",
                "RankedIDSet", "Set", "Stream", "DatasetRef", "ArtifactRef", "Result", "Stats", "ControlToken"}
        if declaration in bare:
            if actual.kind != declaration:
                _fail(path, "declared representation differs from inferred output")
            return
        if declaration == "Stream[Record]":
            if actual.kind != "Stream" or actual.item is None or actual.item.kind != "Record":
                _fail(path, "declared representation differs from inferred output")
            return
        # Preserve legacy Ref spelling while recursively checking its target.
        match = re.fullmatch(r"(DatasetRef|ArtifactRef)\[(.+)\]", declaration)
        if match:
            if actual.kind != match[1] or actual.item is None:
                _fail(path)
            return check_declared(actual.item, match[2], path)
    expected = parse_type(declaration, path)
    if not _assignable(actual, expected):
        _fail(path, "declared concrete type differs from inferred output")


def _assignable(actual, expected):
    if same_type(actual, expected):
        return True
    if actual.kind == expected.kind == "List":
        return actual.metadata.get("max_length", 4097) <= expected.metadata["max_length"] and _assignable(actual.item, expected.item)
    if expected.kind == "Nullable" and expected.item is not None:
        if actual.kind == "Nullable" and actual.item is not None:
            return _assignable(actual.item, expected.item)
        return _assignable(actual, expected.item)
    if expected.kind == "Union":
        members = actual.members if actual.kind == "Union" else (actual,)
        return all(any(_assignable(member, branch) for branch in expected.members) for member in members)
    if (actual.kind, actual.domain, actual.revision) != (expected.kind, expected.domain, expected.revision):
        return False
    if actual.kind in {"Record", "Table", "EvidenceTable"}:
        return set(dict(actual.schema)) == set(dict(expected.schema)) and all(
            _assignable(t, dict(expected.schema)[name]) for name, t in actual.schema)
    if actual.kind in {"Stream", "ArtifactRef", "DatasetRef"} and actual.item is not None and expected.item is not None:
        return _assignable(actual.item, expected.item)
    return False


def type_json(t: Type) -> dict:
    result = {"kind": t.kind}
    if t.schema:
        result["schema"] = {name: type_json(value) for name, value in t.schema}
    if t.item is not None:
        result["item"] = type_json(t.item)
    if t.domain is not None:
        result["domain"] = t.domain
    if t.revision is not None:
        result["revision"] = t.revision
    if t.members:
        result["members"] = [type_json(x) for x in t.members]
    if t.kind == "List":
        result["max_length"] = t.metadata.get("max_length",4096)
    # Other metadata (estimates, indexes, lifecycle handles) is not a type declaration.
    return result
