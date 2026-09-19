# RCWG EXEC-001 接口卡

本卡把 SPEC-001B 已实现的静态输出交给下一阶段执行器。当前没有运行内核、真实模型请求、云端执行或正式资源计量。`IR_VALIDATED` 只表示静态契约通过；`runtime_kernels=NOT_IMPLEMENTED`、`formal_ready=false` 继续有效。

## 1. 数据流与信任边界

```text
已审核 public TaskInput
  → validate_public_task
  → P0/P1 mock 组装、原始响应解析及私有归档
  → validate_workflow / validate_workflow_bytes
  → typed_graph + input_bindings + runtime_obligations
  → [EXEC-001 待实现：注册数据、调度/内核、artifact 注册、实际事件]
  → [待实现：独立输出 verifier，私有 gold 留在验证侧]
  → seal_events / make_sidecar / validate_evidence
  → 后续正式计量和统计门禁
```

模型只能提交 WorkIR。公开数据注册表、编译器源码、runtime/cache/measurement/verifier 身份、预期尝试清单及最终 sidecar 都由可信 runner 构造。模型输出中的“已验证”“资源已满足”或自报 hash 不会成为权威证据。内容 hash 证明记录一致，不能单独证明真实部署执行了相同配置。

## 2. 已实现的编译输出

Python 入口：

```python
from rcwg_spec.compiler import validate_workflow, validate_workflow_bytes

report = validate_workflow(task, plan, stage="primary_execution")
# 有原始响应字节时使用以下入口，以同时保留 raw_plan_hash。
report = validate_workflow_bytes(task, raw_plan_bytes, stage="primary_execution")
```

只有 `status=IR_VALIDATED` 且静态 gap 为空时，未来执行器才能进入自身运行门禁。`INPUT_INVALID` 是任务/设施输入缺陷；`PLAN_INVALID` 是可确定的计划违约；`IMPLEMENTATION_GAP` 是设施能力缺口；`INTERNAL_ERROR` 阻止发布，不能归为模型错误。诊断包括 code、stage、JSON Pointer path 和脱敏说明。

报告真实字段如下：

| 字段 | EXEC-001 使用方法 |
|---|---|
| `task_input_hash` | 绑定原任务对象，区别于规范化后的输入 hash |
| `canonical_plan_hash` / `raw_plan_hash` | 前者绑定 JSON 内容，后者绑定原始字节；仅字节入口返回后者 |
| `typed_graph.nodes` | 按原序列化顺序提供所有 scope-qualified 节点；不能拿分析拓扑序替换模型调度顺序 |
| 节点 `id/scope/logical_id/serialization_position` | 区域与节点实例身份基础；动态实例还需执行器添加实例/迭代标识 |
| 节点 `operator/implementation/dispatch_id` | 已验证的静态分发选择；实际 kernel 注册表仍待实现 |
| 节点 `input_references/params/after` | 原始引用、参数与显式控制依赖，不添加隐式排序、复制或物化 |
| 节点 `inputs/outputs` | 从真实公开 schema 和上游推导的类型 JSON，不以输出声明替代类型证据 |
| 节点 `input_capabilities/output_capabilities` | 保留公开来源、索引、文档 ID 映射、图属性等类型元数据；属于能力/来源描述，不是运行观测 |
| 节点 `resources/storage` | 节点声明的资源/存储选择；缺失值按执行器冻结策略处理，不编造已测峰值 |
| 节点 `buffer_aliases` | 静态可能共享的符号根集合；不是已经分配的物理 buffer ID |
| `dependency_edges/scopes` | 数据、after、region 捕获依赖；scope 同时保留 serialization_order 和 analysis_topological_order |
| `input_bindings[alias]` | 包含 source_id、推导 type、完整规范化 public_source；只允许注册的公开来源 |
| `result` | 最终 reference 和类型；执行器还需生成并封存实际输出 artifact |

