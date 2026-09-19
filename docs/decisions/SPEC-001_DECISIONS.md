# RCWG-SPEC-001 决策稿 · TaskInput / WorkIR / 算子契约的可执行验证与 API 协议补充

- 票号：WG-SPEC-001（对应原设计 WP1 主体 + WP5 的 API 协议约束）
- 日期：2026-09-19
- 分支：rcwg/spec-001
- 基线 main：08b1ecff33ab01098926e3dceba64ab6ab4fa02c
- 状态：DRAFT_FOR_REVIEW（阶段A 草案，未实现）
- 原则：沿用 RCWG 1.0 / TaskInput 1.0 / WorkIR 1.0 既有语义；参考原件字节不变；歧义标 OPEN_DECISION。

## 0. 范围与边界

- 本票交付：可执行的契约与静态验证层 + API 中立记录 schema（mock）。
- 不在本票：真实模型调用、云资源、IAM、formal 启用、正式 campaign 冻结。
- 验证报告范围：公开合成正/反例；实际计算输出由 EXEC-001 统一执行器产生。

## 1. 来源基线

| 编号 | 来源文件 | 用途 | 读取时 hash（填） |
|---|---|---|---|
| S1 | specs/reference_v1_0/examples/task_input.json | TaskInput 样例（缺 schema，见 D02） | |
| S2 | specs/reference_v1_0/schemas/workflow.schema.json | WorkIR 1.0 结构 | |
| S3 | specs/reference_v1_0/catalogs/operators.json | 32 算子卡 | |
| S4 | specs/reference_v1_0/catalogs/task_templates.json | 72 模板 | |
| S5 | prompts/v1_1/{system,p0_user,p1_logical,p1_physical,executor_extract,resource_audit}.txt | 现行提示词 | |
| S6 | specs/reference_v1_0/configs/generation.json | P0/P1 调用数、seeds 17/29 | |
| S7 | specs/reference_v1_0/configs/campaign.json | 规模与矩阵 | |
| S8 | docs/SPEC_AUDIT.md | D01–D09 差异 | |
| S9 | docs/API_ENV_AMENDMENT.md | API 分层与测量 | |

## 2. TaskInput 契约

| 字段 | 来源（文件/JSON path） | 当前状态 | 所需实现 | 验收用例 | 判定 |
|---|---|---|---|---|---|
| task_id | S1 .task_id | 样例有 | 必填 string；唯一性 | 缺失/重复失败 | |
| instruction | S1 .instruction | 样例有 | 必填 string；长度上限? | 空串失败 | OPEN_DECISION: 长度上限未定 |
| datasets[].id | S1 .datasets[].id | 样例有 | 必填 string | | |
| datasets[].schema | S1 .datasets[].schema | 样例有 | 类型映射白名单 | 非法类型失败 | |
| datasets[].stats | S1 .datasets[].stats | 样例有 | 公开统计字段白名单 | 隐藏字段拒绝 | |
| resources.{cpu_slots,worker_memory_limit_bytes,wall_timeout_s} | S1 .resources | 样例有 | 类型/区间 | 越界失败 | |
| output_contract.{type,fields,k,mode,tie_breaker} | S1 .output_contract | 样例有 | 按 mode(exact/approx) 分支 | 非法 mode 失败 | |
| tool_catalog_id | S1 .tool_catalog_id | 样例有 | 引用算子目录 ID | 未知 ID 失败 | |
| gold / 标签通道 | D02 | 未定义 schema | 显式排除于公开输入 | 合成 canary 泄漏测试 | OPEN_DECISION: gold 通道边界 |

## 3. WorkIR 校验层

| 规则 | 来源 | 当前状态 | 所需实现 | 验收用例 | 判定 |
|---|---|---|---|---|---|
| 结构/必填 | S2 required | schema 有 | 映射为活动 schema | 缺项失败 | |
| ir_version const 1.0 | S2 | 有 | 保留 | 非 1.0 失败 | |
| nodes[].operator 枚举 | S2 enum | 有（32 项） | 与 S3 一致 | 未注册失败 | |
| nodes[].implementation | S3 implementations | 有 | 与算子注册表对齐 | 未注册失败 | |
| 引用完整性（inputs 端口） | S2 | schema 弱 | 端口/类型检查 | 未知端口失败 | |
| result 有效性 | S2 | schema 弱 | 必须指向有效输出 | 缺失/无效失败 | |
| 数据依赖 + after 合成 | S2 after | 未校验环 | 非受控环检测 | 环失败 | OPEN_DECISION: 有界循环判定 |
| 区域作用域（regions） | S2 $defs.region | schema 有 | 绑定/作用域校验 | 越界引用失败 | |
| 静态上限 | S2 limits | 有 | node_instances/loop_iterations | 越界失败 | |
| 参数合法性 | S3 parameter_fields | 未校验 | 类型/必填/越界 | 未知参数失败 | |
| 输入/输出类型兼容 | S3 input/output_type | 未校验 | 类型推导与匹配 | 不兼容失败 | OPEN_DECISION: 类型 lattice |

