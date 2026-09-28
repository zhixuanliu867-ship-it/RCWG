# RCWG project state — 2026-09-18

## NEXT-LIVE-001 completed finite packet — 2026-09-28

The user-authorized A-to-B continuation ran at code commit
797c5b4cf1bf2f11e637bfa5bc616c85f3ade0d6. Exact-head Python 3.12.14 CI passed
2,184 FULL001 tests and 286 subtests, retaining all prior 2,149 IDs. Inherited
Python 936, native N0-N3 115 and N4 82 passed; affected WSL tests passed 183.
Selected CI artifact members were retained with CRC/hash/source checks.

Real dispatches were 14 G, 4 E and 17 COUNT: all 35 HTTP responses were complete,
with 34 HTTP200 and one qualifying HTTP429. G2/P0 recovered after one bounded
5-second-minimum retry using the identical body and actual COUNT, a separate
physical ID and separate reservation. No new unknown or model deferral occurred.
The original unknown and its USD0.251904 hold remain unchanged.

All 12 F1 logical slots settled. Six legal plans (G1/G2/G3/G4/G5 P0 and G3 P1)
ran three times each on existing WSL; all 18 native executions passed the
independent verifier. Five P1 logical outputs wrapped logical_contract and
failed the unchanged root schema. G0/P0 wrapped wire_schema and failed shape
validation. Their 18 dependent X slots stayed NOT_RUN. No output was unwrapped,
rewritten, or regenerated. Prompt wording names these containers and may
contribute to wrapper ambiguity; this single block cannot establish causation
or general model/protocol rankings.

Fixed E public field/citation validity improved to 3/4, but independent business
correctness remained 0/4: two source-label answer/witness failures, one invalid
JSON response, and one controlled-text response with correct fields but
incomplete evidence coverage. These are fixed-reference diagnostics, not
model-generated semantic workflows. E_QUOTE_PROMPT_1 stays separate from the
unadmitted schema-constrained E_QUOTE_1/P5 tracks; no contents-only schema count
is claimed. The natural panel has not run.

Incremental conservative reservations are USD2.667133; cumulative reservations
are USD56.115756, not invoice costs. The original recovery subcap has only
USD1.473310 left. The next whole F2 packet requires USD3.606142 including two
capacity retries (USD2.709118 before retries), so it was not dispatched. No
scope/epoch reset or new funding was assumed. Later families, natural panel,
reference confirmation and formal runs remain NOT_RUN under the original order.

All 23,702 original AUTO2 files and 1,448 R1 files passed full preservation hashes.
All native execution seals and independent results were rechecked; the finite
executor exited and its task cgroup was removed. No new VM, disk or account was
created. Private reports, attempts, budgets, output/gold and source locks remain
outside public Git. SERVICE_ONLY and formal_ready=false remain in force;
formal Success@Budget, EfficientSuccess and T_ref are null. The original research
matrix is unchanged. PR9 remains draft; no merge or history rewrite.

## 2026-09-27 AUTO2 continuation in progress

The current user explicitly delegates preparation and bounded real cloud work
through the new AUTO2 profile. Historical receipts and policies below are
preserved. The current cumulative ceiling is USD100, including historical
holds, with no automatic increase. PR #9 remains draft.

The AUTO2 controller, separate host claims, label provenance, live transition,
per-job service bounds and conditional calibration/reference/formal adapters
are implemented. Forty-seven additional offline regression tests pass. The
final source requires complete Linux acceptance before any model inference;
partial and failed earlier runs remain preserved and do not count as passes.
The task-owned cloud executor and original-scale dataset preparation are real
operations, not mock evidence. Two private reports will record actual final
preparation and live outcomes, budgets, identities and cleanup.

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


## API-001 WIN-01 recovery — 2026-09-20

