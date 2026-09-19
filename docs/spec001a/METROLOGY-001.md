# RCWG-METROLOGY-001：资源条件化工作流的测量与解释协议

日期：2026-09-19。规范状态：DESIGN_APPROVED。计算核检查点：SPEC-001A。
来源：原正式实验设计书 v1.1 第11–16章、API_ENV_AMENDMENT；本轮修订单列。

## 1. 审核结论

原方案覆盖了语义验收、预算可行、相对确认候选的时延、条件适配、进程树资源、数据搬运和生命周期。这些内容继续保留。论文强度取决于能否通过同一执行环境下的任务条件干预，区分正确性、算法选择、信息丢失与执行安排的影响；增加指标数量本身不构成贡献。

补齐五项：并发归属和重复计数规则；中间信息保真的可检查定义；API环境的不可观测项；缺测/参照覆盖/重试的统一分母；受控干预与阴性对照。所有新增量绑定原始事实，避免从图规模或模型解释中猜资源。

## 2. 目标、主指标与可观测资源

任务 x、公开条件 c、资源上限 b、生成器 g 产生 WorkIR w。统一执行器 E 执行 w，独立验证器 V 检查结果和证据。选择目标可以表达为：在语义契约通过与资源约束满足的可行集合中，比较完成时间、CPU工作、内存和数据搬运等向量。

### 2.1 原主指标保持

对计划 i 的第 r 次主执行：

S_ir = 1[来源、实际输出、关键语义和证据通过]
B_ir = 1[该任务所有声明且适用的资源上限通过]
V_ir = S_ir AND B_ir

Success@Budget：先对固定计划重复取均值，再按生成试次、条件、基础实例、模板、任务族依次聚合。

EfficientSuccess(eps)：在独立冻结的参照覆盖集合内，对 V_ir * 1[T_ir <= (1+eps) T_ref_i] 按相同层次聚合；eps主值0.20，敏感性0.10/0.50。T_ref由参照候选独立确认阶段获得。模型比参照更快时 rho=T/T_ref 可小于1。

AdaptiveGain：相同目标条件下 AdaptivePlan 与来自 C0 的 FrozenPlan 的配对指标差。程序形状保持与变化都依据结果计分。

精确族保留完整契约；原 F5/F6 默认字段F1>=0.90、证据precision>=0.95并逐项通过否定、日期和关系等硬约束；这些值在正式测试解封前审核冻结。本票不更改它们。

### 2.2 原始scope

| scope | 记录 | 用途 |
|---|---|---|
| generation | P0/P1、请求数、latency、usage、拒答/格式失败、探测与修订 | 生成能力与部署附账 |
| worker_exec | 从执行器接受validated plan并开始执行到结果封存；CPU秒、内部排队、工作量 | 主执行性能；排除外部批次队列和独立verifier |
| worker_cgroup | run及所有worker子进程的资源；包含执行器自有开销 | RAM/CPU/I/O预算和失败证据 |
| artifact_proxy | 逻辑读、引用载荷、复制、序列化、buffer生命周期 | 分解与信息搬运诊断 |
| semantic_service | 固定E0/E1客户端请求、批次、provider usage及payload | 语义调用成本；CPU/GPU内部不可观测 |
| cloud_control | Job等待/启动/外层workflow与对象归档延迟 | 实际部署端到端面板 |
| verifier | 输出与隐藏标签验收、证据判定 | 评测设施开销和语义标签；保持独立 |

分阶段延迟可在串行、无重叠定义下相加。E调用已包含在worker等待中的时间不再次加到worker总时延。并行请求延迟之和表示累计等待工作，不能冒充端到端时延。

## 3. 最终报告的五组面板

### A. 结果与资源可行性（主表）

格式/类型通过、执行完成、语义成功、关键约束通过、Success@Budget、EfficientSuccess、参照覆盖和计量覆盖。失败按格式、引用、参数/前置条件、错误答案/证据、OOM/超时、API/基础设施等分类。每层既保留无条件分母，也可另外报告条件转移率，避免只看幸存者。

### B. 资源向量（解释为何贵）

