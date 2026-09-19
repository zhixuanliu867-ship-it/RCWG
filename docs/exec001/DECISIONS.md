# EXEC-001 实施决策与接口 — 2026-09-19

状态：DESIGN_APPROVED；本轮已完成 REFERENCE_CORE，完整 EXEC-001 的进程监督与完整验收由 Codex 继续。基线是已审 B 的 a1f65120ef0b2b8e1fb6f1c31224244d6f7ee16b，tree 5b1b7cd587bbb3df54952ea24eb6841767a1e0bd。原设计文件与 32/56 静态契约、72 模板、6 模型槽、主要比较保持不变。

## 1. 本票具体目标

用模型可提交的真实 WorkIR 执行首个 F1 ordered-records 开发闭环：可信数据注册 → 已有静态编译 → 受支持实际内核 → 实际结果 artifact → 独立结果验证 → 固定 expected manifest 及真实事件绑定。

本票完成状态名为 `EXEC001_F1_ENGINEERING_ACCEPTED`，范围是本文件声明的 F1 root-chain profile。它不代表 32 个运行内核全部完成，也不代表正式资源计量/正式论文运行准备完成。任意 WorkIR 的多分支调度、图/文档内核和控制区域按执行内核后续子票扩展。后端不支持的合法计划使用设施 gap，不能计为模型错误。

## 2. 参考后端与正式后端的关系

本轮 `rcwg_exec` 是 Python 标准库参考后端，profile 为 `RCWG_EXEC001_F1_REFERENCE_SERIAL_PULL_0.1`。其用途是验证数据依赖、结果和证据闭环，并给后续原生后端提供独立对照。

原设计的 C++20/Arrow 等公平内核与受控 Linux worker 仍是正式效率实验路线。禁止把本轮 Python reference 的耗时、进程高水位或 row-frame 数直接换名为正式 C++ 算子/worker 指标。本票不要求安装新依赖；原生后端、容器和正式 cgroup 校准在对应门禁落实。

实际支持 5 算子 / 8 分支：scan:sequential；filter:scalar、vectorized；project:column_view、copy；top_k:full_sort、streaming_heap；emit:json_artifact。vectorized 在此明确为 **bounded-batch mask Python reference**，实际按 batch_rows 分批，并计 batch_frames_peak；不声称 SIMD/native 吞吐。其代码、配置与标签绑定 runtime identity，不能和后续原生实现混表比较。

当前 preflight 只放行一条完整 root 数据链。显式 after、多消费者/死节点、regions、disk 或声明多 CPU/并行均明确返回 RUNTIME_IMPLEMENTATION_GAP；不能默默删掉节点、重复消费同一个 stream、插入物化、忽略 after 或改算法。Codex 在本票内可以保持该 profile 范围；扩展必须先落明确契约和对应验收，不以“完整 EXEC”简称暗示已覆盖任意 DAG。

## 3. 已有调用入口

```python
from rcwg_exec.datasets import FileRegistry
from rcwg_exec.runner import preflight, run_f1_reference
registry = FileRegistry(task, trusted_locations, allowed_root=private_root)
report = run_f1_reference(task, plan, registry=registry, recipe=private_recipe,
                         output=fresh_output_directory)
```

`trusted_locations` 由 runner 构造，不从 WorkIR 或模型 URI 生成。注册时核对真实文件 SHA256，scan 对真实消费字节再计算 SHA256，EOF 不一致或 row/schema 不一致归数据/设施失败。JSONL 是开发数据布局，不冒充 Arrow 的零复制实现。旧参考示例保持原件；demo 创建新 task_id/真实行数/修订/内容 hash，与 960 正式实例分开。

核心结果 artifact 遵循旧 artifact schema；execution 绑定放独立 artifact_binding.json。新目录独占创建、文件模式 0600，使用 O_EXCL，拒绝输出路径和源位置越界。数据/结果/recipe/原始日志留在 runs/ 私有目录。

## 4. 正确性与计划忠实性

`full_sort` 真正物化并全排序；`streaming_heap` 显式维护最大候选堆，容量 k，再排序 k 项。它不调用会在某些 n/k 条件下自行切换策略的通用 top-n API。完全相同的排序 keys 用稳定序位断开容器比较，不对记录 dict 作比较。

排序键与方向来自 WorkIR，不能追加模型遗漏的 tie-breaker。输出投影来自模型 project；runner 的最终序列化不自动删除多余字段。k=0 的参考实现仍耗尽输入，以保留本 profile 的完整 source/EOF 证据；这是明确的参考实现策略，之后的优化后端必须另登记实现版本。

