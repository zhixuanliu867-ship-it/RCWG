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

## SPEC-001A 决策与实现进展 — 2026-09-19

当前上游 main 已核实为 `08b1ecff33ab01098926e3dceba64ab6ab4fa02c`，PR #1 已合并。
上述初始状态与本地收尾记录作为历史保留。本次目标3.12.14环境依据所有者验收记录；交付端代码测试环境另列。

| 项目 | 状态 |
|---|---|
| 协议/算子/计量决策 | DESIGN_APPROVED（用户已授权核心范围内直接修订） |
| 32算子ID与候选来源 | 保留；implementation_status=NOT_IMPLEMENTED |
| F1 TaskInput有限profile与白名单组装 | IMPLEMENTED / 离线测试见本次报告 |
| 三值预算评分、分层归约、buffer/字节/见证覆盖计算核 | IMPLEMENTED / synthetic及单测；不是真实模型结果 |
| cgroup读值诊断 | READ_ONLY_PROBE；未验证正式隔离 |
| 完整WorkIR静态验证器与全部算子端口类型 | NEXT_CHECKPOINT: SPEC-001B |
| 云端、容器、真实API | 保持原延期/未执行状态 |
| 正式实验 | NOT_FROZEN；formal_run_enabled=false |

采用 docs/spec001a/SPEC-001_DECISIONS.md、METROLOGY-001.md 与 CLAIMS_AND_FALSIFICATION.md。
新增接口和文件在新路径；原33个参考文件保持不变。configs/boot.json仅移除已有用户证据支持的两个本地blocker，正式运行标志保持关闭。
本次远端写入结果与交付端实测结果见 docs/spec001a/TEST_REPORT.md；不把本地补丁生成当作远端已合并。

## SPEC-001A 用户 WSL 导入验收 — 2026-09-19


独立分支 `rcwg/spec-001a`；原包 121 文件与导入 tree 逐字节一致。
用户 WSL / Python 3.12.14：原 117/117，修订后 **131/131 PASS**；BOOT/SPEC、mock、原件完整性及公开仓库 guard 通过。
修复 JSON 数值溢出、评分输入异常边界、未完成运行时延比与暂存凭据检查；保持科学主比较、32 算子/72 模板/6 模型槽及原件不变。
证据：`docs/spec001a/OWNER_WSL_ACCEPTANCE.md`、`evidence/spec001a-owner/ACCEPTANCE.json`；日志在 `runs/spec001a-owner-20260919T095950Z-3473`（不入 Git）。
新 doctor 保留 Docker 不可用、gcloud 不存在、formal_isolation_verified=false、formal_ready=false 的实测状态。
正式门禁 `BLOCKED_NOT_FROZEN`、退出码 2；真实模型/云/IAM 动作 0。
下一阶段 **SPEC-001B**；完整验证器与 32 算子运行时仍未实现。GitHub CI 和远端状态另行核实。

## SPEC-001A review / SPEC-001B start — 2026-09-19

Reviewed PR #2 head: `6afd48490094d716dc65cf84fe822e45216fcac3`; tree `e09ee3a93b46192d3e88775fda5e24bade771f4d`.
SPEC-001A review: `ACCEPTED_OFFLINE`; actual PR #2 merge remains an owner/repository action (observed open).
SPEC-001B decisions: approved in `docs/spec001b/DECISIONS.md`; implementation started.
Starter implementation: structural/lexical dependency and identity modules, 63 new tests; full compiler and full task/message integration remain pending.
`STRUCTURE_PASS` and the foundation/sentinel checks are not complete SPEC-001B acceptance.
Follow `docs/spec001b/CODEX_TASK.md` and `ACCEPTANCE.md`; preserve A's 131 tests and four review fixes.
Cloud/API/IAM actions remain unexecuted in this package; formal gate stays closed.

## SPEC-001B 完整实现 — 2026-09-19

已继承独立审查的 A 提交 `6afd48490094d716dc65cf84fe822e45216fcac3`，独立分支 `rcwg/spec-001b`。
PR #2 最新核对仍为 open；尚未把 A 的合并写成已完成。B 的远端基线与 PR 状态以本轮交付证据为准。

实现 TaskInput tagged union、schema/type 代数、完整 32/56 静态算子契约、区域控制、资源与别名生命周期义务、P0/P1 mock、不可变 expected manifest 和来源绑定。保留原 131 项及基础 63 项测试，完整验收读取固定方法清单并核对实际通过记录；27 哨兵仅是其中一项。

