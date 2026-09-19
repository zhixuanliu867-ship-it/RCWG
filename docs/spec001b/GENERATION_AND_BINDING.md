# SPEC-001B generation and evidence interfaces

Implemented scope: offline message assembly, strict response parsing, private
response archiving, runner-owned identity snapshots, expected records, and event
and reference sidecar validation. These interfaces do not make model requests,
execute operators, verify semantic answers, measure resources, or enable formal
experiments. All fixtures are BOOT_ONLY and all returned `formal_ready` flags are
false. An `EVIDENCE_BOUND` result says the supplied records agree with their
pre-execution identities; it does not certify that a worker enforced its config.

## Generation API

`rcwg_spec.generation.build_request(task, *, protocol, stage,
generation_attempt_id, request_id, logical_contract=None, capabilities=None,
token_counter=None, tokenizer_id=None)` validates the public TaskInput and returns
an inspectable mock-provider payload plus its exact serialized text and SHA256.
It reads only repository-owned source prompts/catalog/schema/example/addendum;
there is no private bundle, gold path, arbitrary catalog path, or network input.
Source bytes are hashed separately and never rewritten. Template substitution
uses one pass so placeholder text inside a public instruction stays literal.
An independently hashed compact planning supplement exposes the approved
SPEC001B worklist's ports, parameters and constraints. Historical status labels
stay in their original source file and are not presented as executable validation;
the compiler's current registry remains the authority for that separate gate.

P0 has a single `physical` request with 16,384 output tokens. P1 uses `logical`
(4,096) then `physical` (12,288), distinct request IDs, and one shared
`generation_attempt_id`. These stages are not two plan-generation attempts.
Transport retry, regeneration, and execution-repeat fields are separate; this
mock path retries neither invalid responses nor failed logical contracts.

The logical contract has exactly these seven fields, each an array of nonempty
strings: `required_outputs`, `hard_constraints`, `necessary_operations`,
`data_dependencies`, `information_requirements`, `permissible_alternatives`,
`uncertainty`. Only the last two arrays may be empty. P1 physical assembly includes
both the original public task's validated normalization and the logical proposal.
The proposal cannot replace any TaskInput field or change its original input hash.

Capability keys are exactly `max_output_tokens`, `tokenizer`, `seed`,
`structured_json`, with values `SUPPORTED`, `UNSUPPORTED`, or `UNKNOWN`. Missing
capabilities default to `UNKNOWN`. All API usage remains null. Input tokens remain
unknown unless a trusted runner tokenizer callback measures the exact serialized
provider bytes; its explicit identity is recorded. A count above 12,288 raises
`INPUT_BUDGET_EXCEEDED` as a dataset-build defect. A mock counter does not prove a
real provider's tokenization or parameter support. Formal API compatibility is
still a later gate even when a mock fixture supplies every capability.

`parse_response(raw_bytes, kind="logical"|"physical")` accepts one plain UTF-8
JSON object, rejects duplicate keys, nonfinite values, surrogates, excess depth,
extra JSON documents, and responses above 65,536 bytes. It never strips fences,
repairs JSON, or executes text. It returns separate raw-byte and canonical-content
hashes. Key order canonicalizes; array order remains meaningful and preserved.
Logical responses additionally use the seven-field validator. Physical parsing
is explicitly **not** workflow validation: pass the returned value to
`compiler.validate_workflow(task, plan)` before calling any future executor.

`run_mock_generation(task, protocol=..., responses=[bytes, ...],
generation_attempt_id=..., request_ids=None)` ties these pieces together without
a provider client. Each attempted stage retains its request and response identity;
malformed response results retain the raw SHA256 and a sanitized diagnostic.
An invalid logical response stops P1 before the physical stage. Expected stages
and attempted mock requests are both reported, while real requests remain zero.

## Private evidence archiving

`archive_response(private_root, archive_id, raw_bytes, kind=...)` only writes below
the current checkout's ignored `runs/` directory. Public paths, escapes and
symlink traversal are rejected. The archive directory and every file are created
exclusively. A repeated archive ID raises `ARCHIVE_EXISTS` and never overwrites an
earlier result. New directories/files use private POSIX modes where supported;
filesystem access policies and Windows ACLs remain the owner's responsibility.

Files are `response.raw`, `metadata.json`, and, for valid JSON,
`response.canonical.json`. Invalid outputs still preserve exact raw evidence with
its hash; metadata and return values contain only safe diagnostic codes and paths,
never raw response text. Interrupted/incomplete writes remain inspectable and are
not silently retried. Raw archives are private evidence and must not be committed.

Privacy is enforced by the public-profile allowlists and the absence of private
data resolvers. Top-level/nested private fields and unexpected fields are rejected.
Canary and final provider-serialization tests exercise this boundary; a keyword
scanner is not proof that arbitrary text is public. If a trusted caller puts
private facts into an allowed public instruction, this API cannot discover that
provenance. Provider/tokenizer errors are sanitized with exception chaining
suppressed, so the traceback does not reveal a provider's echoed request body.