User approved Windows native gcloud/HTTPS with direct USER identity; old NET-01 is SUPERSEDED_BY_WIN_01. V2 configuration and approval retain old SA semantics, fixed model/global/1-dollar/3+3/zero-retry scope and original Linux F1 executor. Original 821 methods and byte-pinned source tests are retained by explicit baseline manifest; Windows helper, runtime and deployment are independently bound. New target, native Windows and CI evidence are separate. Final LIVE, billing estimates, credential commands, cloud changes and unknown states are reported only from the private delivery evidence. PR5 stays draft. No new head merge is authorized. Formal remains BLOCKED_NOT_FROZEN.

## RCWG-CLOUD-001 (engineering evidence complete; independent PR review pending)

Reviewed API/WIN head 272950bd3dedb13d29857600e6a07f6c43cb8cc8 was merged
as 6e5ee40984d2631be4be7ec277cb63cb31988c5d after fresh matching-head CI
and conflict checks. Development branch: rcwg/cloud-001.

AUDIT-F01 is addressed by the new cloud001_v1 public grammar/example profile;
the protected prompts/reference and all previous raw results remain unchanged.
The old pilot is consumed. This ticket uses separate fixed GCS claims/slots.
The owner approved change plan SHA256
68f11740c7242475c2926025cf4bef22495a9877a49bc9503abb069ccf7ffd0c:
us-central1, USD 5 working allocation (USD 1 model / USD 4 infrastructure),
at most two builds, one replay and one live execution, one new 3+3 model batch.
The public change plan remains an immutable proposal; the actual approval
receipt is private and separate from measured acceptance evidence.

New modules preserve USER/WSL profiles and use explicit cloud service identity,
append-only conditional GCS admission, same-image replay/live and independent
artifact reread. Runtime and local simulation labels are not cloud acceptance.
Cloud C1/C2, actual image digest, platform/GCS reconciliation and invoice cost
remain separate gates recorded in the private delivery. Formal status stays
BLOCKED_NOT_FROZEN; only the existing F1 reference backend is implemented.
See docs/cloud001/CHANGE_REQUEST_zh.md and docs/cloud001/IMPLEMENTATION.md.

CLOUD001 cloud C1 and new LIVE evidence have now been independently reopened:
replay P0 PASS / old P1 static refusal; live P0 PASS / P1 PASS, 3+3 HTTP 200,
zero model retries. The initial LIVE Workflow failed its status GET with 403;
one separately approved read-only recovery succeeded under the same identity.
This preserves the original controller failure and does not add a Job execution.
The current Workflow is read-only. Draft PR #6 remains unmerged for review.
New generation cost estimate: USD 0.00973975; invoice unknown. Formal readiness
and memory-isolation claims remain false; stage status is engineering only.


## Active ticket: RCWG-NATIVE-001

Current scope: docs/native001/START_HERE_zh.md and SCOPE.json. N0–N3 combined; historical text above retained. One independent branch and one draft stacked PR; no merges, no model/cloud/system/cgroup changes. formal_ready=false.


## Active ticket: RCWG-NATIVE-001 / N4

Base 456a30d0d242ec005bfb9e25fdc7a45c72aa9af8; branch rcwg/native-001-n4. Read docs/native001n4/START_HERE_zh.md and DECISIONS.md. Offline counter hardening, receipt-bound finite calibration implementation and independent regression gates. One draft stacked on rcwg/native-001; PR6/7 not merged. Host proposal remains approved=false; real calibration NOT_RUN pending exact owner receipt. No models/count/GCP/IAM/install/cgroup writes. Formal BLOCKED_NOT_FROZEN. Historical evidence above retained.


## RCWG-FULL-001 checkpoint

Baseline 2824ee8e7678a39b3bff2ac701ffececd50d1e81, isolated branch rcwg/full-001. Continue from docs/full001/PROGRESS.json, REQUIREMENT_TO_EVIDENCE.json and OWNER_ACTIONS_REQUIRED.json. Software implementation and acceptance remain incomplete. Native CI build passed; the first independent native run found integer-division rounding failure; failed evidence is retained. N4 plan and history unchanged. All six readiness flags remain false; formal BLOCKED_NOT_FROZEN. Owner directly authorized new-branch pushes, offline CI and a draft PR based on rcwg/native-001-n4; no merge or force push. No host, paid API or cloud approvals inferred.

