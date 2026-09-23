"""Capacity matching over compressed rows, with O(input rows) auxiliary memory.

Candidate edges are generated on demand, never stored as a quadratic matrix.
Only positive integer flows are retained, at most one per input occurrence.
Exact fields partition the graph; identical floating rows share capacity, but
are NOT greedily cancelled because tolerance neighborhoods can overlap.
"""
from collections import defaultdict, deque
from rcwg_full.evidence import canonical


def _shape(value):
    if type(value) is float: return ['float']
    if type(value) is dict: return ['dict', [[k, _shape(v)] for k, v in sorted(value.items())]]
    if type(value) is list: return ['list', [_shape(v) for v in value]]
    return [type(value).__name__, value]


def _groups(rows, partition):
    groups = defaultdict(dict)
    for row in rows:
        bucket = groups[canonical(partition(row))]
        key = canonical(row)
        if key not in bucket: bucket[key] = [row, 0]
        bucket[key][1] += 1
    return groups


def capacity_equal(actual, expected, equal, *, partition=_shape):
    left, right = _groups(actual, partition), _groups(expected, partition)
    if left.keys() != right.keys(): return False
    for key, values in left.items():
        a, b = list(values.values()), list(right[key].values())
        if sum(v[1] for v in a) != sum(v[1] for v in b): return False
        # Nonfinite floats cannot match even themselves.
        if len(a) == len(b) == 1:
            if not equal(a[0][0], b[0][0]): return False
            continue
        free = [v[1] for v in b]
        reverse = [dict() for _ in b]
        for start, (row, needed) in enumerate(a):
            while needed:
                queue = deque([start]); seen_left = {start}; via = {}; parent = {}
                end = None
                while queue and end is None:
                    i = queue.popleft()
                    for j, (wanted, _) in enumerate(b):
                        if j in parent or not equal(a[i][0], wanted): continue
                        parent[j] = i
                        if free[j]: end = j; break
                        for displaced in reverse[j]:
                            if displaced not in seen_left:
                                seen_left.add(displaced); via[displaced] = j; queue.append(displaced)
                if end is None: return False
                amount = min(needed, free[end]); j = end
                while parent[j] != start:
                    i = parent[j]; j = via[i]; amount = min(amount, reverse[j][i])
                free[end] -= amount; needed -= amount; j = end
                while True:
                    i = parent[j]; reverse[j][i] = reverse[j].get(i, 0) + amount
                    if i == start: break
                    j = via[i]; reverse[j][i] -= amount
                    if not reverse[j][i]: del reverse[j][i]
    return True