控制节点的 `regions[label]` 已返回 `{scope, bindings, yield}`。区域实际节点位于扁平节点表并携带对应 scope。`bindings` 的右端在父作用域解析；区域内部只通过 `$bound.alias` 访问显式绑定。map 的 `$item` 是单条 Record；loop 的 `$state` 是状态值。branch 的 then/else 结果必须能按已批准规则合并，不能补隐式转换。

`typed_graph.buffer_identity_kind=STATIC_SYMBOLIC_ROOTS_NOT_MEASURED_ALLOCATIONS` 必须保留。只有 EXEC 实际分配/注册后才能建立物理 buffer_id、共享 view 和生命周期账本。

## 3. 执行器必须落实的运行义务

`runtime_obligations` 是执行器的任务清单，不是执行成功证明。义务包含稳定 code、path，以及适用节点/条件。当前包含以下主要类别；实际报告可以包含算子专属条目：

| 已返回义务 | 执行器应落实的行为 |
|---|---|
| `GLOBAL_CPU_SLOTS` | 全局 CPU admission 同时约束所有实际节点，不能由嵌套 map 放大配额 |
| `GLOBAL_INSTANCE_COUNTER` | 动态实例累计计数；释放对象或串行完成不退还实例额度 |
| `WORKER_MEMORY_LIMIT`、`WALL_TIMEOUT` | 实际 worker 边界内执行并记录超限，不能把估计内存当真实值 |
| `DYNAMIC_MAP_INSTANCE_ADMISSION` | 按实际输入与局部 max_parallelism 创建实例，同时遵守全局限制 |
| `CONTINUATION_AT_LIMIT` | loop 先检查初始状态，每次更新后重查；到上限时 false 可完成，true 为 LOOP_LIMIT_REACHED |
| `CONTROL_DEPENDENT_LIFETIME`、`CROSS_REGION_LAST_CONSUMER_GUARD` | 分支、循环和区域捕获的实际最后消费者检查，物理 buffer 唯一计数 |
| 谓词/算术/前置条件义务 | 三值逻辑、动态除零/溢出、数据相关排序/图权性质、索引可用性等使用固定运行语义 |
| 数据/语义/输出义务 | 实际读取、复制、证据来源及结果完整性在运行和独立验证侧核查 |

静态允许的低效计划不能在执行器里自动优化。`full_sort`、重复读取、低并行等选择应保留其可观测成本。运行失败与设施失败分别登记；没有运行观测的 CPU、RAM、远端 GPU/显存、API usage 保持未知。

## 4. 已实现的身份和事件连接

`rcwg_spec.binding.build_context(...)` 接收任务、condition_id、实际 data_manifest，以及 runtime、cache_policy、verifier、metric_spec、measurement_profile、operator_registry、source_manifest 的完整元数据对象，产生不可变 `RunnerContext`。

data_manifest 的每条 `{id, revision, content_sha256, schema_hash}` 必须匹配 public source；source_manifest 必须包含 `revision` 与 `public_sources`。measurement_profile 还需 `event_source_id`、`clock_id`。缺少数据修订、内容证据、必要配置或含 UNRESOLVED/null 时不能补假值获得正式身份。

`freeze_expected(context, specifications)` 在运行前创建不可变 `ExpectedManifest`。每条记录含 record_id、MODEL/REFERENCE role、实际 plan、实际 compiler_source 字节、generation_id、repeat_id、PRIMARY_REPEAT/TIMING_CONFIRMATION role。参照计划允许与模型计划不同，但必须共享比较上下文。runner 应预先保存 manifest hash，并用该可信清单验证后续结果；不能根据收到多少日志重建分母。

`seal_events(manifest, record_id, observations)` 给已经观测到的事件添加连续 sequence、source_id、clock_id、execution_key 和 hash chain。输入 observation 必须已有 `{event, monotonic_ns, status, payload}`；本函数不会采集时间或生成测量值。当前支持 run_started、node_ready、node_started、node_finished、artifact_created/read/released、run_finished，并检查唯一开始/终结与时钟单调性。更完整的 node ready/resource-ready/blocked 状态机、动态实例与 buffer 事件语义由 EXEC-001 实现及校准。

