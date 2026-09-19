# RCWG-SPEC-001 决策记录：协议与计量补充

日期：2026-09-19。状态：**DESIGN_APPROVED / IMPLEMENTATION_STARTED**。
实施检查点：**SPEC-001A**。下一检查点：SPEC-001B（完整静态验证器与接口组装）。
本决策依据用户本轮授权作出，研究核心范围内的接口和计量修订由研究协作者直接落实、测试并记录。

## 1. 依据、原件与证据边界

依据：已合并 PR #1；远端 main `08b1ecff33ab01098926e3dceba64ab6ab4fa02c`；原正式实验设计书“流程详解版 v1.1”第 11–16 章；用户上传的 32 行算子候选表；既有 `docs/API_ENV_AMENDMENT.md` 和 `docs/SPEC_AUDIT.md`。

本轮上传文件只含算子表及其脚注：它引用 OD-04 与“§6”，没有提供这两个段落的正文。本记录独立给出类型系统和 API 分层的确定方案，不声称引用未见的 OD 全文。候选原件以原字节保存在 `provenance/spec001a/owner_operator_candidate.md`，SHA256 见 BASELINE.json。

原 TaskInput 1.0 / WorkIR 1.0 的协议名称保留。新增实施规范使用 SPEC001A 0.1.0，与研究协议和文稿版本区分。`specs/reference_v1_0/`、`prompts/v1_1/` 原件保持字节一致。新字段、语义澄清和来源放在 `specs/spec001a/` 与本目录。

BOOT 本地验收完成、PR #1 合并已从连接器读取。新的 Python 3.12.14 doctor 在合并记录中登记了版本和散列；本次未再次取得该原始 JSON。旧 conversation doctor（3.14.4）作为历史采集保留，不被当成本次目标环境。容器、云端与真实 API 验收按已登记工作包执行。

## 2. 保留的科学对象与主比较

研究对象：生成器如何在公开任务、数据条件和资源限制下，联合选择算法、分解、数据传递和调度，获得语义可靠且资源可行的计算工作流。

正式设计仍为 6 个生成器槽位、32 个算子、72 个模板、480 开发/960 测试条件实例；P0/P1；原生成试次编号和运行数保留。

主比较保留：P1 对 P0 的 Success@Budget；EfficientSuccess(0.20)；AdaptivePlan 对 FrozenPlan 的配对收益。0.10/0.50 为原敏感性阈值。新增资源前沿、证据流、因果诊断用于解释主结果，独立标记其统计地位。美元成本作为经济性附账。

## 3. 授权与变更控制

可直接完成：兼容性修订、错误修复、文档与测试、原规格的有来源解释、离线样例、计量补充、独立分支/PR。通过报告说明“改了什么、依据是什么、实测到哪里”。

需保留所有者动作：云账号/IAM/付款与收费请求的实际授权、安装系统级软件、破坏性数据操作。主论文问题、正式数据划分或主比较的实质改变需明确登记协议修订，避免在看到测试结果后调整目标。

新的实现提交继续走独立分支和 CI；由所有者应用/合并。审批负担集中于费用、权限和科学范围改变，常规协议决定不反复等待逐条确认。

## 4. D-TYPE：确定类型代数（解决候选表的 OD-04 依赖）

采用“带 schema 的类型代数 + 显式表示转换”，不将 Table、Stream、Graph 与 Ref 视为可互换万能类型。

- 标量：Bool、Int64、Float64、Utf8、Date、Timestamp；Nullable[T] 区分缺失与具体值。数值拓宽、日期单位或时区转换需要声明规则。
- 数据值：Record[S]、Table[S]、Stream[Record[S]]、Set[T]、Graph[G]、GraphView[G]、NodeSet[G]、EdgeStream[G]、PathSet[G]、DocumentStream、ChunkStream、EvidenceTable[S]、Result。
- 引用：DatasetRef[T]、ArtifactRef[T]。Ref 是来源/生命周期句柄，与其被引用值分开检查。scan 的 source 端口解析 DatasetRef[Table[S]]；旧表的 Table 表示源数据范畴，不要求事先装入内存。
- Graph 和 GraphView 实现只读 GraphReadable[G] 接口。只读图算子可以显式接受这一接口；可写操作不接收只读视图。
- 联合类型只表示列出的可接受分支。Table[S]→Stream[Record[S]] 由声明的读取适配处理；Stream→Table 由 materialize/collect 处理。编译器保存转换节点与其资源开销。
- schema 统一检查字段名、顺序义务、nullable、图标识/方向/权重、文档 revision 与 span 坐标。动态数据前置条件由执行器再次检查。

当前代码实现的是旧 F1 表格 TaskInput 的有限 profile，尚未声称实现此完整类型代数。完整类型统一和控制区域检查属于 SPEC-001B；未覆盖特性返回 UNSUPPORTED_FEATURE/IMPLEMENTATION_GAP，不冒充模型非法计划。

