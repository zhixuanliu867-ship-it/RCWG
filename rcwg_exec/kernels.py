"""Actual Python reference kernels. Algorithm choice is never auto-replaced.

Counters count this implementation's operations, not hardware instructions.
RowFrame ordinal makes equal ordering keys deterministic without comparing dicts.
"""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cmp_to_key
import heapq
from itertools import islice
import math
from types import MappingProxyType
from .errors import ExecFault

@dataclass(frozen=True, slots=True)
class RowFrame:
    values: Mapping
    ordinal: int

class ProjectedRow(Mapping):
    """A read-only column view retaining the original mapping (no row copy)."""
    __slots__ = ('base', 'columns')
    def __init__(self, base: Mapping, columns):
        self.base, self.columns = base, tuple(columns)
    def __len__(self): return len(self.columns)
    def __iter__(self): return iter(self.columns)
    def __getitem__(self, key):
        if key not in self.columns: raise KeyError(key)
        return self.base[key]


def _finite(value):
    if type(value) is int and not -(2**63) <= value < 2**63:
        raise ExecFault('ARITHMETIC_OVERFLOW', 'plan')
    if type(value) is float and not math.isfinite(value):
        raise ExecFault('ARITHMETIC_OVERFLOW', 'plan')
    return value


def evaluate(ast: dict, row: Mapping):
    """Finite AST interpreter after static validation; no eval/exec.

    Boolean junctions evaluate operands in source order. All operands are
    evaluated, so arithmetic failure is not suppressed by an optimizer.
    This policy is versioned with the reference runtime.
    """
    if 'field' in ast: return row[ast['field']]
    if 'literal' in ast: return ast['literal']
    op = ast['op']
    if op in ('and', 'or'):
        vals = [evaluate(x, row) for x in ast['args']]
        if op == 'and':
            return False if any(v is False for v in vals) else None if any(v is None for v in vals) else True
        return True if any(v is True for v in vals) else None if any(v is None for v in vals) else False
    if op in ('not', 'is_null', 'count'):
        v = evaluate(ast['arg'], row)
        if op == 'is_null': return v is None
        if op == 'not': return None if v is None else not v
        return None if v is None else _finite(len(v))
    a, b = evaluate(ast['left'], row), evaluate(ast['right'], row)
    if op == 'in':
        if b == []: return False
        if a is None or b is None: return None
        if any(v is not None and a == v for v in b): return True
        return None if any(v is None for v in b) else False
    if a is None or b is None: return None
    if op == 'eq': return a == b
    if op == 'ne': return a != b
    if op == 'lt': return a < b
    if op == 'le': return a <= b
    if op == 'gt': return a > b
    if op == 'ge': return a >= b
    if op == 'add': return _finite(a + b)
    if op == 'sub': return _finite(a - b)
    if op == 'mul': return _finite(a * b)
    if op == 'div':
        if b == 0: raise ExecFault('DIVISION_BY_ZERO', 'plan')
        return _finite(a / b)
    raise ExecFault('PREDICATE_IMPLEMENTATION_GAP')


def filter_rows(rows, predicate, counters, tick):
    for frame in rows:
        tick(); counters['predicate_evaluations'] = counters.get('predicate_evaluations', 0) + 1
        if evaluate(predicate, frame.values) is True: yield frame



def filter_batch_rows(rows, predicate, counters, tick, *, batch_rows=128):
    """Bounded batch/mask reference semantics; native SIMD is not claimed."""
    iterator=iter(rows)
    while True:
        batch=list(islice(iterator,batch_rows))
        if not batch:break
        tick();counters['vector_batches']=counters.get('vector_batches',0)+1
        counters['batch_frames_peak']=max(counters.get('batch_frames_peak',0),len(batch))
        mask=[]
        for frame in batch:
            tick();counters['predicate_evaluations']=counters.get('predicate_evaluations',0)+1
            mask.append(evaluate(predicate,frame.values) is True)
        for frame,keep in zip(batch,mask):
            if keep:yield frame


def project_rows(rows, columns, implementation, counters, tick):
    for frame in rows:
        tick()
        if implementation == 'column_view':
            values = ProjectedRow(frame.values, columns)
            counters['row_views_created'] = counters.get('row_views_created', 0) + 1
        else:
            values = MappingProxyType({key: frame.values[key] for key in columns})
            counters['row_mappings_copied'] = counters.get('row_mappings_copied', 0) + 1
        yield RowFrame(values, frame.ordinal)

class Ordering:
    def __init__(self, keys, counters, tick):
        self.keys, self.counters, self.tick = keys, counters, tick
    def compare(self, a: RowFrame, b: RowFrame):
        self.tick(); c = self.counters
        c['ordering_comparisons'] = c.get('ordering_comparisons', 0) + 1
        for key in self.keys:
            x, y = a.values[key['field']], b.values[key['field']]
            c['key_comparisons'] = c.get('key_comparisons', 0) + 1
            if x is None or y is None:
                if x is y: continue
                first = key.get('nulls') == 'first'
                return (-1 if first else 1) if x is None else (1 if first else -1)
            if x != y:
                result = -1 if x < y else 1
                return result if key['direction'] == 'asc' else -result
        return (a.ordinal > b.ordinal) - (a.ordinal < b.ordinal)

class _WorstFirst:
    __slots__ = ('frame', 'order')
    def __init__(self, frame, order): self.frame, self.order = frame, order
    def __lt__(self, other): return self.order.compare(self.frame, other.frame) > 0


def select_topk(rows, k, keys, implementation, counters, tick, *, max_materialized_rows=100000):
    order = Ordering(keys, counters, tick)
    if implementation == 'full_sort':
        materialized = []
        for frame in rows:
            tick()
            if len(materialized) >= max_materialized_rows:
                raise ExecFault('REFERENCE_MATERIALIZATION_CAP')
            materialized.append(frame)
            counters['input_rows'] = counters.get('input_rows', 0) + 1
        counters['candidate_frames_peak'] = len(materialized)
        result = sorted(materialized, key=cmp_to_key(order.compare))[:k]
        counters['full_sort_calls'] = 1
    elif implementation == 'streaming_heap':
        if k > max_materialized_rows: raise ExecFault('REFERENCE_MATERIALIZATION_CAP')
        heap = []
        for frame in rows:
            tick(); counters['input_rows'] = counters.get('input_rows', 0) + 1
            if k == 0: continue  # Still drain/validate the declared source.
            if len(heap) < k:
                heapq.heappush(heap, _WorstFirst(frame, order))
                counters['heap_pushes'] = counters.get('heap_pushes', 0) + 1
            elif order.compare(frame, heap[0].frame) < 0:
                heapq.heapreplace(heap, _WorstFirst(frame, order))
                counters['heap_replacements'] = counters.get('heap_replacements', 0) + 1
        counters['candidate_frames_peak'] = len(heap)
        result = sorted((e.frame for e in heap), key=cmp_to_key(order.compare))
        counters['heap_selection_calls'] = 1
    else:
        raise ExecFault('KERNEL_IMPLEMENTATION_GAP')
    counters['output_rows'] = len(result)
    return result
