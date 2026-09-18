# RCWG-BOOT-001 验收表

| 门禁 | 标准 | 交付时状态 | 谁补齐证据 |
|---|---|---|---|
| G0 来源与仓库基线 | 初始远端真实读取，归档及成员hash | PASS；远端写入403 | Work复核，Codex导入 |
| G1 BOOT核心 | 单元测试、mock、hash/数量、安全默认值 | 交付方Python3.13.5通过 | Codex在3.12重跑 |
| G2 本机环境 | WSL doctor、解释器、容器可用性 | PENDING | 用户 |
| G3 目标容器 | 构建成功，网络关闭mock，记录digest | PENDING | Codex/用户批准的构建环境 |
| G4 公共仓库 | 公开范围与秘密扫描，独立commit/PR | PENDING；当前主分支未改 | 用户+Codex |
| G5 云端 | 一次外层工作流，私有GCS产物，受控账单 | PENDING / NOT_EXECUTED | 用户 |
| G6 API | 提供商/region/模型/价格确认后一次请求、usage记录 | PENDING / NOT_EXECUTED | 用户 |
| G7 正式门禁 | 旧/新协议与模型/数据/执行器/计量全部冻结 | BLOCKED_NOT_FROZEN | 后续工作包 |

## 提交给研究负责人的记录格式

```text
Ticket:
Environment: (owner WSL / CI / Docker / cloud)
Python exact version:
Git commit:
Commands and exit codes:
Tests count and result:
Reference hash check:
Image base digest / application digest:
Cloud execution and artifact hash:
Model requested/reported version and usage:
Actual cost evidence / unknown fields:
Unresolved items:
```

每个环境只填写自己实测的结果。共享前检查账号、路径、IP、密钥与隐藏数据；公共PR可以记录脱敏摘要，私有原始证据另存。后续验收通过时更新本文件与PROJECT_STATE，保留历史状态和时间。
## 本地验收进展 — 2026-09-19

原始交付状态保留在上表；本节仅追加带日期的进展证据。

| 门禁 | 更新后状态 | 证据 |
|---|---|---|
| G1 BOOT 核心 | PASS（用户 WSL / Python 3.12.14） | unittest 43/43；日志 hash 见 PR #1 |
| G2 本机环境 | 已采集（doctor） | 新 doctor：python 3.12.14；docker/gcloud 仍不可用 |
| G3 目标容器 | PENDING（延后至首次云部署前） | — |
| G4 公共仓库 | PR #1 已建立 | 见 PR #1 |
| G5 云端 | DEFERRED_BY_OWNER | 保留门禁 |
| G6 API | NOT_EXECUTED | 后续 API 票 |
| G7 正式门禁 | BLOCKED_NOT_FROZEN | 不变 |