T_exec、CPU秒、cgroup memory.peak、logical read、block IO、payload/copy/wire、语义请求数与参考token量。工作量按算子记录 comparisons、hash_probes、rows_scanned、edge_visits、semantic_examples，跨算子不盲目相加成“复杂度总分”。

实际有限规模计数用来分析扩展趋势；仅凭几次wall time不能证明Big-O。算法的渐近式由具体实现推导，规模实验检验观测范围内的增长。

在相同语义门槛、预算、数据和执行环境下展示确认候选资源前沿与 Reference-Dominated Rate（诊断）：生成计划是否被一个确认候选在预登记可比维度上不差、且至少一维实质更好。时延差需超过测量噪声/工程差异阈值。未知维度不补0。该前沿仅代表候选集合，不是全局最优证明。

预算成功面板按原C0–C3及预登记可比条件展示。只有保持其余因素固定的预算扫描才能解释为预算敏感性。模型排名变化、质量/资源取舍与交互效应都保留；不把美元、秒、字节加权成任意总分。

### C. 信息流和执行过程（定位计划问题）

1. 调度：node ready、resource_ready、start、end，显式批次到达/阻塞、背压、队列等待。活跃节点数是诊断量；真正的CPU占用来自cgroup。给定无阻塞纯DAG及节点工作条件时可计算理想关键路径下界；含流式/服务等待时按实际事件图定义，不把理论下界当可达到的最佳调度。
2. 数据：序列化耗时、读量/复制量、fan-out、buffer共享及落盘。重读或多节点只有在任务允许省略且受控干预保持语义时才被称为冗余。
3. 内存：每个唯一物理buffer的创建、最后使用、释放、spill，报告峰值存活字节与 byte-seconds。两者描述声明/注册的对象，不代替系统总RAM。
4. 信息保真：在预登记文档/图文路径检查点，测量任务所需事实、限定词与支持证据的可用性。采用独立标签或经盲化裁定的见证集；不直接使用全文相似度。

### D. 条件适配与稳健性

保留E2 Adaptive/Frozen配对；同义改写、顺序/ID重命名、规模外推、selectivity、图度分布/索引条件、上下文预算变化分别归原E6或诊断轨。对每个场景指明哪些变量不变、哪些改变。长任务上的证据退化和恢复曲线进入E4；E0/E1交叉执行沿原E7，不将不同服务内部算力当作可观测资源。

### E. 测量有效性（发布门禁）

expected manifest、terminal record、plan/data/source hash、单位/scope、必需资源、账本序号/完整性、计量开销、计时稳定性和参考覆盖。它们用于判断结果能否支持结论，而非给生成器奖励分。

## 4. 并发内存、CPU与字节的严格计量

### 4.1 工作流RAM

每次正式run创建独立cgroup，在运行前把worker纳入并在组内创建负载。监测/外层控制与独立verifier在外部组。冻结CPU配额/亲和性、线程预算、memory.max、swap政策和缓存条件。

主峰值由run cgroup的memory.peak取得；读取memory.events、memory.stat、cpu.stat、io.stat及可用pressure/throttling字段。核实内核版本能力，不依赖所有内核都有相同的peak-reset接口。每run新组避免复用旧峰值。

memory.current以100ms采样画曲线；样本最大值不替代kernel peak。memory.peak包含被该组记账的匿名页/文件缓存等，不能直接叫“Python对象RAM”。跨组共享页记账归属、页缓存与实际驻留在正式校准中说明。

M_run_peak = max_t M_run(t)，一般不等于 sum_v max_t M_v(t)。节点并发共享进程时，总RSS不能被简单切片成精确节点RAM。采用节点隔离诊断或标注“不具精确归属”；主分数使用run级事实。

### 4.2 buffer对象

每次真实分配有唯一buffer_id；view/切片引用同一ID并保存范围。A(t)为时刻t仍存活的唯一buffer集合，

M_buffer_peak = max_t sum_{b in A(t)} bytes_b
L_buffer = integral sum_{b in A(t)} bytes_b dt

采用半开区间[create,release)，同一时刻先释放后创建。元数据、自有分配、allocator保留、运行时和page-cache可能不在这个buffer账本内，报告覆盖范围和偏差；M_buffer_peak与M_run_peak分别保存。

