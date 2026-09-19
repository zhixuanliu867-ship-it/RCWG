# RCWG-SPEC-001B 实施决策与接口契约

日期：2026-09-19。状态：DESIGN_APPROVED / IMPLEMENTATION_STARTED。
依据：PR #2 head `6afd48490094d716dc65cf84fe822e45216fcac3`；SPEC-001A 决策；原 WorkIR 1.0、正式实验设计书流程详解版 v1.1 §6/8；本轮实际代码复核。
本文件为新实施决策，补齐原稿未固定的具体字段/引用语法；不把这些新增细节声称为原稿已有全文。研究问题、主比较、32 算子、72 模板、6 模型槽和正式规模保持原值。

## 1. 工程基线与交付层次

SPEC-001A 的 131 项测试、33 份保护原件与安全门禁构成本票回归基线。保留 Codex 的指数溢出、评分异常、未完成运行时延和暂存内容扫描四类修复。
本起始补丁已提供 `ir_structure.py`、`identity.py` 与 63 项单测，合计 194 项。它们只完成结构/词法依赖和身份构造；完整编译器尚未实现。
`STRUCTURE_PASS`、`SPEC001B_FOUNDATION_PASS`、`SPEC001B_SENTINELS_PASS` 均不得当作 `SPEC001B_ACCEPTED` 或正式可运行。

## 2. 完整编译器的公开函数

Codex 实现 `rcwg_spec/compiler.py`：

```python
def validate_workflow(task: dict, plan: dict, *,
                      stage: str = "primary_execution") -> dict:
    ...
```

成功报告最少包含：

```json
{
  "status": "IR_VALIDATED",
  "profile": "RCWG_WORKIR_1_0_SPEC001B",
  "canonical_plan_hash": "<真实内容SHA256>",
  "task_input_hash": "<真实内容SHA256>",
  "diagnostics": [],
  "typed_graph": {},
  "runtime_obligations": [],
  "readiness": {"runtime_kernels": "NOT_IMPLEMENTED"},
  "formal_ready": false
}
```

失败分类：`INPUT_INVALID` 为任务包/设施输入缺陷；`PLAN_INVALID` 为提交计划可确定的违约；`IMPLEMENTATION_GAP` 为合法协议特性在设施中尚未实现。每条诊断含 `code`、`stage`、JSON Pointer `path` 和脱敏说明。程序内部 bug 不能捕获后伪装成模型错误；独立报告 INTERNAL_ERROR 并阻止发布。
完整编译流程：严格读取 → TaskInput 及来源 → WorkIR 结构 → ID/引用/作用域/合并依赖 → 算子实现/端口 → 参数与谓词 AST → schema/类型 → 前置条件与资源 guard → typed graph。
CLI 建议新增 `python -m rcwg_spec validate-workflow --task TASK --plan PLAN --output REPORT`；保留旧 CLI。
静态成功仅表示通过已实现的静态检查；无真实执行内核时 readiness 明确阻止运行，勿因缺少运行内核让所有合法 IR 都变成 PLAN_INVALID。

## 3. 结构、作用域与控制区域

保持 WorkIR `ir_version=1.0`，保护源 schema 与样例字节。新增约束/文档放 spec001b，不覆盖 source。

- 根输入：`$input.alias`；节点输出：`node.port`。
- region 内显式绑定：`$bound.alias`。`bindings` 右端在父作用域解析。map.body 可将 `$item` 绑定到一个别名；loop.body 可将 `$state` 绑定到一个别名。
- 节点 ID 在每个词法作用域唯一，图身份采用 `root/controller:body/node` 等 scope-qualified ID。同名局部节点可出现在不同分支；未绑定的外层引用与兄弟区域穿透均非法。
- 根节点数组与所有嵌套区域递归计数合计不超过 48；region 最大嵌套深度为 2（根为 0）。4096 是动态节点实例总计数上限；16 是循环迭代上限。schema 的局部长度检查不能替代递归总量检查。
- 数据输入、after 与 region 捕获共同构造依赖。forward reference 可合法；node 列表顺序不是依赖顺序，仍必须保留序列化顺序供调度策略使用。
- map/loop 恰好有 body；branch 恰好有 then/else。空区域可以直接 yield 一个已绑定值。yield 的端口集合必须与控制节点输出一致。
- `analysis_topological_order` 仅用于分析，不能暗中替换模型的算法、增加排序/物化或改变调度优先级。

