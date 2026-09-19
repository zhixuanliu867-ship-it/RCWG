"""Owner-registered JSONL sources. Model references never become file paths."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from types import MappingProxyType
from rcwg_spec.public_task import validate_public_task
from rcwg_spec.typesystem import row_schema, unwrap_ref
from .errors import ExecFault
from .kernels import RowFrame

MAX_LINE = 1024 * 1024
SUPPORTED = {'Bool', 'Int64', 'Float64', 'Utf8'}

def _pairs(items):
    out = {}
    for key, value in items:
        if key in out: raise ExecFault('DATA_DUPLICATE_KEY')
        out[key] = value
    return out

def parse_line(line: bytes):
    def number(s):
        x = float(s)
        if not math.isfinite(x): raise ExecFault('DATA_NONFINITE')
        return x
    def bad(_): raise ExecFault('DATA_NONFINITE')
    try:
        return json.loads(line.decode('utf8'), object_pairs_hook=_pairs,
                          parse_float=number, parse_constant=bad)
    except (ValueError, UnicodeError, RecursionError):
        raise ExecFault('DATA_JSON_INVALID') from None

def field_valid(value, t):
    if t.kind == 'Nullable': return value is None or field_valid(value, t.item)
    if t.kind == 'Bool': return type(value) is bool
    if t.kind == 'Int64': return type(value) is int and -(2**63) <= value < 2**63
    if t.kind == 'Float64': return type(value) is float and math.isfinite(value)
    if t.kind == 'Utf8':
        if type(value) is not str: return False
        try: value.encode('utf8'); return True
        except UnicodeEncodeError: return False
    return False

from .files import open_regular


def _hash_file(path):
    h = hashlib.sha256()
    fd = open_regular(path)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise ExecFault('DATA_NOT_REGULAR')
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()

@dataclass(frozen=True)
class Entry:
    source_id: str
    path: Path
    expected_sha256: str
    revision: str
    schema: dict
    row_count: int | None
    schema_hash: str

class FileRegistry:
    """Constructed by a trusted runner, never from WorkIR-provided path text.

    Registration hashes actual file bytes. Each scan hashes exactly the bytes it
    consumed again before EOF success, so a mid-run mutation invalidates the run.
    Files remain private and source paths are not included in public diagnostics.
    """
    def __init__(self, task: dict, locations: dict[str, Path], *, allowed_root: Path):
        checked = validate_public_task(task)
        raw_root=Path(allowed_root).absolute()
        if any(p.is_symlink() for p in [raw_root,*raw_root.parents]):raise ExecFault('DATA_SYMLINK')
        try: root = Path(allowed_root).resolve(strict=True)
        except OSError: raise ExecFault('DATA_ROOT_UNAVAILABLE') from None
        sources = {x['id']: x for x in checked['source_manifest']}
        if set(locations) != set(sources): raise ExecFault('DATA_REGISTRY_IDS')
        self.entries = {}
        for ident, source in sources.items():
            p = Path(locations[ident])
            if any(part.is_symlink() for part in [p.absolute(),*p.absolute().parents]):raise ExecFault('DATA_SYMLINK')
            try: p = p.resolve(strict=True)
            except OSError: raise ExecFault('DATA_FILE_UNAVAILABLE') from None
            if not p.is_relative_to(root): raise ExecFault('DATA_OUTSIDE_ROOT')
            typ = unwrap_ref(checked['input_types'][ident])
            if typ.kind != 'Table': raise ExecFault('DATA_KIND_IMPLEMENTATION_GAP')
            schema = row_schema(typ, '')
            for t in schema.values():
                base = t.item if t.kind == 'Nullable' else t
                if base.kind not in SUPPORTED: raise ExecFault('DATA_TYPE_IMPLEMENTATION_GAP')
            expected = source.get('data_sha256');revision=source.get('revision')
            if not expected or not revision: raise ExecFault('SOURCE_IDENTITY_REQUIRED')
            if _hash_file(p) != expected: raise ExecFault('DATA_HASH_MISMATCH')
            public = next(x for x in checked['normalized_task']['datasets'] if x['id'] == ident)
            self.entries[ident] = Entry(ident,p,expected,revision,MappingProxyType(schema),
                public.get('stats',{}).get('row_count'),source['schema_hash'])
        self.allowed_root=root
        self.entries=MappingProxyType(self.entries)

    def manifest(self):
        return [{'id':e.source_id,'revision':e.revision,'content_sha256':e.expected_sha256,
                 'schema_hash':e.schema_hash} for e in sorted(self.entries.values(),key=lambda x:x.source_id)]

    def frames(self, ident, counters, tick):
        if ident not in self.entries: raise ExecFault('DATA_UNREGISTERED')
        e=self.entries[ident];h=hashlib.sha256();count=0
        fd=open_regular(e.path)
        with os.fdopen(fd,'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ExecFault('DATA_NOT_REGULAR')
            while True:
                tick();line=f.readline(MAX_LINE+1)
                if not line:break
                if len(line)>MAX_LINE:raise ExecFault('DATA_LINE_LIMIT')
                h.update(line)
                counters['source_read_bytes']=counters.get('source_read_bytes',0)+len(line)
                row=parse_line(line)
                if type(row) is not dict or set(row)!=set(e.schema):raise ExecFault('DATA_SCHEMA_MISMATCH')
                if any(not field_valid(row[k],t) for k,t in e.schema.items()):raise ExecFault('DATA_TYPE_MISMATCH')
                counters['rows_scanned']=counters.get('rows_scanned',0)+1
                yield RowFrame(MappingProxyType(row),count)
                count+=1
        if h.hexdigest()!=e.expected_sha256:raise ExecFault('DATA_CHANGED_DURING_RUN')
        if e.row_count is not None and count!=e.row_count:raise ExecFault('DATA_ROW_COUNT_MISMATCH')
        counters['source_eof_verified']=True
