"""Small deterministic serialization helpers; no network side effects."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents silently overwriting acceptance evidence.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