### 4.3 CPU

CPU_run = delta cpu.stat.usage_usec / 1e6，涵盖组内进程树。线程化内核的总CPU秒可大于wall time。多核CPU利用率的分母使用实际配额×时间，标明它是观测利用率；不由节点span重叠数推断。

### 4.4 数据字节

payload_bytes=边协议的引用/正文payload；read_bytes=代理记录的实际逻辑读取；copy_bytes=已插桩应用层复制；wire_bytes=特定传输边界观测的网络字节。io.stat=块设备层读写。几者不同且可能重叠，全部分列，不相加成一个“通信量”。

事件以operation_id/edge/attempt去重，同一次传输的发送/接收日志不算两次传输。共享1GiB对象传64B引用仍可能有消费者读取；zero-copy只减少特定复制，不消灭读取或进程驻留。库内部未插桩复制/DRAM带宽明确保持未知。

## 5. 信息保真：先确定义务，再检查传递

以一个私有标注的必需事实q为例，它可具有多个可接受见证集W(q)={W1,W2,...}。见证集可包含实体、否定、日期、关系、原始文档revision/span等不可分割组合；另一份等价证据可成为另一集合。

在预登记检查点j，独立验证器给出下游可用的规范化事实/证据单元A_j。若存在W in W(q)且W包含于A_j，记q在该检查点covered。检查点coverage=covered义务数/适用义务数。

检查的是任务相关信息义务，正确过滤掉不相关记录不受惩罚。原始span存在不自动证明语义真值；从文本到规范化事实的映射需要标签/程序/人工裁定。所需信息为空时记NOT_APPLICABLE。关键否定、时态、关系需单列硬约束。

后续gather/re-read可恢复信息，故coverage可升可降。报告“当前已物化信息覆盖”和“按计划允许后续读取恢复”两种状态，不把中间暂未读取一概认作永久丢失。最终指标仍由完整结果/证据验收决定。中间检查由独立诊断重放收集或评测期读归档，避免gold流入生成器/worker。

SPEC-001A中的evidence_coverage只对已经标注的见证ID集合做集合运算，用于测试接口；它没有自动事实识别或判真能力。

## 6. 完整性、失败、参考覆盖与统计

### 6.1 冻结分母与缺测

每次运行前由expected manifest列出主尝试/重复。少一条实际日志不让分母变小；重复record_id和未计划的记录均报错。

确认的模型/计划失败：V=0。已核实基础设施/计量故障：原attempt保留、按统一有上限策略重跑，派生attempt与parent关联；未解决时状态UNKNOWN，不能伪装模型成功或无声删除。

S/B使用三值：False可决定失败；True需充分证据；必需观测缺失为Unknown。基础设施状态阻断最终能力归因。若有Unknown，报告固定分母下的观测可识别区间：下界把未知置0，上界把未知置1，并按原层级聚合。这不是95%置信区间。主点值发布需相应计量门禁通过；未通过时仍展示完整覆盖与失败信息。

资源上限由任务声明。已确认OOM/超时直接使相应预算判定失败，即便OOM时peak没有揭示总需求。超时时间是完成时间的截尾下界，不能当成恰好该时刻完成。受预算终止的运行无法恢复出无约束峰值需求。

HTTP状态不单独决定失败归因。429/超时需要结合冻结的并发/请求预算、提供商状态和重试策略判断；生成器自行重复调用造成超预算与独立服务故障分别登记。工具实现缺口、版本不兼容及计量代码错误属于设施缺口，不能记成模型非法计划。因果诊断和正式尝试分别计数；失败尝试产生的调用和执行消耗仍进入完整经济性附账。

### 6.2 参考可比性

候选集合在看到测试生成结果前冻结；确认计时独立于候选筛选，减少选择噪声。reference_id绑定任务条件、预算、数据版本、硬件/执行器、缓存和确认记录。

所有模型/协议比较使用相同参考覆盖集合；报告按模板/族分层覆盖率。覆盖缺失影响EfficientSuccess的可计算域，不会取消该任务的Success@Budget义务。覆盖不同的面板不直接排序；模型跑赢参照保持真实rho<1。