控制语义：map 逐条消费有限 Record stream，`$item` 为一条 Record；body yield.rows 为 Record[T]，外层 rows 为 Stream[Record[T]]。branch 两臂 yield 按已批准类型合并，不插入数值或表示转换。loop 使用 state:T → state:T 的不变式；condition 为“继续循环”的布尔 AST，检查初始状态并在每次更新后检查。最后允许迭代后 condition=false 可完成；true 则 LOOP_LIMIT_REACHED。
map 局部并行使用 resources.max_parallelism；全局 CPU admission 对所有实际节点统一计数，不能靠嵌套乘出额外 CPU。

## 4. 类型、端口与必要的兼容解释

类型核心采用 SPEC001A 的带 schema 代数。具体实现可用不可变 dataclass + 显式统一规则。类型变量由已验证的 public data schema 及上游输出推导；模型输出中的裸 `Table`、`Stream[Record]` 等旧声明是待核对的表示约束，绝不是逃过字段验证的 Any。

新增端口与参数决策在 `specs/spec001b/operator_contract_worklist.json`。其中 prose type strings 是实施工作清单，尚未充当可执行类型系统。

为使已有任务链可组合，批准下列显式 overload；Codex 将每个 overload 独立测试和登记，不静默插入转换节点：

1. `RowReadable[S]` 是编译期只读接口，包含 Table[S]、Stream[Record[S]] 和带行 schema 的 EvidenceTable。filter/project/deduplicate 可以直接处理这些表示并保持输入表示；对 Table 的原生操作不等于隐式转 Stream。
2. Graph[G] 与 GraphView[G] 只读匹配 GraphReadable[G]，G 包含同一图的标识/修订/schema。不同图的 NodeSet 不能合并匹配。
3. `ReadableArtifact/ReadonlyArtifact` 是受管对象的生命周期接口，允许命名的 Table/Stream/Graph 输出带句柄元数据被显式 stream_read/broadcast/cache/release 消费。不能解析任意 URI 或把输入文本当路径打开。
4. IDSelection[D] 是显式文档 ID 域选择；IDSet、RankedIDSet 可匹配。单列 Table 需要显式 id_field 和已公开的文档 ID 域映射。图节点 ID 到文档 ID 的关系通过声明的表/关系操作提供，不自动等同。
5. broadcast 的 consumers 为唯一合法标识符列表；输出端口使用对应标识符（每消费者一个 Ref），避免增加无登记的数组索引/选取算子。
6. graph_subgraph induced 用 nodes，edge_selected 用 edges；结果语义及输入不能混用。
7. 显式 Table→Stream 用 stream_read；Stream→Table 用 materialize/collect。现有 top-k 两实现内部都读取输入并生成 Table，此内部算法行为按实现计量。

端口、必填参数、条件参数、别名、前置条件形成真实注册表。每个 operator/implementation 均须查真实 schema 及类型推导函数，不允许仅查名称 enum 后输出 VALIDATED_CONTRACT。

## 5. 参数与 AST

参数 object 采用白名单；未知参数返回 PARAMETER_UNKNOWN，缺少参数返回 PARAMETER_REQUIRED。
类型不符/范围越界/枚举不符分别采用 PARAMETER_TYPE、PARAMETER_RANGE、PARAMETER_ENUM。未知字段为 FIELD_NOT_FOUND，端口不符 PORT_MISMATCH，类型统一失败 TYPE_MISMATCH。

有限 AST：`{field: name}`、`{literal: scalar_or_scalar_list}`；二元 `{op, left, right}` 的 eq/ne/lt/le/gt/ge/in/add/sub/mul/div；布尔 `{op:and|or,args:[...]}`、`{op:not,arg:...}`；is_null、count 采用 arg。每种节点字段封闭，最大深度/大小受 JSON guard 控制。字段/算术类型由 schema 检查。bool 不当作 Int64；三值布尔 unknown 有明确规则；除零和动态溢出留作运行时义务。使用解释器，禁止 eval/exec/脚本执行。

