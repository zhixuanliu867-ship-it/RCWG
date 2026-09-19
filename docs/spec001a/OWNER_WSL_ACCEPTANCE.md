# SPEC-001A 用户 WSL 导入与修订验收

日期：2026-09-19。状态：**OWNER_WSL_ACCEPTANCE_PASS**。范围：离线工程验收。

## 来源与实际环境

原补丁从 main `08b1ecff33ab01098926e3dceba64ab6ab4fa02c` 干净导入独立分支 `rcwg/spec-001a`。
原导入提交 `cb95a5a2ba6367509e230b531606cc1598479e19` 的 tree 为 `408a7968efe9938a49b2a256a54232058d2b99a2`，
121 个跟踪文件与上传 ZIP 逐字节一致。原交付方 Python 3.13.5 证据保留于 `evidence/spec001a/`；本报告记录新的用户 WSL 实测。

Ubuntu 26.04 LTS / `6.6.87.2-microsoft-standard-WSL2` / 32 逻辑核 / Python **3.12.14**。
所有验收 Python 命令通过 `uv run --offline --frozen --python 3.12.14 python …` 执行。
系统默认 Python 未用于验收；未安装依赖、未改系统配置或全局 Git 代理。

## 复核修订

1. 严格 JSON 读取拒绝 `1e400`、`-1e400` 等溢出为无穷值的数字，保留有限正负 JSON 数字。
2. 评分入口先验证对象与字段；null、数字、数组、缺字段或未知字段返回结构化错误与退出码 2，不产生输出文件或未捕获 traceback。
3. OOM、超时及其他未完成状态的已用时间不再计算为完成时延比；确认的计划失败仍计 0，设施不确定状态仍保留 unknown。
4. 公开仓库 guard 增加 GitHub Token 形状和 `.venv/` 检查；始终检查 Git 暂存字节，工作区删除文件也不能隐藏已暂存内容。GitHub CI 增加该 guard。真实凭据未写入仓库；测试仅构造无效占位值。

新增 14 项回归测试先在原实现上运行：14 个方法、23 个失败子用例，退出码 1。修订后原 117 项和新增 14 项合计 **131/131 通过**。子用例不计入方法总数。

## 验收

| 项目 | 结果 |
|---|---|
| 原交付 WSL 验收 | 117/117 PASS |
| 修订后 WSL 验收 | 131/131 PASS |
| BOOT / SPEC | BOOT_CHECK_PASS / SPEC001A_CORE_PASS |
| smoke / API probe | PASS / mock PASS，真实模型请求 0 |
| formal | BLOCKED_NOT_FROZEN，退出码 2 |
| 新 doctor | Python 3.12.14；formal_ready=false |
| cgroup 只读探针 | 已采集；formal_isolation_verified=false |
| 原件保护 | 33 参考文件原字节保留；32 算子 / 72 模板 |
| 仓库 guard / compileall / bash 语法 | PASS |
| 公共仓库私有路径 | runs/ 与 .venv/ 未跟踪且保持忽略 |
| Docker / gcloud | UNAVAILABLE_OR_PERMISSION_DENIED / 不存在，均未修改 |

原验收目录：`runs/spec001a-owner-20260919T095453Z-2998`。修订后目录：`runs/spec001a-owner-20260919T095950Z-3473`。
原始输出留在被忽略的 runs；本目录 JSON 仅登记文件散列和必要摘要。新 doctor SHA256：`00b73d896dc69d8e63f871ef372071906694f75af503ecf49eb579543a5fbc88`。
测试代码文件清单摘要：`2e9c535c7f7d6a611f4bf9d33945c64a6ad8fb0c50e6892659e1488c01b2367e`；完整逐文件散列见 `evidence/spec001a-owner/ACCEPTANCE.json`。
该摘要绑定受测代码和配置，后续只有状态/报告文档变动时无需将文档提交冒充一次新的代码测试。

## GitHub 与下一阶段

GitHub 连接器创建分支实测返回 403；仓库元数据的 push 权限不等于该集成具有写入能力。
远端推送、PR 和 CI 结果在交付报告中按实际另行登记，不能用本机结果代替 CI。
保留 main 供 PR 审查；旧 `rcwg/spec-001` 草案分支不改动。

SPEC-001A 的目标环境验收完成。下一工作包为 SPEC-001B：完整 WorkIR 静态验证、类型/引用/作用域/资源检查、P0/P1 输入组装与 gold 隔离、32 算子契约覆盖矩阵、计划/数据/预算/运行环境证据绑定；之后 EXEC-001 实现首条 F1 真实 WorkIR 执行闭环。
当前仅有 F1 TaskInput 有限 profile 和离线计算核；完整验证器、32 算子执行内核、自动事实判真及正式统计分析均未声称完成。
真实模型请求、云资源创建、IAM 变更均为 0；正式门禁保持关闭。
