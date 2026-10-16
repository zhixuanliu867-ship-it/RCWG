# Reproducing WELD

## Choose a reproduction level

| Level | Inputs | Model calls | Available in this repository |
|---|---|---|---|
| Numerical reproduction | Final stage and pair tables | None | Yes |
| Figure and manuscript rebuild | Tables, plotting scripts, LaTeX | None | Yes |
| Re-grade or replay individual traces | Full raw archive, frozen assets, labels | None | Source is included; complete inputs are separate |
| Collect new model responses | Full task environment, API credentials, new budget | Paid | Measured collector snapshot and protocol are included; local configuration is required |

The public quick start reproduces reported measurements from released tables. It does not replay hidden execution traces or claim that today's API will reproduce a historical response.

## 1. Recompute the central results

Use Python 3.12 or newer; no third-party package is needed.

```bash
git clone https://github.com/zhixuanliu867-ship-it/WELD.git
cd WELD
python weld_release/scripts/reproduce_results.py
```

Expected output includes `status: PASS`, 6,000 stages, 3,873 valid stages, 100 parents, 20 source clusters, 5,006 valid initial pairs, and 2,241 dominance pairs. The script independently rebuilds pair relations from component work, checks eligibility against the stage table, recomputes adaptation denominators, and recomputes parent-weighted timing means. It verifies SHA-256 files before calculation. Output is saved to `weld_release/reproduced/summary.json`.

`--skip-hashes` is intended for explicitly edited copies. Keep it off when checking the published release. Bootstrap interval endpoints are supplied in the uncertainty tables; the quick-start command recomputes central estimates, not the original resampling run.

## 2. Rebuild scientific figures

Create an environment and install the plotting requirements:

```bash
python -m venv .venv-weld
# Linux/macOS: source .venv-weld/bin/activate
# Windows PowerShell: .venv-weld/Scripts/Activate.ps1
python -m pip install -r weld_release/requirements-figures.txt
python weld_release/scripts/plot_expansion.py
python weld_release/scripts/plot_design.py
python weld_release/scripts/build_tables_figures.py
python weld_release/scripts/plot_coverage.py
```

Each figure has SVG, vector PDF, and PNG versions. SVG text is editable in Inkscape. The plotting commands rewrite derived figures and table fragments; retain an untouched checkout when verifying the original release hashes. Numerical results should agree, while PDF byte hashes can vary with fonts and library versions. The original dependency versions are recorded in `weld_release/provenance/analysis_runtime_versions.json`.

## 3. Build the manuscript

The official ACL style files are included. With Tectonic installed:

```bash
cd weld_release/paper
tectonic -X compile main.tex --keep-logs
tectonic -X compile main_zh.tex --keep-logs
```

XeLaTeX plus BibTeX is an alternative. The Chinese source uses SimSun/SimHei; on other systems replace them with installed CJK fonts such as Noto Serif/Sans CJK SC. The files use ACL final mode with visible authors and no review line numbers. The PDFs supplied in the repository are already compiled.

## 4. Re-grade and replay the full archive

The complete archive contains `src/`, `vendor/`, `tasks/`, `assets/`, `private/`, `protocol/`, `runs/`, and historical final-main records under `historical_raw/R6`, `R7`, and `R8`. The public benchmark snapshot exposes the measured implementation and public cards; the archive supplies the assets and evaluator labels.

Extract into a new directory. Preserve the archived protocol and original records. Configure interpreter and archive-root paths in a working copy of `environment.json` and the historical-root constants in the postprocessing scripts. The original native replay used Python 3.13.4 and SQLite 3.49.1; analysis used a separate environment. Keep those environments separate when reproducing timing.

The archive's `postprocess.py` performs re-grading, prefix audits, native replay, merged analysis, and validation without model calls. Its original scripts contain author-machine paths and must be relocated before use. `replay_all_models.py` and `replay_matrix.py` preserve response-fixed execution; `audit_grades.py` applies the final evidence-equivalence checks. Expect 8,874 completed native executions in the final accepted replay. The interrupted earlier storage campaign is excluded.

Do not treat changed local timing as a failed numerical replication. Record the operating system, CPU, storage, interpreter, SQLite version, worker count, and background load. Compare fixed-response native timings within the same replay campaign.

## 5. Collect a new API campaign

`weld_release/benchmark/run_matrix.py` is the frozen collection entry point. The source snapshot preserves the original campaign's paths and transport configuration. It is provided for protocol inspection and adaptation, rather than as a one-command public API client.

For a new campaign: create a new output root; install the permitted upstream data; configure the task assets and labels; use your own credentials outside Git; select exact currently available model/provider routes; run development contract checks; record output-format and reasoning settings; freeze the protocol; set a budget; and then launch one collector. Save every attempt, failure, retry, and unknown charge. A new campaign must not overwrite the published one. Model prices and availability must be checked at collection time.

## Data availability

The public release includes all final logical-stage rows, public task cards, evaluator source, work vectors, paired timing inputs, adaptation tables, source receipts, model profiles, figures, and manuscripts. It excludes credentials, author-machine runtimes, private validation labels, raw API response files, and large third-party source assets. Those materials are retained in the authors' separate complete research archive. There is no public full-archive download URL in this release. A full raw-trace replication therefore requires obtaining that archive through the maintainers and observing upstream data terms.

Open a [repository issue](https://github.com/zhixuanliu867-ship-it/WELD/issues) for artifact-access or reproduction questions. Include the commit, Python version, command, and concise error output. Never include API keys or private account data.
