# Measurement definitions

## Validity

`Q1` checks the requested output or application-state contract. `Q2` checks executed support and identity/version bindings, or supporting state observations. `G = Q1 AND Q2` is joint validity. Missing and incorrect submissions contribute zero to the planned-stage denominator. Submission is a separate indicator: a delivered answer can be wrong or unsupported.

There are 600 stages per model and 120 per model/scenario. The all-stage score is `100 * sum(G) / 600`. The balanced design makes this equal to the mean of five scenario rates. Initial validity uses 200 stages per model. This aggregates one binary outcome, not different abilities into a weighted score.

## Native work

For unique execution events, `W = sum_e w(e)`. Coordinates retain native units. Physical retries receive new event identities and count again; inherited prefix events have zero incremental work.

| Scenario | Primary coordinate for savings | Additional coordinates |
|---|---|---|
| Graph | Paper records examined | returned records, pages, transformations |
| Code | Native regression cases | checks, source lines/bytes, contracts, transformations |
| Analytics | SQLite progress-work proxy | queries, returned rows, transformations |
| Telemetry | Metric values examined | log/trace rows scanned, queries, transformations |
| Business | Business records read | writes, state changes, state reads, transformations |

`a` dominates `b` when every active native coordinate is no larger and at least one is smaller. Equal vectors and incomparable trade-offs remain separate. Pairs require the same parent, initial condition, and repeat, with both executions valid.

SQLite's callback interval is 1,000 VM instructions. The legacy `sqlite_vm_steps_lower_bound` field is a progress-work proxy, not an exact instruction counter or universal lower bound. Zero-denominator cases remain in absolute tables and are excluded from ratios.

## Realized benefit

Order a pair by primary work, `W_l < W_h`:

```text
S_W = 1 - W_l / W_h
S_T = 1 - T_l / T_h
D   = S_W - S_T
```

Positive `D` means the time reduction is smaller than the work reduction. A slowdown is not required: 50% less work and 20% less time give a 30-point gap.

Online time covers runtime start through completion, including model requests and local admission. The adjusted domain subtracts recorded local admission. Native replay fixes saved decisions and measures the union of worker intervals at one/four slots, taking the median of three repetitions. Overlapping worker durations are not summed as wall time.

Online pairs require compatible acquisition groups and operational segments. Native replay measures all cohorts together. Estimates average pairs within a parent, then give eligible parents equal weight. Source-aware uncertainty and matched-domain tables accompany the estimates. Evaluator validation work is separate from workflow work.

## Selective adaptation

For update type `u`, `A_u = sum(G_initial AND G_u) / sum(G_initial)`. Related and irrelevant stages branch from the same initial checkpoint. Related validity measures repair; irrelevant validity measures preservation. Incremental calls, work, time, and costs measure continuation effort. Unconditional update validity includes every attempted update.

The prefix audit tests old answers and old evidence under the new contract. It distinguishes required answer changes, fresh support for unchanged answers, and reusable results. Zero-call continuations are interpreted using this audit.

## Accounting

Manager requests, worker operations, tools, failures, and retries are recorded. Receipts distinguish settled charges from unknown reservations. Remote accelerator utilization is not inferred from latency. Versioned artifacts and unique events prevent double-counting inherited work.
