# Experiment protocol and final coverage

The main matrix is `100 parents × 3 conditions × 2 repeats × 10 models = 6,000 stages`. Every model has 600 stages, including 200 initial stages. Each scenario contributes 120 stages per model. Five scenarios each contain 20 parents and four source clusters. Easy/medium allocation is 5/15 per scenario.

## Evaluated endpoints

| Reporting group | Model labels |
|---|---|
| Open-weight model families, API-served | DeepSeek V4 Pro 0813; Kimi K2.6; Qwen3.8 Flash; Gemma 4 31B; GLM-5.3 Flash; MiniMax M3 |
| Closed-model APIs | Gemini 3.8 Flash; Gemini 3.7 Flash; Grok 4.3; GPT-6 Luna |

All were accessed through OpenRouter. Grouping describes endpoint families; it is not local-versus-hosted inference. In particular, the Qwen production route is not identified with a specific released weight checkpoint. Frozen route/configuration evidence is in `weld_release/provenance/final_model_profiles.json`. Model availability and prices are historical observations, not current API recommendations.

Mistral Small 4 was replaced by GLM before any formal Mistral stage because provider rate limiting persisted. Development probes remain outside formal results. Two repeats use the recorded provider sampling settings and are not asserted to be deterministic seeds.

## Execution

The model iteratively creates dataflow nodes, dispatches batches, observes native results, and makes new decisions. Four deterministic workers execute the main suite. Public prompts, JSON-object compatibility settings, and decision limits are frozen before collection. A final submission is checked for output validity and evidence/state validity.

Both update conditions inherit the same initial state. They do not form a serial base→related→irrelevant chain. Incremental resources exclude the imported prefix. A prefix audit separately tests whether old answers and evidence remain usable under the new contract.

## Timing and replay

Online comparisons require matched acquisition groups and operational segments. Native replay fixes saved model decisions and re-executes them at one and four worker slots, three times each. The final replay uses 1,479 valid initial workflows, yielding `1,479 × 2 × 3 = 8,874` executions. All model cohorts share the final replay campaign. The earlier interrupted storage campaign is retained outside final measurements.

## Analysis populations

- Unconditional validity: all 6,000 logical stages; 3,873 pass the final joint gate.
- Initial validity: 1,479 / 2,000.
- Work comparison: 5,006 pairs of valid initial workflows on matching parent/repeat cells.
- Medium online savings: 116 eligible pairs across 37 parents.
- Medium native savings: 467 eligible pairs across 40 parents.
- Conditional relevant adaptation: 807 / 1,479.
- Conditional irrelevant preservation: 1,468 / 1,479.

The stage, pair, and parent counts are different statistical units. Source-aware intervals and common-support comparisons accompany the pooled rates. Earlier very complex tasks and development probes are outside this main easy/medium matrix.

## Instrument checks

The final protocol records 784 tier-contract checks, 19 expansion checks, 11 evidence-equivalence cases, malformed-answer rejection checks, and prefix/resource audits. The final audit accepts two MiniMax stages rejected by the earlier evidence matcher without changing their model responses or execution traces. Every final logical stage has a record. Physical attempts and unknown-charge reservations remain separately accounted for.

This public-release task adds no model calls and does not change experimental results. Acceptance evidence accompanies the source snapshot.
