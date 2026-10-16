# Reading WELD

1. Read the abstract and introduction for the three research questions.
2. Read Figure 0 and the measurement section for the model/worker boundary, validity gate, and update checkpoint.
3. Read the dataset section and [construction notes](DATASETS.md) for the relationship between upstream records and WELD tasks.
4. Read the findings with their denominators. Figure 1 compares valid alternatives; Figure 2 compares savings within timing domains; Figure 3 compares repair and preservation.
5. Use the appendix for source revisions, model profiles, instrument checks, and additional counts.

The English and Chinese PDFs contain the same study. The English manuscript follows the ACL layout. Conference acceptance is not claimed.

## Check the evidence

| Question | Table under `weld_release/data/` |
|---|---|
| Attempts and successes | `combined_main_stages.csv`, `paper_model_counts.csv` |
| Work among valid solutions | `native_work_pairs.csv`, `native_work_pair_components.csv` |
| Equal call counts and different work | `same_tool_call_count_primary_work.csv` |
| Realized time savings | `attenuation_primary.csv`, `attenuation_parent_uncertainty.csv` |
| Matched online and native comparisons | `paired_timing_domains.csv`, `paired_timing_domain_uncertainty.csv` |
| Changes in answer versus evidence | `combined_prefix_audit.csv`, `prefix_refresh_matrix.csv` |
| Conditional adaptation | `all_updates.csv`, `conditional_adaptation.csv` |
| Source sensitivity and matched support | `leave_one_source_out.csv`, `related_source_uncertainty.csv`, `pairwise_common_support_adaptation.csv` |

The stage unit is `(model, parent, replicate, condition)`. Pair rows reuse stages; thousands of pairs are not thousands of independent tasks. Parent- and source-aware uncertainty is reported separately.

## Inspect the implementation

Under `weld_release/benchmark/`, `src/tiered.py` defines final task interfaces and validation; `src/dataflow.py` defines nodes, references, transformations, and continuations; `src/runtime.py` records dispatch, provenance, revisions, and events; `src/adapters.py` implements native operations. `audit_grades.py` provides final evidence-equivalence checks. `event_metrics.py` and `combine_final.py` build execution accounting and final analysis. `tasks/` contains public conditions.

The measured snapshot supports inspection and full-archive replay. The portable public entry point is `weld_release/scripts/reproduce_results.py`. Read [reproduction](REPRODUCING.md) before launching an archived collector.
