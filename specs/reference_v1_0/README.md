# RCWG 1.0 设计附件

这是两份设计文档的机器可读配套规范，不是已完成的benchmark或模型实验。

- schemas：WorkIR结构约束；算子专有参数语义仍须按设计书实现并测试。
- configs：正式矩阵、模型与资源候选配置；UNRESOLVED字段禁止正式运行。
- prompts：可编辑模板；冻结后须记录SHA256。
- catalogs：32个逻辑算子、72个任务模板目录。
- examples：两个合法结构的精确top-k示例；不是正式测试数据。
- checks：结构、依赖及数量一致性检查，不执行工作流。
- sources.json：公开来源与证据等级；含历史讨论保留项。

验证附件：`python checks/validate_specs.py`（需要jsonschema）。
正式执行器、控制台、完整数据和论文复现尚未交付。本文档不是对此的完成声明。