## 4. 算子契约注册表（覆盖 32 个 ID）

> 逐行填 S3 的 32 个 operator。contract_status ∈ {VALIDATED_CONTRACT, BLOCKED_UNDEFINED}；implementation_status 独立登记（BOOT 仅为设计资产，见 D06）。

| operator | 来源(S3 path) | contract_status | implementation_status | 参数类型/前置条件 | 验收用例 |
|---|---|---|---|---|---|
| scan | catalogs/operators.json[0] | | | | |
| filter | | | | | |
| project | | | | | |
| join | | | | | |
| aggregate | | | | | |
| deduplicate | | | | | |
| sort | | | | | |
| top_k | | | | | |
| set_op | | | | | |
| graph_neighbors | | | | | |
| graph_reachability | | | | | |
| graph_shortest_path | | | | | |
| graph_filter | | | | | |
| graph_subgraph | | | | | |
| read_documents | | | | | |
| text_retrieve | | | | | |
| split_documents | | | | | |
| gather_context | | | | | |
| semantic_extract | | | | | |
| evidence_merge | | | | | |
| evidence_validate | | | | | |
| materialize | | | | | |
| stream_read | | | | | |
| broadcast | | | | | |
| release | | | | | |
| cache | | | | | |
| map | | | | | |
| branch | | | | | |
| loop | | | | | |
| collect | | | | | |
| emit | | | | | |
| stats | | | | | |

## 5. P0/P1 阶段关系与错误状态

| 项目 | 来源 | 当前状态 | 所需实现 | 验收用例 | 判定 |
|---|---|---|---|---|---|
| P0 单次调用 | S6 protocols.P0.calls=1 | 有 | 记录 1 物理请求 | | |
| P1 两阶段（逻辑→物理） | S6 protocols.P1.calls=2 | 有 | 分开记录父子 attempt | 父子关系可查 | OPEN_DECISION: 父子 schema |
| seeds 17/29 | S6 | 有 | 试次标识；记录 seed 支持状态 | 不支持时标 null+原因 | |
| 错误状态分类 | S2/API | 未定义 | {ok, schema_mismatch, http, timeout, refusal, format} | 429/超时分类 | OPEN_DECISION: 错误码表 |

## 6. API 中立记录契约（G / E0/E1）

| 字段 | 来源 | 当前状态 | 所需实现 | 验收用例 | 判定 |
|---|---|---|---|---|---|
| role（G / E） | S9 | 有 | 必填枚举 | | |
| stage / parent_attempt | S9 | 有 | P1 两阶段父子 | 缺父失败 | |
| request_sha256 / response_sha256 | S9 | 有 | 规范化 hash | 可复算 | |
| requested_model / reported_model | S9 | 有 | 分列 | 未知→null | |
| usage | S9 | 有 | 分 provider 字段 | 缺失→null+原因 | |
| client_latency_ns | S9 | 有 | 与服务器时间分开 | | |
| remote_cpu/gpu/vram | S9 | 有 | 不可观测→null+NOT_OBSERVABLE | | |
| seed_supported | S9 | 未定 | bool + 说明 | | OPEN_DECISION |
| actual_cost_usd | S9 | null | 无证据保持 null | | |

## 7. OPEN_DECISION 清单（交研究负责人）

| ID | 问题 | 候选解释 | 影响 | 待确认 |
|---|---|---|---|---|
| OD-01 | instruction 长度上限 | 无 / 12k token | 输入组装 | |
| OD-02 | gold/标签通道边界 | 完全排除 / 只读白名单 | 泄漏测试 | |
| OD-03 | after + 数据依赖的非受控环判定 | 严格 DAG / 允许有界循环 | WorkIR 校验 | |
| OD-04 | 类型 lattice（Table/Stream/…） | 枚举 12 类 / 结构化 | 类型兼容 | |
| OD-05 | P0/P1 父子 attempt schema | 平铺 / 嵌套 | API 记录 | |
| OD-06 | 错误码表 | 见 §5 | 报告结构 | |
| OD-07 | seed 支持状态表示 | bool / 字符串 | API 记录 | |
| OD-08 | 静态可证明的资源条件 | 见推进卡 4.3 | 资源校验 | |

## 8. 待研究负责人确认（推进卡 4.2 六项）

1. 公开输入字段与 gold 通道
2. P0/P1 阶段关系
3. WorkIR 错误状态
4. 算子参数/输出类型与前置条件
5. 静态可判断的资源条件
6. API 元数据与不可观测字段表示

## 9. 版本与兼容决策

- 沿用 RCWG 1.0 / TaskInput 1.0 / WorkIR 1.0；如需变更语义或兼容性，另立版本决策记录。
- 新增活动契约放独立目录（specs/active/），不改参考原件。

## 10. 阶段B 实施计划（待批准后执行）

- 目录：见推进卡 4.5。
- 依赖：验证库与版本在阶段B 锁文件审核后固定，不用临时 --with。
- 通过标准：每个已声明规则有测试；两原始 top-k 样例有效；泄漏测试通过；原 43 项 + 33 参考件 + mock + formal 退出码 2 持续通过。