## 5. D-OPS：32 算子决定与修订

32 个算子 ID 和实现名称保留。表中的候选 VALIDATED_CONTRACT* 统一转为 **DESIGN_APPROVED**；完整可执行契约通过相应测试后才升为 VALIDATED_CONTRACT。实现状态仍为 NOT_IMPLEMENTED，避免把审批当作内核已存在。

| 修订 | 决定 |
|---|---|
| scan/source | source 是输入端口，不同时作为含歧义 params 字段；由公开 dataset manifest 解析来源。 |
| project/graph_filter/shared_ref | view 保存底层 buffer_id 和依赖；物理 buffer 按唯一分配计量，别名不重复加整块大小。 |
| graph_reachability/DFS | max_hops 下 DFS 必须重访更短深度状态或跟踪 (node,depth)；普通 visited 集合不能保证有界跳数结果完整。 |
| graph_shortest_path | BFS 等权，Dijkstra 非负；不可达/并列路径选择和单条/全集路径义务由任务明确。 |
| loop | 最后允许迭代后先检查终止条件；已满足终止则成功，仍需继续时记录 LOOP_LIMIT_REACHED。 |
| collect | limit 默认保护上限；只有任务允许时才合法截断，保存 truncated 标记。 |
| map/branch/loop | 控制体通过 WorkIR regions 表达；params 不接收脚本或第二套嵌套工作流表示。资源使用原字段。 |
| evidence_merge | 支持保留并标冲突、拒绝冲突或预声明优先规则；不使用偶然遍历顺序解决冲突。 |
| evidence_validate | 公开规则/span检查属于算子；隐藏 gold 只由独立 verifier 使用。 |
| stats | 仅预登记 I2 探测轨的生成阶段开放并计入生成账本。 |
| semantic_extract | 接口与观测契约批准；E0/E1 的实际服务绑定保持 PENDING，不阻塞离线协议实现。 |

所有逐行决定见 `specs/spec001a/operator_contracts.json`。实现仍需固定输入/输出端口及参数 schema、差分测试和资源校准。

## 6. D-API：生成与语义执行分账

G 生成器、E 固定语义服务、worker 本地计算、云端外层编排、独立 verifier 使用分离 scope。
P1 的逻辑和物理阶段拥有独立 request_id，归同一 generation_attempt；transport retry、模型重新生成、执行重复分别记录，生成试次不等于 HTTP 请求数。

记录 requested_model/reported_model、provider、API版本、region、配置、时间窗、响应/输入 hash、usage原字段及可获得状态。provider不支持seed时保留 attempt_index，不伪造确定性。tokenizer兼容量与provider计费token分开。

远端 CPU、GPU、VRAM 填 null + NOT_OBSERVABLE。模型服务延迟是客户端观测量，包含网络/排队。G开销、E调用开销和本地算子资源分别展示；E0 replay 与 live execution 属于不同实验轨。

## 7. D-METRIC：确定计量闭环

采用 `METROLOGY-001.md`：结果与预算主指标、资源向量、过程与信息保真、条件适配、测量有效性五组面板。
每个指标必须绑定原始来源、单位、scope、缺失语义、适用任务及干预测试。节点/边数量是描述量，较少不自动加分。

原稿三项主比較不更名。补充点：共同候选覆盖、缺测可识别区间、并发内存去重、buffer存活面积、全量权威账本与OTel镜像、API隔离，以及原E3/E4/E5上的受控诊断。

原计时不稳定规则允许增加到7次。实施明确区分 PRIMARY_REPEAT 与 TIMING_CONFIRMATION：原2/3次主重复定义保持冻结，追加计时用独立诊断manifest，避免按观测稳定性选择性改变成功率的重复权重。此项是本轮明确化修订，应在正式预注册中登记。

## 8. 本次实际实现与下个交接点

SPEC-001A 已实现：严格JSON读取、F1 TaskInput有限profile及白名单组装、原算子ID对齐检查、单位/scope感知指标验证、逐重复三值判定和分层汇总、候选覆盖/时间比、物理buffer生命周期与多种字节账本归约、标注证据见证集覆盖归约、只读cgroup探针；对应离线测试。

本次尚未实现：完整 WorkIR 编译器、所有算子运行时、自动事实判真、云部署、正式容器隔离、全量执行器计量、cluster bootstrap/Holm生产分析。DESIGN_APPROVED 与这些代码状态在报告中分别表达。

下一交接点 SPEC-001B：从保护原件的五节点示例开始，实现 TaskInput全族扩展、输入/输出端口检查、完整类型/作用域/依赖/资源静态验证；保留真实缺口状态。随后 EXEC-001 实现首个实际 F1 WorkIR 闭环，同时接入本次账本接口。真实模型/API和云部署按后续独立门禁运行。
