# N4 离线工程决定（预观察冻结）

基线 456a30d0d242ec005bfb9e25fdc7a45c72aa9af8；新分支 rcwg/native-001-n4，
以 rcwg/native-001 为 stacked base。PR #6/#7 不合并，N4 保持草稿。

1. 审查包候选在精确基线独立副本 apply-check/应用；18 项补充测试字节不改。
   兼容扩展保留必需键、raw 文本和异常部分报告，并在每次读取后持久化。
   MeasurementFault 同时属于 FacilityFault/OSError，保持原删除失败回归契约。
   kill、wait、remove、计量完整、答案、预算、校准状态分别记录。
2. N4 专用 libc launcher 先写 cgroup.procs、设 affinity，再 exec 原性能二进制。
   不用 Python preexec_fn；外层单线程 fork watchdog 覆盖内层 Popen 与整个 run。
   原 N0–N3 无批准本地执行接口保留；批准后的校准只经 N4 receipt runner。
3. 同窗口 oom/oom_kill 不能唯一确定原因。记录 run/祖先 local/hierarchical 事件，
   原生退出、限制读回和控制动作。无法取得绑定 victim/group 的独立证据时 UNKNOWN；
   本轮不请求特权日志，不主动制造祖先或全局 OOM。
4. C01–C10 工程计划固定 888 workload 槽：230 校准、10 预热、648 资源。
   资源原网格 324 对完全保留；seed901 固定顺序，相邻配对，非比较分支固定
   scalar/streaming_heap/column_view。行数据沿原合成生成器，非正式数据。
   C07 故障槽最后安排；设施故障停止批次，剩余 NOT_RUN，不为凑分母重跑。
5. C08 每类 CPU/stream/fanout/I/O/短节点固定批处理，各20对。相同性能二进制，
   只切换100ms采样。统计量 mean((on-off)/off)，seed4901、10000次配对bootstrap，
   95%区间上界<=3%才PASS，下界>3%为FAIL，否则INCONCLUSIVE；off批次<100ms也
   INCONCLUSIVE。不扣猜测开销，不更改正式重复规则，不把整批峰值拆成单任务峰值。
6. 专用临时systemd服务覆盖整批：cpu/memory/io/pids；1GiB、200%CPU、TasksMax64、
   7200秒全局截止、run单线程/固定affinity/64或128MiB/swap0/pids8/最长20秒。
   不修改共享root/user@，不复用旧60秒只读hostcheck批准。就绪失败即停。
7. 单一 proposal 在最终精确head和CI二进制冻结后生成，始终approved=false。
   独立私有owner receipt绑定proposal SHA、host/boot/uid、源码/二进制/输入/命令、
   manifest、1次service use、最长24h有效范围。运行器不生成批准，claim独占落盘。
8. memory.peak包含kernel记账页/缓存；自然warm/mixed缓存，不drop_caches。
   输入解析和hash仍在worker。controller/verifier在外，WSL背景噪声不得外推为正式平台资格。

技术依据：Linux cgroup v2 https://docs.kernel.org/admin-guide/cgroup-v2.html；
Python3.12 subprocess https://docs.python.org/3.12/library/subprocess.html；
原 docs/spec001a/METROLOGY-001.md。线上文档是接口依据，不代替目标主机实测。
正式6模型/32算子/72模板/480开发/960测试与原pins不变，BLOCKED_NOT_FROZEN。
