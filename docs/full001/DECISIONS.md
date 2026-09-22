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

## F4 typed plans and build-mode isolation

All twelve F4 baseline plans compile and have one actual native tiny run with an independent oracle. Full base/condition and variant execution remains pending. Stream fanout has an explicit COMPAT1 contract yielding one bounded single-pass stream per consumer. The reference grammar v2 retains prior choices first and adds actual scan-batch sizes 16/31 when needed for eight distinct choices; it remains unfrozen. Streaming aggregation state is module-local so diagnostic and performance builds coexist without a pybind type registration conflict. Legacy scalar aliases are normalized through the versioned parser before Arrow validation.

## Document runtime closure and independent allocation floor

The 1319-test run had exactly one failed assertion: Arrow pool memory was zero after input release, whereas the pre-GC baseline was 110720 bytes from unreachable objects of earlier tests. The test now collects those objects before taking its baseline; weak-reference death and exact allocated-byte equality checks remain. F4 template and candidate runs passed in that run.

The document adapter only presents fields explicitly read or contexts explicitly gathered. Response fields are type-checked and citations must be covered by the supplied canonical context segments. Identical facts merge unique citations; conflicting facts remain distinct. BM25 builds/scoring and nested Arrow list/struct payload reconstruction have new native implementations awaiting integration. The worker selects document sources by domain/revision and loads only an explicitly supplied engineering replay manifest whose hash is in the runner context. The COMPAT1 context adapter preserves the original RunnerContext, expected-manifest and seal implementation; only public type validation is versioned, with the inherited function body hash recorded. No new paid service or authority is introduced.

## F5 request-bound replay and independent intermediate evidence

F5 now has twelve distinct executable plans: typed multi-field extraction, cross-section and boundary recovery, unit conversion via a public Arrow join, section disambiguation, duplicate evidence union, unknown/refuted separation, entity deduplication and aggregate, declared version priority, shared queries, and extractive context selection. Source-language expectations are parsed by a verifier that imports no runtime, compiler or replay. Private semantic_response events preserve intermediate rows for verification when final arithmetic omits citations. The fixed service responses are explicitly engineering recordings and cannot claim real semantic service readiness. Grammar 3 adds explicit document caches and sharing choices while keeping original algorithm decisions separate. Native BM25, nested payloads and allocation baseline now pass current CI; four document worker setup failures were repaired and all four pass local source-frozen testing. Formal gates remain closed.

## F6 graph-text closure

All twelve mixed template plans now execute through actual graph kernels, explicit domain/revision ID mapping, document reads, fixed engineering semantic responses and independent verification. The first 96 candidate executions passed. Node-domain capabilities are preserved through supported join projections and checked during branch type merging; ordinary integer fields do not acquire graph membership. Shared mapping streams are explicitly materialized before reuse. The all-source CI at e1aa305 passed 1588 tests, including every F5 tiny case and eight actual candidates per template. The final 240 F6 instances and broader integration remain pending. No formal readiness state changed.

## Native temporal values

Date uses Arrow date32 and Timestamp uses UTC microseconds. Internal scalar tags preserve these types through equality, ordering, joins, grouping, projection and bounded region evaluation; Utf8 remains literal text. JSON boundaries emit ISO dates and explicit UTC timestamps. Equivalent timestamp offsets share a native key. Native changes and new differential tests require a new source-bound build. The prior immutable cbd55f6 CI passed all 1855 existing tests, including 1440 tiny template instances. This does not close remaining software or formal gates.

## Actual source validation and graph field bindings

Source validation recomputes canonical logical content from actual JSON or incremental Arrow batches. A physical rehash cannot legitimize a stale logical-content claim. Public counts, actual scalar/record types, graph endpoint membership, identities, weight facts, index permutation/order and duplicate set IDs are checked independently. All 72 base-zero four-condition groups passed this audit (288 instances); the exact source remained unchanged.

Graph native kernels bind public node_id_field/source_field/target_field rather than assuming physical column names. For graph_filter, bare and edge-prefixed fields name the current edge. The complete predicate is evaluated with node-prefixed fields bound to each endpoint, and must be true at both endpoints; null fails. This is a vertex-preserving edge view, including depth-zero vertices. Explicit node removal uses graph_subgraph induced. The compiler records these endpoint bindings as an obligation. Filtered edge constraints flow to subsequent kernels. Historical graphs without edge IDs may traverse, but path witnesses and explicit edge selection require stable edge_id instead of inventing IDs. New native tests await the next build.

The previous 00d5aca CI passed all 1863 tests, including typed temporal offset equivalence, native joins and aggregates, nested projection and scan-map-disk JSON roundtrip. Formal readiness is unchanged.

## Recovery, durable execution and closed service identities

The recovered source is a continuation of the same FULL001 task. The inaccessible historical WSL worktree is preserved and its bundle plus uncommitted FULL001 files were recovered into a local isolated checkout. The exact baseline remains 2824ee8e7678a39b3bff2ac701ffececd50d1e81. Local tests use Windows Python 3.13.4 only as supplementary evidence; target acceptance requires Linux Python 3.12.14 and a current source-bound native build.

All eight service slots have explicit provider/account/region/model/capability/template/pricing identities. Existing API001, Windows and CLOUD001 transports are reused without login or authority changes. No provider idempotency header is invented. A durable request ID is bound before budget admission and sending; uncertain sends do not auto-retry. COUNT and thinking billing bounds must be explicit, and configured reservations must cover the request upper bound. A cancelled semantic worker leaves any in-flight request index open until response evidence is persisted; unresolved requests prevent seal. This does not establish actual provider capability or service readiness.

Campaign order is derived only from predeclared slots, with paired protocol ordering and dependency sorting. E2/E3/E4/E7 depend on exact primary generation IDs; this repairs the unfrozen planning implementation without changing target counts. E3 logical guidance sends one physical P1 request from public task guidance. E5 injected result/journal artifacts are separate from original native evidence. Claimed or uncertain work requires reconciliation and does not expire into duplicate execution.

The control outbox calls the actual runner for selected frozen slots, waits for prerequisites, records cancel-before-launch without a physical attempt, and preserves a crash claim. Trusted middleware supplies actor roles. Raw verification and metric payloads remain private until the complete package has an explicit Auditor release. Private seals include raw attempt outputs, worker logs, service request/response files and consistent SQLite snapshots; original sources remain unchanged. Source datasets and build binaries retain separate frozen artifact identities, explicitly declared in the sealed scope.

The latest supplementary cohort passed 331 tests, with zero skips. Earlier failures and all prior successful results are retained. Requirement mappings are PARTIAL wherever a supplementary cohort covers only part of a requirement. The total dispatcher produced an actual BLOCKED report, not a software acceptance pass. Formal builders, true bounded external merge, remaining memory accounting and exact-source native integration are still outstanding software obligations.