同源非空标量排序可沿用旧 keys；nullable keys 需要显式 nulls=first/last。输出映射不通过“输出类型字符串是 Table”掩盖 missing field 或错误 schema。

## 6. 资源与正确性：三类情况明确分开

静态非法：单节点 cpu_slots 超公开全局上限、环、非法区域、负 k、错误端口、元数据已证明不满足的算法前提。
运行时义务：峰值内存、数据相关实例数、数据相关非负权/排序、限定跳数语义、真实读取/复制/背压、晚出现的 provenance 与结果完整性。
合法且可能低效/答错：full_sort 在小内存条件下、遗漏筛选但仍类型完整的计划、顺序执行可以但成本高。它们通过静态类型后，保留给真实执行/独立 verifier 计入相应结果。

不能把所有节点声明 CPU 相加而拒绝可由 ready queue 顺序执行的计划。不能把估计内存/估计选择率当真值。展开实例大于预算的“可能上界”触发运行时 guard；只有不依赖数据、可证明的必然违约才静态拒绝。动态实例计数累积，串行释放并不归还实例数预算。

## 7. TaskInput 与 P0/P1

保持旧 `validate_task` 的有限 F1 profile 和所有原测试。新增全族 public profile：表/图/文档索引/显式ID选择的 schema、数据修订、公开统计/索引、资源和输出契约。采用 tagged union；任务族私有分层和 gold/oracle/reference 不进入生成输入。旧 tabular dataset 省略 kind 时兼容解释为 table，规范化及来源 hash 分列。
先为 F1–F6 各给一个仅用于契约的开发样例，原 72 模板及划分不变。字段尚缺只能返回 INPUT_INVALID/IMPLEMENTATION_GAP，不能默认塞进 Any。

P0 一次 physical；P1 logical → physical，分别有 request_id、共享 generation_attempt_id。模板仍使用 prompts/v1_1 的原字节，附加的明确 schema 说明用独立文件/hash登记。P1 第一阶段的 7 字段沿用 required_outputs、hard_constraints、necessary_operations、data_dependencies、information_requirements、permissible_alternatives、uncertainty；本阶段规定每项为字符串数组，允许空 uncertainty/alternatives，保持只含公开可检查声明。
P1 第二阶段带原任务与逻辑契约；不能用逻辑输出覆盖原任务，不接受验证器/gold反向反馈。

预算沿用 source generation：P0 16384；P1 4096+12288；输入上限 12288；最终 JSON 字节上限 65536。provider 不支持参数/tokenizer不可用时 capability=UNKNOWN/UNSUPPORTED、阻止正式冻结，不伪造实际 usage。transport retry、regenerate、execution repeat 分开；本票所有 calls 均 mock。
消息组装器只接受 public TaskInput，代码层不打开私有 gold 包；用嵌套未知字段、唯一随机 canary、provider格式化后消息验证隔离。不能声称关键词扫描能证明所有数据都公开。

## 8. 比较与执行身份

已提供 `identity.py`：
- comparison_context_hash 绑定 case/condition、data manifest、预算 profile、runtime、cache、verifier、metric spec、measurement profile、operator registry、source manifest。
- execution_key 再绑定 plan、compiler、input、generation、repeat 和 role。
- 参照计划与模型计划理应不同；比较时匹配 comparison_context_hash，不要求同一 plan_hash。
- 改 data/cache/runtime/profile 必须破坏比较身份；改重复 role 必须破坏 execution key。

这些 hash 构造函数不会证明实际部署遵守了配置。Codex 需要将其连接到真实的 expected manifest、引用与事件 sidecar，旧 ENGINEERING_ONLY 算分 API 保持兼容。必需字段 UNRESOLVED/null 不可变成合法正式 hash。避免把被测模型能自由提交的字段直接当受信 manifest。

## 9. 收尾条件

全 32 算子/实现的可执行契约矩阵、全族 TaskInput、P0/P1 mock、完整类型/控制、身份绑定、CLI、原件与安全回归都通过，才能输出 SPEC001B_ACCEPTED。`RUNTIME_NOT_IMPLEMENTED` 可保留给 EXEC-001，但静态契约 IMPLEMENTATION_GAP 不能被测试 skip 掩盖。
真实内核、API、云、隔离计量与正式统计仍分别属于后续工作包。
