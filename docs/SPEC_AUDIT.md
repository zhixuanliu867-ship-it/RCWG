# 源规格审计与差异登记

## 来源与一致性

读取了两个明确选定的源 ZIP，未宣称盘点全部 Library。归档及所有成员的字节数、SHA256 见 `provenance/SOURCE_INVENTORY.json`。机器规格 25 个文件导入 `specs/reference_v1_0/`；新提示词 8 个文件导入 `prompts/v1_1/`。最新完整设计书、流程图和历史研究文档留在原私有来源中；其归档成员 hash 可用于定位原件。

旧规格的自带 `checks/validate_specs.py` 在交付方环境中通过了两个 WorkIR top-k 样例和正式矩阵算术检查。它使用交付环境已有的 jsonschema 4.26.0。BOOT核心程序不依赖此库；该次结果不等价于完整运行时实现或 schema 覆盖证明。

## 待处理差异

| 编号 | 已观察到的事实 | 处理方式 |
|---|---|---|
| D01 | 旧配置指向本地权重/vLLM与A6000硬件；用户本次选择API | 原件不覆盖；按 API_ENV_AMENDMENT 新建适配与服务冻结表 |
| D02 | 原机器规格只有 workflow/artifact/event/evidence schema；包含 TaskInput 样例，未提供独立 TaskInput schema 文件 | WP1 补齐 TaskInput 1.0 的机器可验收契约与边界样例 |
| D03 | 新旧提示词同时存在 | 新表达版放 prompts/v1_1；输入组装器实现后核查语义一致性并冻结所用hash |
| D04 | 原网络门禁为 network_in_primary_execution=false；API生成/语义调用需要外部访问 | 明确生成器、固定语义服务与计算worker的网络域及白名单，按版本登记 |
| D05 | 旧模型列表含 UNRESOLVED revision/template 等 | 按具体API提供商能力冻结；缺失信息标不可获得，不编造权重hash |
| D06 | 旧32算子卡与72模板是设计资产，尚非完整可执行系统 | WP2/WP4继续开发；BOOT固定夹具标记工程验收 |
| D07 | 原正式worker存在进程树/服务组计量要求 | 原规范保留；受控Linux正式计量另做隔离校准和门禁 |
| D08 | 仓库公开，源材料包含研究规格与提示词草案 | 所有者审查公开范围与许可证；隐藏gold和真实输出保持私有 |
| D09 | Python目标3.12；交付方可用环境3.13.5，无Docker，容器网络无法解析GitHub | 本地已有结果如实登记；WSL、3.12、Docker与云验证分别待办 |

## 数量检查

32 个算子卡、72 个任务模板、480 开发条件实例、960 正式测试条件实例，6 个生成模型槽位，P0/P1，尝试种子编号17/29。原设计生成尝试23,040；核心执行尝试上限61,440（诊断、隐藏夹具和参照另外计数）。本轮保留这些字段，不把固定BOOT夹具数写回正式campaign。

## 自带验证工具的使用

目标环境后续可在得到依赖安装批准后单独运行：

```bash
uv run --with jsonschema==4.26.0 python specs/reference_v1_0/checks/validate_specs.py
```

此命令的临时依赖不属于零依赖 `uv.lock`。在其进入正式门禁前，Codex应将完整传递依赖加入专门锁文件并审核；当前 BOOT 完整性检查验证原件hash、数量与安全默认值，不冒充完整 JSON Schema 验证器。
