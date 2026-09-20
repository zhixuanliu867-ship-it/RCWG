# NATIVE001 公共接口（V1）

所有 fixture 是 BOOT_ONLY 合成开发数据。原 WorkIR 静态编译器保持不变，
合法但本 profile 不支持的计划返回 UNSUPPORTED_IMPLEMENTATION / facility。
不能改写实现选择、删节点或把错误计划换成正确计划。

算子端口沿原契约：scan source→rows；filter rows→rows；top_k rows→rows；
project rows→rows；emit rows→result。父控制器只做公开任务/计划静态准入及
可信 source_id→路径绑定；不读取、排序、过滤、转换数据以准备内核输入。
原生 worker 自己打开 JSONL、校验 schema/UTF8/有限数及 SHA256、执行原链并编码结果。
输入类型 Bool/Int64/有限 Float64/Utf8/Nullable；null 三值逻辑及源序 ordinal 稳定排序。
字符串 count 按 Unicode code point；不使用 locale 排序。整数算术溢出和除零归 plan；
不支持的表达式/表示归 facility，不能静默转换。Int64 除法绝对值超过 2^53 的数值
先拒绝为 UNSUPPORTED_IMPLEMENTATION（避免未经证明的浮点舍入一致性）。

Row 是 shared_ptr<const Buffer> 加列索引；buffer_id 是本次 worker 单调递增标识。
scan 分配所有列；view 保存同一 backing buffer；copy 真正复制所选 Cell 和 UTF8 数据。
output/value 生命周期由 RAII 管理；只有诊断轨统计实际分配、复制、batch 和比较计数。
计数只覆盖显式实现，不代替全进程峰值或库内部/DRAM traffic。

run_id 是控制器生成/验证的 ASCII [A-Za-z0-9_-]{1,80}，独占目录禁止复用。
expected_manifest 在 spawn 前写入，绑定原 task/plan、lowered request、数据 hash、
native source closure、二进制/编译器/flags manifest、测试 case 和 verifier recipe。
worker 记录 run_id/request SHA256、节点真实开始/完成、单调时钟、终态和原始结果；
控制器独立重读所有文件并形成 seal。外部 seal SHA 是独立复核锚点。
未执行/中断/缺测仍保留 expected slot；节点 ID 变化只能改变 identity，不能改变答案。

生命周期：DECLARED→PREPARING→RUNNING→STOPPING→DRAINING→MEASURING→SEALED。
预创建/限制写入/spawn/归档失败均进入持久终态；超时、用户取消、进程崩溃、数据变化、
应用保护上限、计量缺失分别记录原因。OOM 仅凭本 run cgroup memory.events 的增量归因；
bad_alloc/SIGKILL 本身不能证明 OOM。答案错误保留 COMPLETED + verification FAIL。

本地无委派运行只使用独立进程组与外部 deadline，不能宣称 cgroup 隔离。
cgroup driver 默认拒绝创建，必须有 N4 批准、被委派的专属根、可写 controller 和新 run 组。
组级 cpu.max / memory.max / memory.swap.max 在加载 native/data 前设置；启动子进程先
进入组再 exec。监测/控制/verifier 在外。清理先 kill 全组、等空、读 final counters 再回收。

字段：worker_exec_wall_ns（native request 解析至结果编码）、controller_wall_ns（启动至
清理及封存，不含 verifier）、verifier_wall_ns；cpu_usage_usec 为本组 usage 增量；
cpu.stat 节流字段；memory.peak 主峰值；memory.current 100ms 诊断样本；memory.events；
io.stat 按设备保留块 I/O；logical_read_bytes/copy_bytes/payload_bytes 分列，wire_bytes
在无网络本地轨不适用；未插桩 library_copy_bytes/DRAM 为 null。无组数据一律 null + reason。
诊断插桩与 performance 编译/运行模式分开，性能轨不采集 per-row 计数/ownership witness。
所有 N0–N3 输出 budget_within=null、formal_ready=false；mock 与本地真实 native、N4 校准分列。
