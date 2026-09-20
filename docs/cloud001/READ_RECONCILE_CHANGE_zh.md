# CLOUD-001 现有执行只读恢复变更单

变更单 SHA256：`7fa01aac5258661c1c027f5ce51a2d5b1dc2b0ed4b900a70673d7b4632096581`。源文件 SHA256：`3a18838fa49023a440ecdacb35663bba0f41b479a5c510d8799941ab49157e85`。

原 LIVE Workflow 在提交 Job 后读取状态时收到 run.executions.get HTTP 403。
Job `rcwg-cloud001-live-mfrgz` 已成功结束，GCS 封存存在；原失败记录保留。
两个 Job 的窄角色绑定均已实际读回；IAM 传播延迟只是待验证解释。

仅在原项目 rcwg-509116、us-central1，用原 Windows 账号与原 orchestrator 身份：

1. 将现有 rcwg-cloud001 Workflow 更新为随附只读源码。
2. 额外执行这一个 Workflow 一次。源码没有输入参数、POST、Job 提交、模型端点或重试，只有一个固定现有 execution 的 GET。
3. 保存原身份返回的实际终态；失败就停止，不扩大权限。

不增加 Job 执行、构建、模型调用、IAM、API 或资源。沿用 4 美元基础设施额度，
本步规划预留 0.01 美元，非账单保证；总工作额度仍为 5 美元。
原变更单限制 Workflow 共 2 次，现已使用；本补充仅将其放宽至 3 次。
这次只读恢复成功也不会把原 LIVE Workflow 的 FAILED 改成 SUCCEEDED。

审批前不更新云端 Workflow，不触发额外执行。正式门禁保持关闭。