## RCWG-FULL-001 recovery — 2026-09-22

The preceding history is retained. Resume the same total task from docs/full001/PROGRESS.json and SOFTWARE_GAPS.json. The recovered local checkout contains the managed campaign runner, eight fixed service bindings and existing-auth adapters, control outbox, explicit private sealing, source snapshot tooling, paired analysis and total-acceptance dispatcher. Current Windows Python 3.13.4 supplementary integration passed 331 tests with no skips; it is not Linux/native or complete software acceptance. The dispatcher actually refused total acceptance because Linux Python 3.12.14 is unavailable in the current environment. Current WSL access returned E_ACCESSDENIED; repository connector writes returned HTTP 403. Historical CI applies only to its recorded commit. Keep local source and evidence, do not infer permission from an inaccessible environment.

Formal capacity builders, bounded external-sort integration, transformed/graph/JSON allocation accounting, remaining schema/external-adapter coverage and exact-current-source native/inherited acceptance remain software work. All six readiness states stay false. No paid/count/cloud/IAM/install/cgroup/calibration/merge actions were performed in this recovery. N4 original 888 slots and approved=false remain unchanged.


## RCWG-FULL-001 continuation checkpoint — 2026-09-22, portable-w05

Current supplementary integration passed 369 tests and 104 subtests, without skips, on Windows Python 3.13.4. Independent JSON Schema validation passed all 1440 plan structures, eight service bindings and three rejection variants; workflow YAML was checked offline. These are not current Linux/native, formal capacity or cloud acceptance.

F1/F2 now have bounded Arrow construction and an independent on-disk SQL oracle. Their 24 templates x four conditions passed small fixture construction, static compilation and independent oracle/condition checks. Formal workload construction still requires exact host admission. F3/F4 formal builders and F5/F6 formal-source binding remain software work.

Reference attempts persist before execution and resume without resend; uncertain outcomes pause their group. New native reference execution uses inherited reference/timing evidence roles. E2's versioned binding now seals the original C0 plan against the target context without rewriting the plan. Controller timing now ends at committed result receipt, before process drain and verification. New Linux integration cases are retained but have not run in this environment. A facility retry must preserve plan, source, data, model, budget and comparison context.

Resume from PROGRESS.json and SOFTWARE_GAPS.json. All six readiness flags remain false, formal BLOCKED_NOT_FROZEN. No host load, paid/count request, cloud/IAM change, system install, cgroup write, merge or force push occurred. N4 and inherited protected bytes are unchanged. Historical failure directories remain; inaccessible historical directories are separately recorded and never inferred as acceptance evidence.


## REVIEW-R1 continuation — 2026-09-23

R01-R06 remain under unified exact-head acceptance. The c2ddd71 CI built native modules and passed inherited native gates, but 507 FULL errors exposed a reused global allocation observer (502), concurrent artifact iteration (3), and two new test fixture mistakes. Failure artifacts and original test IDs remain intact. Native observer state is now call-scoped with ContextVar; retirement is serialized. WSL target Python 3.12.14 and hash-locked dependencies are accessible without system installation. CI remains the available native compiler.

F3/F4 formal candidate builders now preserve fixed capacity and use independent disk/stream oracles. The F4-08/10 formal reference uses vector projections instead of millions of dynamic map instances. F4-12 declares a finite public continuation predicate (remaining > 0 AND iterations < 16), returns the current state when that predicate becomes false, and never treats an implicit runtime-limit exception as success. This is versioned FULL001_F4_BOUNDED_REFERENCE_1; old tiny definitions and gold stay unchanged. Formal-scale reference feasibility still needs admitted host evidence.

All 24 F5/F6 source binding contracts accept actual QASPER/SciFact adapter bundles, authenticated original records, public task designs, explicit auxiliary graph rules and separately supplied private derived labels. Section extraction/reordering has exact Unicode-coordinate maps. No parser for the synthetic fixture language is used to create real labels. Blind packages omit prior labels. Real license, two-human review/adjudication, semantic neutrality of C1/C3 and reference confirmation remain pending.