本阶段验收结果由 `scripts/accept_spec001b.py` 输出 `SPEC001B_OFFLINE_GATES_PASS`；用户 WSL 与 GitHub CI 分开留证，最终 clean apply/tree 证明与交付状态另列。运行内核、artifact 注册器、独立语义 verifier、受控 Linux 资源计量为 EXEC-001 待实现项，不产生正式实验结果。

正式门禁保持 `BLOCKED_NOT_FROZEN`（退出码 2），真实模型／云／IAM 动作 0。原 33 文件、科学主比较与规模不变。下一工作入口：`docs/spec001b/EXEC-001_INTERFACE.md`。

## 2026-09-19 · 独立 B 复核与 EXEC-001 启动

B head a1f65120ef0b2b8e1fb6f1c31224244d6f7ee16b 的交付/WSL/CI/源码绑定已独立复核，可进入 EXEC-001。原上文状态作为历史保留。当前远端PR2未合并、PR3 draft；连接器合并PR2实际返回403，未改main。合并精确内容授权与权限阻断回退见 docs/exec001/CODEX_TASK.md。

本轮本地已实现 F1 reference 5算子/8分支和真实数据→WorkIR→artifact→独立verifier→事件绑定闭环。它是 REFERENCE_CORE，不等于完整 EXEC-001 或正式效率后端。新增77项、合计662项交付环境3.13.5测试通过；目标3.12.14与独立CI待Codex新票验收。原B正式门禁保留false，native/cgroup/云/API未执行。


## EXEC-001 完整 F1 工程实现 — 2026-09-19

已按精确受审 head 依次合并 PR #2、#3；merge commits 为 05064b27d3f14642b90bdccdbd11fd409ad005a1 和 47ea9703f8adfa5b5778aee5eaff3be802858efb。main 保留 B 已审 tree 5b1b7cd587bbb3df54952ea24eb6841767a1e0bd；EXEC 使用独立 rcwg/exec-001 分支。上述历史待办状态不再代表当前合并状态。

E1 独立 worker、真实父 deadline、进程组终结和 durable run 证据；E2 P0/P1 实际解析到执行、冻结多案例分母；E3 完整离线门禁、故障回归、5/8 实际 dispatch 与运行义务矩阵。保留原 585+77 方法和字节。完整入口 scripts/accept_exec001.py，原 reference 入口仍为 REFERENCE_CORE。

独立 WSL/CI 和补丁应用证明以该提交交付证据为准。整票状态 EXEC001_F1_ENGINEERING_ACCEPTED 仅在全部 X00–X15 证据联合满足后使用。实现说明见 docs/exec001/IMPLEMENTATION.md，下一阶段接口见 docs/exec001/NEXT_GATE.md。受支持范围为 F1 root chain；native/DAG/cgroup/真实 API/云/IAM 未开启，正式门禁继续 BLOCKED_NOT_FROZEN，预算内判定和隔离 RAM 保持 null。


## API-001 项目绑定与离线工程 — 2026-09-20

精确 PR #4 的私有 X15 复核已完成，受审 tree 7763db9b757488e393fb4b4d8552c2daeafcecde 原样合并至 main e826100b42c6a3debd72a9ef6d157d2755e118e6；本票使用 rcwg/api-001 独立分支，API PR 保持草稿待独立审查。

纯新增 API 包导入后，WSL Python 3.12.14 实跑原 708 + API 92 目标验收通过；继续补齐项目/账号/runner 子进程绑定、认证失败留证、原测试字节 pin 和 CI/配置/脚本源码清单。新增 21 项回归已在离线 API 113 项中通过，完整最终 WSL 与 CI 结果独立随本票交付，不能以此段替代机器证据。

WSL 默认 gcloud 账号列表为空；用户确认登录在 Windows 后，仅本票子进程使用现有 Windows 配置，已实际核对获批账号 ACTIVE。没有重新安装/登录或全局配置改写；云权限、LIVE、凭据签发和写操作的最终实际状态分别见本票私有交付。用户已批准的 global/$1/3+3 仍有效，但实际 manifest/24h审批需满足技术前提后登记。模型输出、运行结果和审批仅私有保存。正式门禁继续 BLOCKED_NOT_FROZEN，未用通过字符串改写隔离/RAM/预算真实状态。
