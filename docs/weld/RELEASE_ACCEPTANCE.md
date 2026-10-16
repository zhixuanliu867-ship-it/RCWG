# Public release acceptance

Release date: 2026-10-16. The underlying experiment remains frozen.

## Verified locally

- Numerical reproduction passes on Python 3.12.14 using only the standard library.
- The public manifest verifies 503 release files byte-for-byte.
- All 6,000 logical stages are unique and have balanced model/scenario denominators.
- Joint validity agrees with the conjunction of the two recorded checks.
- Every work pair is eligible under initial validity, and its relation is independently reconstructed from the component table.
- Conditional adaptation and parent-weighted medium timing estimates reproduce the manuscript's central values.
- All four figure scripts execute successfully and regenerate seven figures plus table fragments.
- No paid model call is made by the numerical or figure reproduction.

The public CI repeats numerical reproduction on Python 3.12 and 3.13 and runs the tracked-file credential guard. Its remote status is visible in the repository Actions tab. This document records local checks; it does not substitute for a completed remote run.

## Release contents

The public task directory preserves 300 main cards and earlier development/legacy cards. Main membership is determined by `combined_main_stages.csv` and `task_catalog.json`; extra cards do not enter paper denominators. Raw API responses, private labels, runtime environments, and full third-party assets are not tracked. The complete replay's input requirements are listed in `REPRODUCING.md`.

Original RCWG specifications and prompt files remain byte-identical. The public plotting entry point removes one author-local dependency search path; the measured benchmark snapshot is unchanged. Source/provenance display paths are redacted while source hashes and numerical values are retained.
