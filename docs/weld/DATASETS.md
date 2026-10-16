# Dataset and task construction

The main suite has 100 parents from 20 source clusters. Each has `base`, `related`, and `unrelated` cards. Every scenario has five easy and fifteen medium parents. Difficulty changes output/composition burden while retaining choices about scope, batching, sharing, and reuse. These are WELD tasks derived from upstream sources; their scores are not the sources' original benchmark scores.

| Scenario | Four clusters | Parents | Transformation |
|---|---|---:|---|
| Graph | STaRK MAG original, Stanford, MIT, Tokyo | 8/4/4/4 | Author/publication/reference neighborhoods; scoped summaries |
| Code | Requests, ItsDangerous, packaging, python-dotenv | 4/4/6/6 | Original, controlled mutation, and repaired snapshots; case-bound checks |
| Analytics | BIRD debit, BIRD financial, Chinook, Northwind | 4/4/6/6 | Entity/period aggregates; equivalent SQL and summary helpers |
| Telemetry | RCAEval checkout, currency CPU, product-catalog delay, Train Ticket order CPU | 8/4/4/4 | Frozen metric/log/trace reports and split-time changes |
| Business | Four AppWorld-derived exports | 4/4/6/6 | Playback, downloads, payments, preservation constraints |

## Graph

[STaRK](https://github.com/snap-stanford/stark), [dataset](https://huggingface.co/datasets/snap-stanford/stark), revision `88269e23e90587f99476c5dd74e235a0877e69be`. Original, Stanford, MIT, and Tokyo slices contain 16,550/149,765, 16,058/142,401, 14,376/126,927, and 13,167/120,386 nodes/edges. Expansion selects focal authors by institution and retains publications and outgoing references. Focal authors are disjoint from the original selection; reference nodes may overlap. Tasks specify author sets, time ranges, aggregation fields, and tie rules. Summary operations and lower-level access paths can both satisfy the contract.

## Code review and impact

[Requests](https://github.com/psf/requests) is pinned at `b25c87d7cb8d6a18a37fa12442b5f883f9e41741`; [ItsDangerous](https://github.com/pallets/itsdangerous) at `096c8d42545d3b68ea21a4f890fb2b2d8979c0bd`; [packaging](https://github.com/pypa/packaging) and [python-dotenv](https://github.com/theskumar/python-dotenv) use 25.0 and 1.1.1 source archives. Seeded mutations are experimental changes, not claims of upstream defects. Public normative behavior is separate from observed current behavior. Results bind package, check, case, and revision. A review identifies exactly the failing scoped cases. Related changes require refreshing affected conclusions or support. Source receipts preserve versions and hashes.

## Analytics

Sources are [BIRD](https://bird-bench.github.io/), [Chinook](https://github.com/lerocha/chinook-database), and [Northwind](https://github.com/jpwhite3/northwind-SQLite3). Debit tasks aggregate consumption by requested clients/years; financial tasks aggregate loans by regions/statuses. Purchase tasks count distinct orders/invoices and sum quantities and line values. Northwind applies line discounts. IDs retain source types. Changes alter object sets or controlled source values. Validation accepts equivalent read-only SQL and native summaries when values and executed support satisfy the same contract.

## Telemetry

[RCAEval](https://github.com/phamquiluan/RCAEval), [dataset](https://huggingface.co/datasets/phamquiluan/RCAEval), expansion revision `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`. Each cluster retains metrics, logs, traces, and injection time. Public filters and split timestamps define the requested report. Related cards shift the split while raw records remain fixed. WELD measures controlled diagnostic reporting rather than the original root-cause ranking score.

## Business state

[AppWorld](https://github.com/StonyBrookNLP/appworld) export IDs are `b0a8eae_1`, `22cc237_1`, `3fcc458_1`, and `90adc3f_1`. WELD implements local transitions over exported records. Playback accepts an owned playlist meeting duration. Downloads preserve prior membership. Payment reconciliation computes `max(0, share - paid)` and replaces requests by member ID. Validation checks resulting state and preserved preferences. This is an AppWorld-derived adapter, not an unmodified AppWorld run.

## Artifacts

`weld_release/benchmark/tasks/` holds exact public contracts. `weld_release/data/task_catalog.json` maps membership and clusters. `weld_release/provenance/` records construction receipts. The paper appendix provides further details and citations. Third-party sources retain their terms. Full source assets and validation labels are in the separate complete archive.