Five upstream-native entry-point adapters are source-pinned in external_native_v1.json, with 13 actual AST signatures checked. TPS scope is its original tool-selection judge/parser, WorFEval its original evaluators, SemBench its movie LOTUS runner, LOTUS its four registered semantic DataFrame operators, and DocETL its DSLRunner. They do not claim complete original-paper reproduction. Existing admitted service bridges, separately locked upstream environments and licensed data are prerequisites; no new default provider/credential route is introduced.

Actual CPython/Arrow allocation events are retained, but syncing each dense-graph object separately exceeded an unchanged tiny-test deadline in WSL. Journal batching now writes every original event, synchronizes at most 1 MiB apart and at each completed artifact operation, and never accepts an unsealed crash tail. This is an instrumentation repair, not a timeout increase. The obsolete native external-sort materializing facade is disabled; direct convenience calls use the same bounded state and lazy disk handle as execution. Explicit caller-requested to_pylist/column access is outside the bounded operator path.

All six readiness flags remain false until requirement-level final-head acceptance. Formal BLOCKED_NOT_FROZEN, original N4 888 slots and approved=false remain unchanged. See PROGRESS.json for preserved CI failures, supplementary tests and current remaining work. No paid/count call, real cgroup/stress/calibration, cloud/IAM, system installation, merge or force push was performed.


### FULL001 R1 dispatch closure in progress
6cc127459ed43f0a75430a67b6dfe829c9ec0a25 rebuilt on Linux Python 3.12.14: all 2014 FULL tests and inherited native gates pass (workflow 35843955586). This remains intermediate evidence. Additional worker dispatch completion, authenticated dense encoder assets, bounded generation probes and exact-commit evidence audit are undergoing integration. Preserve 1966 b3 test IDs and bytes; no formal gate changes. Resume from docs/full001/PROGRESS.json and SOFTWARE_GAPS.json, complete final acceptance/delivery before ending total task.

### FULL001 R2 readiness and source-backed regressions

R2 accepted the post-commit offline delivery for 86d0c4db5ac508bde68cba2d17564eb6bc416de0. The preceding in-repository checkpoints remain historical; the private post-commit evidence establishes that reviewed software state. R2 continues host, service, real-source data, reference and campaign preparation with formal admission closed. The original N4 plan remains byte-identical, approved=false and 888 slots. No new host load or paid/cloud permission is implied by readiness preparation.

Actual candidate rehydration exposed insertion-order-dependent alpha identities: a multi-source plan's candidate ID changed after canonical JSON storage despite an unchanged plan hash. FULL001_REFERENCE_GRAMMAR_4 derives external and capture aliases from their actual bindings, independent of insertion order or alias names. Real official QASPER v0.3 ingestion also exposed null section names. FULL001_UPSTREAM_2 represents those as empty headings, records normalized section indices and preserves the complete original source privately. Four new R2 regression IDs cover canonical round trips, alias/capture renaming versus real edge changes, and null-heading Unicode evidence spans. Existing test IDs and protected specification/prompt bytes remain intact.

This checkpoint requires new exact-source build and affected/full acceptance evidence before inheriting software-complete status. The nine calibration checks, actual service binding/paid receipts, human labels, real reference timings and campaign freeze remain separate external evidence requirements. R2's original 150,880 NOT_RUN slot plan and all failures are retained privately; changed source identities are not silently inserted into that old plan.

Reopening the complete real-source export found a second ordering issue: QASPER's public document arrays followed source object insertion order, while canonical private JSON reordered paper keys, causing authenticated reconstruction to fail. FULL001_UPSTREAM_3 sorts paper identities during adaptation and retains original source bytes. A fifth R2 test authenticates the stored multi-paper round trip and rejects changed public content. Actual source exports are rebuilt and reauthenticated before delivery; the earlier export and reproduced failure remain private evidence.

## AUTO2-RECOVERY-R1 — 2026-09-28