## Runner context and expected manifest

`binding.build_context(task, condition_id=..., data_manifest=..., runtime=...,
cache_policy=..., verifier=..., metric_spec=..., measurement_profile=...,
operator_registry=..., source_manifest=...)` produces an immutable `RunnerContext`.
This API belongs to the trusted runner, never the model-generated plan. It receives
actual registered metadata objects and hashes their canonical contents; it does
not accept a model's claimed runtime/cache/budget hash as authoritative evidence.

Data entries have exactly `id`, `revision`, `content_sha256`, `schema_hash`. Each
must match the validated public source registry (`data_sha256` in TaskInput);
omitted, duplicated, extra or mismatching identities fail. Source entries are
sorted by ID for the context hash. Public legacy tables lacking revision/content
evidence remain legal compiler inputs, but cannot acquire a complete comparison
identity by fabricating an `UNRESOLVED` hash.

Each runtime/cache/verifier/metric/measurement/operator/source component must be a
nonempty JSON object with a resolved textual `revision`. Null and unresolved
required metadata fail. `measurement_profile` also declares `event_source_id` and
`clock_id`. `source_manifest.public_sources` must equal the complete source
manifest returned by `validate_public_task`. The task's actual resource object is
the budget identity. Changing a component's contents changes the comparison hash.

`freeze_expected(context, specifications)` creates an immutable `ExpectedManifest`
before execution. Each specification contains exactly:

| Field | Meaning |
|---|---|
| `record_id` | Unique pre-registered record identifier |
| `record_role` | `MODEL` or `REFERENCE` |
| `plan` | Actual plan dictionary; its task ID must match the bound task |
| `compiler_source` | Actual nonempty compiler source/bundle bytes |
| `generation_id` | Parent generation identity or reference-selection identity |
| `repeat_id` | Execution repetition identifier |
| `repeat_role` | `PRIMARY_REPEAT` or `TIMING_CONFIRMATION` |

Actual plan and compiler bytes generate their hashes; claimed hashes are rejected
as unknown fields. The runner should supply a canonical source-bundle manifest
covering all compiler components, not merely a claimed version label. This layer
does not decide whether the plan compiles; compiler validation is an independent
prerequisite. MODEL and REFERENCE plans may differ while sharing comparison
identity. Duplicate record IDs and duplicate execution keys are rejected.

The manifest stores canonical bytes and returns defensive copies. Modifying a
returned dictionary cannot erase a denominator entry. The runner must persist its
manifest hash before execution and load the trusted original for validation.
Hashes are content checks, not signatures: replacing the entire trusted runner or
forging a new pre-registration outside this boundary is not prevented by Python
dataclasses. The objects are never deserialized from model response fields.

## Events, sidecars and EXEC-001 handoff

`seal_events(manifest, record_id, observations)` is a runner adapter for **already
observed** events. An observation has exactly `event`, `monotonic_ns`, `status`,
`payload`. The function adds contiguous zero-based sequence, bound event source,
clock and execution identity, plus a SHA256 chain. It invents no time, metric,
status or resource measurement. Supported event kinds are run_started,
node_ready, node_started, node_finished, artifact_created, artifact_read,
artifact_released, run_finished. Exactly one run start and one final run terminal
are required, with monotonic nonnegative integer timestamps.

Terminal statuses are `COMPLETED`, `MODEL_FAILURE`, `TIMEOUT`, `OOM`,
`INFRA_FAILURE`, `UNKNOWN`. Failed/unknown attempts remain expected attempts.
`make_sidecar(manifest, record_id, events, terminal_status=...,
verification_status=...)` binds the sealed ledger hash/count, terminal status,
full context hashes, manifest identity and independent verifier identity.
Verification status is PASS/FAIL/UNKNOWN; incomplete runs cannot claim PASS.
The future independent output verifier supplies that status. The binder does not
infer semantic correctness or compute a resource score from event spans.

`validate_evidence(manifest, model_records, event_ledgers, reference_records=None)`
checks sidecar identities against frozen records, event sequences/source/clock,
hash chain, terminal consistency, verifier and reference identity. Duplicate,
unplanned, wrong-role, orphaned or conflicting records fail with sanitized
`ContractError`. Missing records or ledgers produce `EVIDENCE_INCOMPLETE` and
explicit missing IDs while retaining the original model/reference denominators.
A reference is confirmed only with completed PASS verification and a complete
matching ledger. Losing a reference never removes the model attempt obligation.

`EVIDENCE_BOUND` means content-complete evidence under this interface. Actual
runtime kernels, artifact registry implementations, node state-machine semantics,
buffer lifetimes, provenance verification, clock calibration and isolated resource
accounting remain EXEC-001/later gates. `runtime_enforcement` and
`measurement_validity` remain `NOT_VERIFIED`; formal readiness remains false.

Regression evidence lives in `test_spec001b_generation.GenerationTests` and
`test_spec001b_binding.BindingTests`; actual test method and subcase counts are
reported by the complete acceptance runner rather than equating fixtures with
formal experiment attempts.
