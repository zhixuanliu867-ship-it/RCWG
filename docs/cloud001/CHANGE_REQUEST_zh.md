# RCWG-CLOUD-001 精确变更单 v1（等待批准）

项目 `rcwg-509116`；操作者 `zhixuanliu867@gmail.com`。本单 SHA256：`68f11740c7242475c2926025cf4bef22495a9877a49bc9503abb069ccf7ffd0c`。
当前 approved=false，尚未创建云资源、变更 IAM 或发起新模型请求。批准有效期拟为确认后 7 天；价格核查有效期另限 24 小时。

## 本次一次性批准的范围

- 区域 **us-central1**，模型位置继续 **global**。
- **5 美元工作额度**：模型 1 美元、基础设施 4 美元，纳入已有 150 美元工作包络。它不是 Google 账单硬限额；未假设免费额度或剩余赠金。
- 仅启用 `artifactregistry.googleapis.com`、`cloudbuild.googleapis.com`、`run.googleapis.com`、`workflows.googleapis.com` 四项 API。
- 新建私有桶 `rcwg-509116-cloud001-private`（STANDARD、uniform access、禁止公共访问）、镜像仓库 `rcwg-cloud001`、Jobs `rcwg-cloud001-replay` / `rcwg-cloud001-live`、Workflow `rcwg-cloud001`。
- 每个 Job 2 vCPU / 4 GiB、1 task、并行 1、重试 0、600 秒，各仅执行一次。两个 Job 使用同一镜像 digest。构建最多 2 次，每次 900 秒；工作流手动触发共最多 2 次，不自动重新派发。
- 新建下面三个服务账号与五个项目自定义角色，只绑定表列作用域。用户既有 Owner 不变；不创建长期密钥。

| 身份 | 权限与精确作用域 |
|---|---|
| `rcwg-cloud001-orchestrator` | `run.jobs.run`、`run.executions.get`，仅绑定上述两个 Job；无运行参数覆盖 |
| `rcwg-cloud001-runtime` | 项目内 `aiplatform.endpoints.predict`、`serviceusage.services.use`；私有桶 `cloud001/` 前缀下只读；仅 claims/reservations/output 三个前缀允许创建对象，无删除/覆盖权限 |
| `rcwg-cloud001-builder` | 仅本镜像仓库 `roles/artifactregistry.writer`；仅桶 `cloud001/build/source/` 对象读取；项目 `roles/logging.logWriter` 与 `serviceusage.services.use`；不读取模型原文，不调用模型 |

五个角色 ID：rcwgCloud001ObjectRead、rcwgCloud001ObjectCreate、rcwgCloud001JobRunner、rcwgCloud001Predict、rcwgCloud001ProjectUse。逐权限定义与 10 条绑定见同目录 JSON。API 启用/首次使用可能自动产生 Google 管理的服务代理及标准服务代理绑定，逐项留前后证据；额外手工宽权限授权不在本单内。绑定不会自动到期或自动撤销。

## 执行顺序与新模型授权

1. 批准后启用四项 API，再只读确认区域/配额、资源名冲突和服务代理。任何冲突或组织策略阻断均停止，不扩大项目/身份/权限。
2. 构建固定 Python 3.12.14 / linux-amd64 镜像；上传源采用干净提交白名单，排除 runs、.venv、私人批准、凭据、真实响应和交付 ZIP。
3. Workflows 提交一次 replay：不调用模型，旧 P0 原样执行并核对结果 hash，旧 P1 原样静态拒绝；GCS 独立重读通过后才进入下一步。
4. 本单同时申请 **一个全新的云端批次，最多 3 次生成 + 3 次计数、串行、零自动重试、模型额度 1 美元**。模型固定 gemini-3.1-flash-lite / global；实际新 manifest、公共提示 hash、镜像 digest、C1 证据和 24 小时内官方价格核查全部冻结后才发起。技术条件不足不等于验收通过，也不自动追加调用。
5. 云端以自己的服务身份取得短期令牌。GCS 固定票据 claim 与 6 个固定槽在 HTTPS 前条件创建；进程死亡、超时、丢失响应都保留 UNKNOWN 和预约，不换目录/manifest 重置。

## 已核实与尚未知

- 项目 ACTIVE、当前账号真实 Owner、结算启用；用户管理服务账号与本项目存储桶列表均为空。
- 四项目标 API 未启用，故对应资源列表、us-central1 项目配额尚未查询；不能断言没有历史资源。全局桶名可用性待创建前核查，冲突即停。
- 当前项目累计账单、可用赠金未获得；结算启用不代表余额充足。现有账单不会伪填为 0。
- 已查到固定基础镜像和构建器 digest，尚未远程构建；输出 image digest 暂为空，不用源码 hash 冒充镜像 hash。

## 费用、停止与保留

按公开价格，两个 Job 各运行 600 秒的配置计算量约 $0.0528，两次 15 分钟 E2_STANDARD_2 构建约 $0.18。启动/结束计费时长、Workflows 计费步数、镜像与 GCS 保留、日志、网络及税费另计；这些是规划估算，实际账单尚未知。最多 6 次模型请求预约共 $0.78，模型上限 $1。

本轮允许在出现异常时取消本票正在运行的 build/job/workflow 以停止继续消耗；不删除证据。新增重跑或扩大额度需要新的具体批准。存储保留 30 天后复核，不加不可逆 retention lock，不配置自动删除；删除资源/撤销绑定需另列清单批准。正式门禁持续 BLOCKED_NOT_FROZEN，内部 F1 的 128MiB 资源可行性仍未验证。

官方依据：[Cloud Run 价格](https://cloud.google.com/run/pricing)、[Cloud Build 价格](https://cloud.google.com/build/pricing)、[Workflows 价格](https://cloud.google.com/workflows/pricing)、[GCS 条件创建](https://docs.cloud.google.com/storage/docs/request-preconditions)、[自定义构建身份](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)。
