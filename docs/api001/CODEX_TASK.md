# RCWG-API-001 — Codex 工作交付与首次真实调用任务

2026-09-19。工作分支 `rcwg/api-001`。研究设计与以下实现决定已批准。本票继续已有 API→静态编译→F1 supervised execution→独立验证路线。先读本文件、DECISIONS.md、ACCEPTANCE.md、GOOGLE_CLOUD_CODEX.md。

## 0. EXEC 基线审核与有条件合并批准

精确受审 PR4 head：`55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278`；tree：`7763db9b757488e393fb4b4d8552c2daeafcecde`。PR2/3 已实时核实 merged，无需重新导入。PR4仍draft。

独立审查实际取得 GitHub CI artifact 10585831284/run35448121656：708通过、34固定运行case无偏离、5算子/8分支、212项源码前后散列映射一致；已下载的47个登记日志重新哈希通过。CI未包含全部运行产物与用户WSL私有交付，X15明确为 EXTERNAL_DELIVERY_PROOF_REQUIRED。请在现有本机 outputs/RCWG-EXEC-001_最终交付.zip 中读取对应证明，**实做**清单/WSL日志/补丁clean-apply/212受测文件字节检查，不替换为一句声明，也不要向ChatGPT索要不存在的本机C:访问权限。

若上述证明实际通过，且实时PR4 head仍精确匹配、CI成功、无未审冲突，本文件批准将PR4 ready并以merge commit合并，无需再次等待同一确认。可用既有授权本机gh：

```bash
gh pr view 4 --repo zhixuanliu867-ship-it/RCWG --json headRefOid,isDraft,mergeStateStatus,state,statusCheckRollup
# 完成上述实查后：
gh pr ready 4 --repo zhixuanliu867-ship-it/RCWG
gh pr merge 4 --repo zhixuanliu867-ship-it/RCWG --merge --match-head-commit 55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278
```

不使用force/reset/clean、管理员绕过或squash。新head不自动继承批准。若唯一障碍为真实权限失败，可以精确受审head为起点stacked开发，标明BASELINE_MERGE_PENDING；LIVE之前必须补齐X15和正确基线。

## 1. 导入本轮实现

ZIP中的 `API001.patch` 是**纯新增文件**补丁；`overlay/`保存相同新增字节。不要重复应用EXEC旧补丁，不把整个overlay覆盖原受测文件。备份/保留当前工作区，检查干净，再建立工作分支。执行：

```bash
git apply --check /实际解压路径/API001.patch
git apply --index /实际解压路径/API001.patch
uv run --offline --frozen --python 3.12.14 python -c 'from rcwg_api.policy import check_exec_sources; print(check_exec_sources())'
```

98个runtime源文件pin来自精确PR4的CI证据。pin失败时核对基线，禁止简单重新计算pin来掩盖未审改动。旧708方法ID、27哨兵、6突变和源测试字节保持。新增92方法仅作为当前必需集合，允许增加真实回归，不允许删除检查以凑通过。

当前API工程代码已经实现，优先复核/验收和修正真实问题，不另写一套SDK或另造mock协议。

## 2. A阶段：目标WSL与独立CI（零真实模型调用）

```bash
uv run --offline --frozen --python 3.12.14 python scripts/accept_api001.py --output runs/api001-owner-唯一新标识
```

目标入口会先运行完整 `accept_exec001.py`，再运行API机器测试和**supervised** mock-wire闭环。既有完整EXEC gate要求工作区/暂存字节一致，所有计划交付文件先审查并暂存；runs/和凭据不入Git。目标通过状态是 `API001_TARGET_OFFLINE_PASS`。`--review`仅供交付方不同环境复核，不能作为LIVE授权。

应保留既有708+本包92=800个必需方法（若新增修复测试，实际总数可以更高）。本轮ChatGPT没有在完整55a代码树上运行800项，不能复制该数字为已测结果。

把API目标入口接入CI，保留原EXEC入口、原artifact处理或等效日志。不在CI放模型/GCP凭据；仅保存去敏的离线证据。配置CI本身可以变更，但其最终source和暂存/hash证据都需重跑。检查py_compile/public guard/bash（如新增）和补丁干净应用。每项原始命令、实际解释器、退出码单列。

生产 `run_pilot(..., mode='LIVE')` 固定使用 VertexTransport 和真实 run_f1_supervised；不能注入reference/fake执行器。新的普通unit tests使用隔离替身或旧reference仅检查协议，不等于完整target gate。

