# NATIVE / METROLOGY next-stage interface

CLOUD-001 provides verified service-identity transport, durable one-batch GCS
admission, pinned image/source provenance, F1 execution/answer seals and separately
scoped platform/model/worker/verifier/archive timing. Current backend is Python
reference root-chain, 5 operators / 8 branches. Static 32 operators / 56 contracts
are not runtime coverage. No arbitrary DAG/regions or formal isolation claim.

Inputs to preserve: reviewed API/WIN baseline, final CLOUD PR head and source map,
image commit 50de23f1ba6571ec500b0f207ec9cc18aec28967, immutable image digest,
actual public prompt bundle/hash, private expected manifests, untouched model text,
generation denominator 2, GCS generations, claims/reservations and independent
platform/task/answer evidence. Never reset the old or CLOUD-001 pilot ledgers.

Next work: freeze a versioned native backend/implementation dispatch contract;
retain reference results as semantic oracle; define exact worker machine/cgroups,
process-tree CPU, peak whole-tree memory, I/O/copy scopes and sampling calibration.
Test OOM/timeouts/descendants/accounting overhead and failure attribution, report
missing observations explicitly, and preserve budget_within=null until verified.
Do not substitute Cloud Run's 4 GiB task container for the WorkIR 128 MiB budget.

Validation should measure real algorithms/data movement, including full-sort vs
streaming-heap and scalar vs vectorized behavior. Freeze resource-condition pairs,
reference-candidate coverage and repeated-run noise before efficiency comparisons.
Prove all promised branches through actual execution and independent artifacts;
gate unimplemented operators/regions explicitly. Formal six-model/480-development/
960-test matrix and resource-conditioned causal claims remain a later freeze.

Cloud orchestration lesson: a freshly read-back IAM binding is insufficient as an
effective-permission readiness check. Test the runtime identity's required reads
without resubmitting jobs; keep controller failure, job terminal, GCS archive,
answer verification and measured budget as separate states. The final deployed
CLOUD-001 Workflow is a read-only receipt reader; it is not an active dispatcher.

No new models, builds, jobs, cloud resources, IAM, billing/system changes or formal
experiments are authorized by this interface card. Propose the next bounded scope,
exact source review and cloud cost/resource changes before execution.