谓词 AST 用有限解释器执行；Bool/Int 区分，SQL-style unknown，Int64 与浮点溢出、除零使用动态错误。参考 Boolean junction 按顺序 eager 求值；不把真值短路优化隐式塞入实验。Date/Timestamp 等未支持数据类型在参考 registry 前置拒绝为设施 gap。

独立 verifier 目前只支持已声明 recipe `F1_ELIGIBLE_SCORE_DESC_ID_ASC_V1`：从可信任务语义审核产生的固定 recipe 读取数据，独立 eligibility 筛选与 (-score,id) 全排序，严格比对 canonical 输出。recipe 绑定 task/data/k/fields，其内容从不进入执行内核或 P0/P1。超出此 recipe 的任务 UNKNOWN，不能据 WorkIR 推导“正确答案”。静态通过但漏过滤/排序错误/k 错误必须 COMPLETED + verifier FAIL；不能自动修复。

## 5. 时间、内存、字节与算法计数

参考 execution wall 从 run_started 附近开始，含实际读取、内核、结果序列化，排除注册预读、静态编译、独立 verifier 与事后账本整理。注册预读会影响页缓存，所以 cache policy 为 observed/uncontrolled，不能冒称 cold-data。verifier wall 独立计量。

node_started/finished 在 lazy pull 中可能嵌套，它们是 inclusive iterator-active intervals。它们不证明物理并发，也不能相加当总 CPU/执行时间。正式调度诊断由后续 scheduler 的真实 ready/resource-ready/start/end 事件产生。

进程 CPU 使用 process_time_ns 差值；Linux ru_maxrss 是当前进程生命周期高水位，含解释器和此前工作，仅诊断。worker_peak_ram_bytes、physical_copy_bytes、block_io_bytes 保持 null + 原因。row_views_created、row_mappings_copied、candidate_frames_peak 是明确对象/算法计数，不是物理 RAM/复制字节。source_read_bytes 是真实 JSONL 应用读取字节；wire 与块 I/O 分别观测，不能混加。

`budget_within=null`，因为必需的任务 RAM 约束尚未验证。即使参考输出正确，不能写成 Success@Budget=1。保护性 max_materialized_rows 属于本地开发设施限制，超限为 INFRA_FAILURE/REFERENCE_MATERIALIZATION_CAP；不能冒充模型在规定 RAM 下 OOM。

## 6. Codex 必须补齐的运行保证

每次执行单独 worker，父进程在启动前封存 expected；父进程真实监督 timeout，进程组取消、崩溃、stderr 与半写输出保留分类。子进程不继承 API/cloud 凭据，不修改系统 Python/WSL/全局代理/IAM。执行仅发生在私有 runner 命名空间。

记录 worker PID、明确 clock domain、真实开始/退出事件；父监督器终结记录标明事件来源，不伪造 worker 自报完成。当前 B 侧车没有 CANCELLED 枚举：本票兼容映射为 terminal UNKNOWN + 独立 OWNER_CANCELLED reason，固定分母保留，不算模型失败。状态扩展须版本化并保留旧解析器。

writer 使用增量 durable journal，父进程能在 worker 异常退出后保留真实已发生事件。完整成功要求 result/metadata/binding/verification/events/sidecar 一致且全部封存。独立 verifier 在 worker 结束后运行并与其资源分账。所有结果的 expected 来自预先冻结清单，不能按收到的日志重建。

cgroup 功能适配可以先以 fake filesystem 做单元测试，默认只读/禁用。没有已批准的 delegated cgroup 时，不执行特权命令或写宿主根组。缺少隔离的 RAM 保持 UNKNOWN；RLIMIT_AS 只是地址空间保护，不能作为 RAM.max 的替代证据。首次正式 cgroup 接入、native 内核和采样开销校准另交门禁。

## 7. 参考实现的待强化项与边界

基础版未覆盖通用 after/多分支、硬中断监督、崩溃后 durable journal、通用物理 buffer 注册/释放、完整源码闭包证明和完整多计划运行分母编排。完整 EXEC-001 要按 ACCEPTANCE.md 补齐进程监督、artifact 重读校验、运行身份和 mock生成到执行的集成；F1之外仍列覆盖表为未支持。公共测试计数通过不等于这些设施已存在。

源码身份至少覆盖全部 rcwg_spec/*.py、rcwg_exec/*.py、runner/verifier/协议配置和实际后端版本；统计/前沿公式冻结继续用原 metrology 规范。禁止把工程单例报告并入正式 campaign。