The explicit user recovery delegation supersedes historical per-module approval
text within AUTO2. Continue the same two-phase task and USD100 budget root, with
a USD5 recovery subcap. The sealed initial run, unresolved request and all holds
remain intact. Recovery adds durable task dispatch fencing, phased HTTP evidence,
one conditional independent fixed-E epoch, and opt-in public request grammar v2.
See docs/full001/AUTO2_RECOVERY_R1.md. Target-environment full acceptance is being
rerun on the current source; Windows supplementary passes alone are not full
acceptance. No new calibration/formal efficiency claim or merge is made.

## AUTO2-RECOVERY-R1 real E checkpoint and independent development

Exact commit 339d2bc7 passed Linux Python 3.12.14 FULL001 CI: 2,138 tests and 270 subtests, preserving all prior 2,094 test IDs. The first independent SERVICE_ONLY diagnostic completed four actual E and four COUNT requests on the existing account/route. All eight responses were complete HTTP 200; semantic correctness was 0/4 (one non-array response and three invalid citation-coordinate responses). No new unknown send occurred; no response was manually repaired. Original unknown and USD0.251904 reservation remain isolated.

The same epoch now supports appending complete independent nonsemantic development blocks, preserving original family/method order, task lineage, dynamic P1 logical dependencies, exact body commitments, root budget and dispatch fuse. This does not reopen the original batch or create another epoch. F1's complete API upper bound fits the remaining USD5 recovery subcap; subsequent blocks must pass actual remaining-budget checks. The existing WSL host and verified CI binaries are being checked for native SERVICE_ONLY execution. Formal measurement and T_ref remain unadmitted. PR9 remains draft.

## AUTO2-RECOVERY-R1 final bounded checkpoint

The development implementation at fe934ee280c8e0ff47b932b7e82abcd354030dcd passed exact-head Linux Python 3.12.14 CI: 2,149 FULL001 tests / 270 subtests, all 2,094 original IDs retained, inherited Python 936 and native 115. Selected CI artifacts were downloaded and checked against source/build hashes and ZIP CRCs. Subsequent changes in this checkpoint are documentation only; the tested executable source closure is unchanged.

Recovery actually dispatched 5 G, 4 E and 9 COUNT requests. Fixed E returned four complete HTTP 200 responses but passed semantic correctness 0/4. The first F1 development block recorded two G2 plans with invalid scan output types, then a complete G0 P1 physical HTTP 429 RESOURCE_EXHAUSTED response. The durable facility fuse stopped the remaining nine logical trials; all 36 model execution slots remain NOT_RUN. This confirmed 429 is not a second unknown send. Original unknown and its USD0.251904 hold remain unchanged. No failed or uncertain trial was retried.

Two separate native reference correctness probes on existing WSL passed independent verification; neither is a formal T_ref or model execution. The bounded native executor exited, its task cgroups were removed, and preparation failures/claims were preserved. No new cloud VM or disk was created. Incremental recovery reservations total USD0.859557; original cumulative reservations total USD53.448623, retaining USD10 cleanup margin and the USD5 recovery subcap. Funds are not the immediate blocker: actual service capacity refusal stopped this incomplete block. Formal calibration/reference/efficiency remain unadmitted. Private PREPARATION_REPORT.md, LIVE_TEST_REPORT.md, budget continuity and sealed evidence are delivered in the separate AUTO2_RECOVERY_R1 output. PR9 remains draft.


## NEXT-LIVE-001 integration — 2026-09-28

Owner adopted the next-live instructions. New prospective REQUEST_3, exact worker-side quote citations and capacity-only bounded retries are implemented; target acceptance and actual comparison evidence remain required. See docs/full001/NEXT_LIVE_001.md. Historical outcomes and the original budget root are retained. PR #9 remains draft.

## NEXT-LIVE-002 integration — 2026-09-29

Owner adopted the attached execution task. REQUEST_4, append-only recovery
subcap extension and complete F2/F3/F4 continuation are integrated on an
isolated worktree. The prescribed 113 related tests passed on the existing
WSL Python 3.12.14. Exact-source full CI and real outcomes remain separate
evidence. See docs/full001/NEXT_LIVE_002.md. Formal admission stays closed;
no old answers, protected specification bytes or historical holds are changed.