`make_sidecar(...)` 绑定账本 hash/count、terminal_status 和独立 verification_status。终态包括 COMPLETED、MODEL_FAILURE、TIMEOUT、OOM、INFRA_FAILURE、UNKNOWN。未完成运行不能附 PASS。`validate_evidence(manifest, model_records, event_ledgers, reference_records)` 检查记录身份、角色、来源、事件序列、hash、终态和参照确认；缺记录/账本返回 EVIDENCE_INCOMPLETE，原模型/参照分母仍保留。

这些接口已经实现。它们返回 EVIDENCE_BOUND 时，`runtime_enforcement` 和 `measurement_validity` 仍为 NOT_VERIFIED。哈希和序列一致不等于实际观测已经可信。

## 5. EXEC-001 待实现：artifact 注册与独立 verifier

以下是下一阶段接口责任，不是本票已有函数或运行内核：

1. **数据/对象注册器**：按 `input_bindings.public_source` 的白名单 ID 与 revision 解析受管对象，核对实际内容和 schema hash。模型文本或任意 URI 不能直接变成文件打开权限。
2. **artifact 注册器**：实际产生 artifact_id、content_sha256、type、producer、serialized_bytes、created_ns；根据实际情况填写 rows、released_ns、format、schema_id、source_refs。原 artifact schema 保持不变；新增 run/execution/buffer/view 绑定放版本化侧车。未释放字段可保持 null。
3. **物理 buffer 账本**：每次实际分配产生唯一 ID，view/broadcast alias 指向同一真实对象；copy_each 对应新对象。记录实际 read/copy/wire 等不同范围的字节，不把引用载荷字节当正文已读取字节。
4. **独立输出验证入口**：输入为只读最终 artifact、原 public output_contract、必要的私有验证包，以及 execution/context/artifact 身份。输出为 PASS/FAIL/UNKNOWN、关键约束/证据结果和 verifier 身份。私有 gold、oracle、分层标签和 verifier 反馈不回流到 P0/P1 生成器。
5. **运行状态机与故障封存**：OOM/timeout/设施故障仍产生终结记录；缺事件、断写和未封存 artifact 不能获得完整成功证据。不得将未完成运行的 elapsed 当完整执行时延。

## 6. 本地调用示例与后续门禁

在仓库根目录用既有 Python 3.12.14，输出文件名每次换新；不得使用系统默认 Python 3.14：

```bash
uv run --offline --frozen --python 3.12.14 python -m rcwg_spec validate-public-task \
  specs/spec001b/examples/public_F1.json

uv run --offline --frozen --python 3.12.14 python -m rcwg_spec validate-workflow \
  --task specs/reference_v1_0/examples/task_input.json \
  --plan specs/reference_v1_0/examples/workflow_topk.json \
  --output runs/exec-interface-check-NEW.json

uv run --offline --frozen --python 3.12.14 python acceptance/spec001b/independent_review.py

uv run --offline --frozen --python 3.12.14 python -m rcwg_boot check --formal
# 预期 BLOCKED_NOT_FROZEN，退出码 2。
```

进入真实执行前仍需实现并验收内核、调度/状态机、数据/artifact 注册、独立输出验证。正式冻结前另外需要实际 runtime/编译器完整源码身份、隔离 worker/cgroup 与权限边界、资源限制和计量校准、时钟/账本完整性、API 服务及 tokenizer/参数能力、真实 usage/成本账本、容器与云端各自证据。WSL、CI、Docker、真实云端结论必须分开。当前不安装系统软件，不改默认 Python、网络模式、Docker、IAM 或云账号，也不开放真实模型和正式实验门禁。
