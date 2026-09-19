"""Strict JSON and numeric primitives. No executable expressions or network I/O."""
import hashlib
import json
import math
from pathlib import Path

class ContractError(ValueError):
    def __init__(self, code: str, path: str, detail: str):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(f"{code} at {path}: {detail}")

def number(value, path: str, *, positive=False, integer=False):
    allowed = (int,) if integer else (int, float)
    if type(value) not in allowed or (type(value) is float and not math.isfinite(value)):
        raise ContractError("INVALID_NUMBER", path, "finite numeric value required; bool is not a number")
    if value < 0 or (positive and value == 0):
        raise ContractError("INVALID_NUMBER", path, "positive value required" if positive else "nonnegative value required")
    return value

def keys(value, required, optional, path):
    if not isinstance(value, dict):
        raise ContractError("OBJECT_REQUIRED", path, "expected an object")
    missing, extra = set(required)-value.keys(), value.keys()-set(required)-set(optional)
    if missing: raise ContractError("MISSING_FIELD", path, ",".join(sorted(missing)))
    if extra: raise ContractError("UNKNOWN_FIELD", path, ",".join(sorted(extra)))

def text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ContractError("STRING_REQUIRED", path, "nonempty string required")
    return value

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False).encode("utf8")

def digest(value): return hashlib.sha256(canonical(value)).hexdigest()

def load(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ContractError("DUPLICATE_JSON_KEY", "$", key)
            result[key]=value
        return result
    def bad(value): raise ContractError("INVALID_NUMBER", "$", value)
    try:
        return json.loads(Path(path).read_text(encoding="utf8"),object_pairs_hook=pairs,parse_constant=bad)
    except json.JSONDecodeError as exc:
        raise ContractError("INVALID_JSON", "$", f"line={exc.lineno}; column={exc.colno}") from exc

def write_new(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf8") as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write("\n")