## 3. B阶段：Google Cloud 只读准备与批准

让用户只提供明确Project ID、可用runner SA或对其创建方案的批准、global模型路由与1美元pilot授权。不要要求聊天中粘贴API key、refresh/access token或服务账号JSON key。核对账户/项目/已启用API和限额；不扫描所有组织或其他项目。

已有gcloud时直接使用，无需先装MCP。缺少gcloud/必要API/runner权限时，列出精确安装路径、待启用服务、待创建身份与最小授权对象，交所有者一次批准后执行；这属于账户/系统变更，不能冒充“动作0”。只授权调用推理的runner，不给Owner、Editor、IAMAdmin。具体认证与MCP说明见GOOGLE_CLOUD_CODEX.md。

本轮批准范围只包含F1文本推理pilot：上限3次generateContent+3次countTokens，串行，零自动重试；凭据签发单独记录。不给Cloud Run部署、VM创建、Workflows执行、存储公开化或IAM任意修改权限。

`configs/api001/codex-gcloud.example.toml` 默认disabled，只是可选工具配置。固定package版本和安装完整性须先核实，不能用latest。不复制覆盖整个 ~/.codex/config.toml，不因用户打开MCP而把工程预算开放为无限调用。

## 4. C阶段：准备/批准/一次真实pilot

A阶段最终源代码不再变化后运行prepare，填写真实项目与现有SA：

```bash
uv run --offline --frozen --python 3.12.14 python -m rcwg_api prepare \
  --project YOUR_PROJECT_ID \
  --service-account rcwg-api-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --output runs/api001-live-唯一新标识
```

WSL必须使用代理时，仅在审查现有HTTP(S)_PROXY后加入 `--allow-environment-proxy`。不改系统代理，不关闭TLS，不记录代理密码。

prepare产生公开开发fixture、预期两次generation清单及 `approval.template.json`，真实请求仍为0。所有者确认后，将批准内容独立保存为 `approval.json`：approved/data_location_approved/pr4_delivery_proof_verified均必须有真实依据；填最终API target ACCEPTANCE.json的SHA256、24小时内费率核实时间、≤24小时有效期、owner_note。模板默认false；Codex不得自行补造批准。

随后由用户本机授权会话执行一次：

```bash
uv run --offline --frozen --python 3.12.14 python -m rcwg_api live \
  --prepared runs/api001-live-唯一新标识 \
  --approval runs/api001-live-唯一新标识/approval.json \
  --offline-acceptance runs/api001-owner-唯一新标识/ACCEPTANCE.json \
  --ack-paid-model-requests
```

保存stdout到新的私有日志（不要set -x）。budget SQLite保留，不可删除以重置。超时/429/403/截断/usage缺失/版本漂移/不支持计划都保留真实结果，遇停机原因不重试。P1第二阶段以原始逻辑返回组装，不用固定正确答案。生成计划语义失败照常交独立验证；不为了通过改prompt后悄悄覆盖本轮。

## 5. D阶段：独立只读LIVE复核与结票

```bash
uv run --offline --frozen --python 3.12.14 python scripts/review_api001_live.py \
  --directory runs/api001-live-唯一新标识/observations \
  --manifest-sha256 准备阶段实际值 \
  --seal-sha256 LIVE输出实际值 \
  --output runs/api001-live-review-唯一新标识
```

如果尚无模型权限，交付 `API001_TARGET_OFFLINE_PASS / LIVE_BLOCKED_CREDENTIALS`，不要宣称整票完成或mock为live。若三个真实生成阶段全部记录且至少一份模型计划实际完成监督执行，独立核对后可以登记 `API001_LIVE_F1_ENGINEERING_ACCEPTED`；答案PASS/FAIL是另一字段，不能强求模型答对才记录接口可用。

交付：可读报告、机器证据、分开的WSL/CI/LIVE日志及SHA256、源码与完整补丁clean-apply/tree证明、请求/试次/执行重复台账、预算预留/usage估计/真实账单各自状态、API版本/模型标识、运行与失败案例、实际新增GCP配置动作、CLOUD-001/NATIVE-METROLOGY下一票接口。PR保持draft待独立复核。隐藏数据/recipe/真实输出/审批文件、budget和token不推公开Git。

## 6. 完成定义

A00–A15逐项证据见ACCEPTANCE.md。API工程离线、目标环境、真实服务、正式benchmark四类状态独立；formal_run_enabled及formal_ready保持false。无需重复批准常规实现决定，模型/金额/地区/权限扩展必须单列新决定。
