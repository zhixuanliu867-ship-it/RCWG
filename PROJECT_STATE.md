# RCWG project state — 2026-09-18

Ticket: **RCWG-BOOT-001**

Repository: `zhixuanliu867-ship-it/RCWG`
Observed remote main: `6337ff75c16ebd014bf9be7210402b8741caad0a`
Observed README blob: `2581964c2697e27eae1560385bb3cbc8d83bdbca` (`# RCWG`, without a trailing newline)

## Decisions
- Owner confirmed: Windows + WSL2; API-based model inference; cloud-hosted workflow; Google and Alibaba accounts; current-round budget USD 100–200.
- Recommendation: GCP outer Workflows, CPU-only Cloud Run Jobs for bootstrap integration, private Cloud Storage artifacts. `us-central1` is the cost-baseline region candidate, pending owner approval and data-location review.
- Accounting assumption: this round's budget includes model APIs and cloud infrastructure, with a working envelope of USD 150.
- Formal metrology: prepare a controlled Linux CPU worker/VM after isolation calibration. Record API internals as unobservable. Cloud Run BOOT measurements are engineering diagnostics.
- Original research scale is retained. API model identities, protocol amendment and formal service conditions remain to be frozen.

## Delivery status
| Item | Status |
|---|---|
| Source archive/member hashes and 33 imported reference files | DELIVERED / VERIFIED |
| Standard-library bootstrap implementation and unit tests | DELIVERED / see TEST_REPORT.md |
| Target Python 3.12 execution | PENDING_TARGET_VALIDATION |
| User WSL2 configuration | PENDING_OWNER_DOCTOR |
| Container build and base/image digests | PENDING_TARGET_BUILD |
| Google workflow YAML syntax | STATIC_CHECKED_ONLY |
| Cloud deployment and persisted artifact | NOT_EXECUTED |
| Live API probe | NOT_EXECUTED |
| Remote branch, Issue and PR | NOT_CREATED; integration writes returned HTTP 403 |
| Formal campaign | NOT_FROZEN |

No remote repository modification, cloud provisioning or paid API call was completed by this delivery. The local patch is based on the observed initial README content; import must first check the current remote and any intervening owner changes.

## Next gate
The owner runs `scripts/doctor.py` in WSL and returns the sanitized JSON. Codex then verifies target Python 3.12 and imports the changes on a branch. Cloud/API acceptance follows explicit project, access, price and budget approval.
