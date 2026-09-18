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
## 本地验收进展 — 2026-09-19

本阶段范围限定为“本地仓库与离线核心验收”。云端、容器与真实 API 验收保持各自门禁，未在本阶段执行。

| 项目 | 状态 | 证据 |
|---|---|---|
| 远端仓库 / 独立分支 / PR | VERIFIED | PR #1 (rcwg/boot-001 → main)；被审提交 ed6a5338… |
| 离线核心 + GitHub CI | PASS | CI run 35362347262 / job 105656410610 (success) |
| 用户 WSL / Python 3.12.14 环境绑定 | VERIFIED | 见下方新 doctor |
| 本地阶段状态 | BOOT_LOCAL_ACCEPTED | 本次收尾提交 |
| 云端验收 | DEFERRED_BY_OWNER | 原门禁 G5 保留 |
| 容器验收 | 延后至首次云部署前 | 原门禁 G3 保留 |
| 真实 API 验收 | NOT_EXECUTED | 后续接口适配票处理 |
| 正式实验 | BLOCKED_NOT_FROZEN | 正式门禁保持关闭 |

目标 WSL 解释器：Python 3.12.14（`uv --offline --frozen --python 3.12.14`）。
新 doctor：`python_version=3.12.14`、`python_3_12_target=true`、`formal_ready=false`。
本地 unittest：43/43 通过（doctor 与单测日志的 SHA256 见 PR #1 描述）。
说明：本次以已验收的 3.12.14 重新采集环境证据；系统默认 Python 3.14 未用于验收。
Issue 状态：按实际单独登记（不因 PR 已存在而推定 Issue 已创建）。
