# SPEC-001B public TaskInput and type interface

This is an implementation clarification under the approved SPEC-001B decisions.
The protected TaskInput example and all original templates remain unchanged.
`validate_task` retains SPEC-001A's limited legacy F1 behavior;
`validate_public_task` validates the full public interface below.

## Public boundary and return values

Top-level required keys are `task_id`, `instruction`, `datasets`, `resources`,
`output_contract`, and `tool_catalog_id`. Optional keys are `notes` and
`information_level` (`I0`, `I1`, `I2`). Task family, split, stratum, gold, oracle,
reference plans and verifier feedback are not generator inputs. F1--F6 fixture
labels live in filenames/test metadata. The public task ID remains an opaque ID;
the compiler does not infer private stratification from its spelling.

Every object uses a closed schema. Unknown/private fields are rejected with
`PUBLIC_FIELD_VIOLATION` and a parent JSON Pointer; diagnostic text does not echo
unknown key names or values. Cyclic/non-JSON values, invalid Unicode, non-finite
numbers, integers outside Int64, excessive nesting/size and malformed descriptors
receive structured errors. This validates a supplied public schema boundary; it
does not certify arbitrary natural-language text as free of private information.
No data file, path, URL, provider, gold package or network is opened by this API.

The result includes `normalized_task`, `input_types` (source ID to Type), original
`task_input_hash`, `normalized_input_hash`, `source_manifest` and `readiness`.
The original object is not mutated. Normalization adds legacy `kind=table` and
canonical output schema descriptors; it does not invent data revisions or hashes.
The source manifest has `id`, `kind`, `revision`, `schema_source`, `data_sha256`,
and the actual `schema_hash`. Unavailable legacy identities are null. Declared
hashes are checked syntactically and bound later to trusted expected manifests;
their presence does not claim that actual data was read or execution occurred.

## Dataset tagged union

Every explicitly tagged dataset requires `id` (`dataset:` identity), `kind`,
`revision`, and `schema_source`; `data_sha256` is optional for offline engineering
but missing content identity appears as a freeze-readiness blocker. No example
fabricates a data content hash. A legacy untagged table can omit revision/source;
the omission is reported, not silently replaced by an identity derived from its ID.

| kind | Required additional fields | Inferred binding |
|---|---|---|
| table | schema, stats.row_count | DatasetRef[Table[S]] |
| graph | edge_schema, node_schema, node_id_type, domain, directed, stats.node_count/edge_count | Graph[G] |
| document_index | schema, id_type, domain, stats.document_count, indexes | DocumentIndex[D] |
| node_set | id_type, domain, stats.item_count | NodeSet[G] |
| edge_stream | schema, domain, stats.edge_count | EdgeStream[G] |
| id_selection | id_type, domain, ranked, stats.item_count | IDSet[D] or RankedIDSet[D] |
| scalar | type; optional correctly typed public value | Bool/Int64/etc. or Nullable scalar |
| record | schema | Record[S] |
| set | item_type, stats.item_count; optional domain | Set[T] |

The scalar/record/set source tags complete composition of already approved branch
conditions, loop state and set operators. They introduce no new operator or kernel.
Source revision remains in the source manifest even for scalar values. Scalar
runtime value identity is distinct from the value's structural type. Date literals
use ISO dates; timestamp literals include a timezone. Bool is not Int64 and Int64
is not Float64; this interface does not coerce values.

Graph node IDs are Int64 or Utf8. `node_id_field`, `source_field`, `target_field`
optionally override `id`, `source`, `target`; all mapped fields must have the same
declared node ID type. Optional `weight_field` selects a nonnullable numeric edge
field. Optional `weight_nonnegative`/`weight_equal` are public boolean facts used
as preconditions, not measured runtime observations. Document indices optionally
override `id_field=id`, which must agree with `id_type`.

Tables may declare `id_domain` and `id_field` together. This explicit mapping is
the only bridge from a single-column table to document selection; graph IDs do
not become document IDs because their primitive types happen to match. Operators
must check domain/revision at each graph/document join or selection boundary.

Tables, graphs and document indices may have public index records with exact keys
`id`, `kind`, `fields`, `revision`, `source` and optional `model_id`. Supported kinds
are range/hash/sorted/csr/adjacency/bm25/dense_fixed. Fields must exist and index
revision must equal the declared data revision. Dense indices require model_id.
Estimated counts/bytes remain estimates in metadata, never resource measurements.

## Public output tagged union

Output contracts require `type` and `mode` (exact or evidence_supported). New
contracts require `id`; legacy exact ordered_records supports the established
`exact_ordered_topk_v1` name. Row outputs (ordered_records, records, evidence,
record) have a concrete schema and/or fields. An omitted schema may only be
inferred when each selected field has one unambiguous public source type. New
aggregate/extraction fields therefore need an explicit output schema.

ordered_records additionally requires nonnegative `k` and an emitted tie_breaker.
evidence requires document domain/revision. paths requires graph domain/revision.
node_set/id_set require domain/revision/item_type (Int64 or Utf8). set requires
item_type. scalar requires scalar value_type. Fields belonging to another output
tag are rejected. Static emit checks type/schema/domain; exact result contents,
ordering, ties, completeness and evidence truth stay with the independent verifier.

## Type implementation

`Type` is an immutable dataclass with `kind`, schema tuple, `item`, `domain`,
`revision`, metadata and explicit union `members`. Metadata includes index and
source identities, graph node schema/ID type/direction, document ID type and
statistics; it does not replace the concrete schema. Public descriptor kinds
include scalar aliases, Nullable, Record, Table, Stream[Record], Set, DatasetRef,
ArtifactRef, the graph/document types and an explicit Union member list.

`same_type` compares full representation, field names/types, nullable, domain and
revision. Document-ID mapping capabilities (field, document domain, document
revision) are also semantic type constraints. Branches with different mappings
cannot inherit one arm's mapping; loops cannot discard/change the mapping and
claim an unchanged state type. These checks use normalized `id_mappings` or the
equivalent source `id_field`/`id_domain` metadata. Schema JSON object key order is immaterial; actual traversal/order
obligations remain separate. Graph metadata contradictions are also rejected.
`merge_types` permits equal types, explicit nullable joins and listed union
alternatives. It does not infer numeric widening, missing columns or a new union.
Stream and Table remain different; reading/materializing requires explicit nodes.

Legacy output strings such as Table and Stream[Record] are accepted only by
`check_declared` after inference. They constrain representation and cannot supply
missing fields or turn invalid schemas into Any. Ref targets are recursively
checked, and `row_schema` does not implicitly unwrap a reference. Compiler and
operators must select the explicit reference-consuming interface.

Actual regression methods are in tests/test_spec001b_types.py and
tests/test_spec001b_inputs.py. Each of six public examples has a separate valid,
invalid and random-canary privacy method. Public input/type tests are static
engineering evidence and do not open runtime, model, cloud or formal gates.