### NEXT-LIVE-002 real execution checkpoint

The executable source at 8e9bb3f208fb2da5a9d5085863bf9a4c4add5961 passed
exact-head CI (2,219 FULL001 tests / 288 subtests) and 218 affected WSL
Python 3.12.14 tests against the verified CI native build. The existing
database received the one append-only USD15 recovery subcap extension;
the original root, epoch and all prior reservations remain unchanged.

F2 was started, but its first COUNT failed during TLS connection with
TRANSPORT_CONFIRMED_NOT_SENT. No G/E request was sent and no model plan was
executed. The original dispatcher fused; F2 is incomplete, F3 is unstarted,
and F4 also lacks the required host memory. A separate read-only handshake
diagnostic reproduced intermittent TLS EOF. No IAM error was observed.
The capacity-only retry rule has not been broadened and the fuse remains
closed pending an explicit prospective recovery decision. The ordinary-uid
executor exited and its task cgroup was removed. Current cumulative holds
are USD56.115757, retaining the original unknown and cleanup reserve.

All four old E diagnostics were audited against actual sent contexts and
source labels. Witnesses were present; extraction/annotation granularity
and incomplete multi-field support remain distinct findings, with no old
score relabeling or new E calls. Private reports preserve the raw failure,
full slot denominators, budget continuity and cleanup evidence. Formal
metrics remain null; PR9 remains draft and unmerged.

### NEXT-LIVE-002 explicitly authorized finite COUNT recovery

The owner explicitly authorized one new COUNT attempt for the proven unsent
TLS failure above. A private versioned controller passed 12 offline tests,
including one-time installation, preserved reservations and refusal of sent,
unknown, advanced-packet, altered-binding and reset-budget cases. The one
new COUNT consumed one of the original two extra attempts without raising
the whole-packet cap. The original failure and its hold remain unchanged.
The revalidated ordinary-uid worker used the same executable source/build
and data; its new boot identity was bound to the remaining scope ceiling.

The recovery COUNT returned complete HTTP 200. The first G then timed out
in WAIT_RESPONSE with zero response bytes, no HTTP status, response ID or
usage. It is SENT_UNCONFIRMED, not proof that the provider did or did not
complete generation. Its USD0.189440 hold is retained and it was not retried.
The durable dispatcher fused again. F2 has one unresolved logical attempt,
11 unstarted logical slots and all 36 native slots NOT_RUN; F3 remains
unstarted. F4's separate frozen-profile memory shortfall also remains.

The current cumulative conservative reservations are USD56.305198;
USD11.283868 remains under the same USD15 recovery subcap. The original
root, epoch, all earlier reservation rows and both unknown holds are retained.
Actual invoice cost and provider active-request count are unobservable.
The task is PAUSED_EXTERNAL. The worker exited, task cgroups were removed,
and the original claim-ledger ownership was restored. The initial sealed
checkpoint is intact; a separate recovery checkpoint preserves raw evidence,
controller provenance and the explicit authorization. Executable source and
its exact CI remain unchanged. Formal metrics stay null; PR9 stays draft.

### HTTP_TIMEOUT_3 prospective independent continuation

The owner explicitly adopted retention of both unknown requests and their
holds, no retries of either, and resumption of fresh independent F2 slots
followed by the original independent F3. HTTP_TIMEOUT_3 separates 20-second
connection operations from G's 600-second absolute HTTP budget and adds a
720-second physical-call process watchdog. COUNT retains its 90-second HTTP
budget; new E is not admitted. A one-time append-only recovery decision
binds the fresh-slot allowlist, new execution identity and remaining budget.
Any new unknown stops again; old provider activity remains unobservable.
See docs/full001/TRANSPORT_003.md. Exact-source CI, WSL acceptance and actual
future calls are separate evidence. Existing unknowns have not been retried,
and no new live dispatch is claimed by this implementation checkpoint.
