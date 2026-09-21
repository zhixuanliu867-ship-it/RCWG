# FULL001 implementation decisions

The authoritative scope is RCWG-FULL-001/1.0.0, recorded in SPEC_IDENTITY.json.
This document records implementation choices, not experimental observations.

1. Work starts at 2824ee8e7678a39b3bff2ac701ffececd50d1e81 in an isolated
   rcwg/full-001 worktree. The original N4 worktree and its evidence remain intact.
2. COMPAT1 copies the small orchestration and structural-validation modules into
   a versioned package, reuses legacy type, expression, public-task and operator
   validation, and adds explicit dispatch for the supplemental forms. No global
   monkeypatching or change to old profile acceptance is permitted.
3. Parameter binding remains a dependency even if a node does not otherwise
   consume its source. Static type witnesses are internal to validation; actual
   bound values and ranges are checked in the worker. Shape, service identity,
   authority, storage and paths cannot be supplied by a value binding.
4. WSL has the target Python 3.12.14 but no C++ compiler. Native builds will use
   existing CI compilers. No system installer, live model/count request or host
   calibration is authorized by this decision.
5. All six completion states start false. Each requirement remains pending until
   its complete scope has actual evidence. Partial tests never pass a larger gate.

## COMPAT1 bounded state and relational template closure

The new profile uses versioned copies of the baseline static contracts and the original immutable Type class; source hashes are recorded in COMPAT_TYPE_SOURCES.json. Legacy files and tests remain unchanged. List requires an explicit max_length <= 4096, encoded in the typed graph and enforced on runtime values.

F1-08 uses explicit scalar ID-set union, a public canonical records lookup by semi-join, and source-ordinal deduplication before ranking. It does not equate arbitrary entity or document domains. F2-12 explicitly stream_reads the joined Table before materialization, preserving the registered Stream-to-materialize contract and metering that bridge.

Reference candidates vary actual algorithm choices and explicit stream/memory/disk nodes; alpha-renaming is deduplicated. Screening times do not enter T_ref. Formal cost coefficients remain untrained. Statistical hypotheses are a candidate version with 18 Holm-family tests, never a declaration of formal freeze.

## Graph closure and automatic retirement

F3 supplies graph-domain-preserving projections and explicit PathSet node/edge flattening with target and ordinal. Bellman-Ford and edge-scan oracles are independent of the execution kernels. C2/C3 audits reread the physical files for all F1-F3 siblings. Automatic retirement defers sealed owners while child views or leases exist; explicit release still rejects live aliases. The failed immutable 803-test run is retained, and all 24 affected candidate cases have separate successful rerun evidence. Formal gates remain closed.

## Streaming physical closure

Hash aggregation now owns per-group scalar accumulators rather than input Tables or ordinal vectors. Source scanning verifies bytes incrementally on the same open file before reading Arrow batches. Narrow projections record the full integrity-read bytes separately; no claim hides those reads. Actual Arrow types, nullability values and bounded nested values are checked before preparation, and the worker binds the public registry to manifest identities. Incremental disk materialization writes bounded IPC or Parquet batches and commits through the existing artifact seal path. Partial files remain evidence on failure. Group-state growth and other collecting algorithms still require resource tests; this checkpoint is not full software acceptance or formal capacity validation.