SPEC-001A检查case_id和budget_hash，报告各模型panel的case集合是否相同。正式reference schema还必须绑定数据/硬件/缓存版本并在SPEC-001B/WP7落实，不将此有限检查冒充完整环境冻结。

### 6.3 聚合和推断

先执行重复，再生成试次、条件、基础实例、模板，最后六族宏平均；模型/协议分别建panel。确定性3次与语义2次不会产生任务权重偏差。

原48测试模板cluster bootstrap（10000次）与三项主比较的Holm规则保留，新增指标标解释性/探索性。不能用两三次运行推断p99；尾部稳定性需专门重复设计。PRIMARY与追加TIMING_CONFIRMATION分开；计时不稳定保留状态并做预登记敏感性。

## 7. 计量设施结构与门禁

执行路径：TaskInput → 输入组装/G API → WorkIR静态检查 → 固定worker → 结果artifact → 独立verifier。

同步保存五个账本：generation、run resource、node/event、artifact/byte、verification。每项带schema_version、run/attempt/plan/data IDs、scope、unit、monotonic clock标识、sequence、采集方式、value/status/reason和证据位置。服务请求再带G/E与stage/request/parent IDs。

权威证据是全量、可校验序号/散列的运行账本。OTel从账本映射span与links用于观测；普通采样trace、span event/link上限不能决定主指标分母。OTel parent表达调用层级，DAG多前驱通过links和原始依赖表保存。

优先完成的部署验收：

1. run进程树确实属于隔离组，所有子进程结束/被受控终止后封存；后台sampler已退出；峰值/I/O最终状态读取完成。
2. 已知内存重叠、alias、复制、spill夹具产生预期账本；采样曲线与kernel peak用途分离。
3. 开启/关闭计量在代表性CPU、流式、fan-out、I/O和短节点负载做随机配对；原3%开销目标按置信区间和计时分辨率判定；短节点用固定批次聚合测试。超过目标将详细计数移至独立诊断，不进行事后任意减去一个固定开销。
4. 断写、重复事件、provider timeout、OOM、缺测、错误单位均触发明确状态。权威ledger和产物完整性丢失时不开放正式评分。
5. CPU/内存与语义请求预算可被执行器实际约束；如果某项只能观测，限制能力说明与预算政策匹配。

Cloud Run适合功能联通性；正式资源比较在受控Linux worker/VM上完成。外层Google Workflows仍管理提交、等待与归档。本轮没有云部署和IAM修改。

## 8. 与论文观点相连的实验

沿原E1–E8组织，不新增泛化“综合总分”。E1主结果；E2条件适配；E3分解/算法/调度隔离；E4粒度和证据传递；E5指标有效性与受控缺陷；E6规模/组合外推；E7语义执行器影响；E8外部任务检验。

E5既有120个人工控制计划内预登记：合法算法替换、合法并行/串行、shared-ref/copy、受控重读、关键限定词删除、路径/空值/并列语义错误、节点重命名阴性对照、丢失/重复计量事件。明确哪些是成对原始/变体、哪些复用E1；不静默增加运行预算。算法/调度干预须保持语义一致；注入语义缺陷的实验用于验证指标敏感性，不充当真实模型普遍缺陷的证据。

真实模型的失败频率来自未挑选的主矩阵；受控实验验证能否定位机制；二者分开报告。若只有构造夹具上有效、外部任务无可观测差异，论文结论应收缩到当前条件，而不是换阈值追求差异。

## 9. 外部技术依据（2026-09-19 核查）

- Linux cgroup v2 官方文档： https://docs.kernel.org/admin-guide/cgroup-v2.html （cpu.stat、memory.peak、memory.stat、共享记账与版本差异）。
- OpenTelemetry Tracing SDK： https://opentelemetry.io/docs/specs/otel/trace/sdk/ （sampling与span limits）。
- OpenTelemetry Tracing API： https://opentelemetry.io/docs/specs/otel/trace/api/ （parent与links）。
- Apache Arrow Columnar Format： https://arrow.apache.org/docs/format/Columnar.html （共享内存zero-copy的具体条件与IPC）。

这些文档支持工具行为；项目阈值、指标组合、检查点和实验安排是本轮研究设计决定，依赖后续目标环境测试。
