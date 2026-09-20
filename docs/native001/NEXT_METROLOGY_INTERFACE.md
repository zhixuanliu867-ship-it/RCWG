# N4 / METROLOGY 下一阶段接口卡

NATIVE001 保持独立草稿 PR #7，base 为已审 CLOUD head 9739bf229843a333f29ce6f166e52e7e12fdd8db。
真实 native 是 C++17 单线程 F1 root-chain 5 算子 / 8 分支。原 Python reference、所有旧 pins、
旧 API/CLOUD ledger 与运行证据不变；没有正式模型、完整 DAG、地区或新云资源承诺。

调用链：`rcwg_native.adapter.lower(task, plan, locations, allowed_root, ident, mode)` →
`rcwg_native.supervisor.execute(request, build, output, context, verify, driver)`。
原始 WorkIR hash、源数据 SHA、编译器/flags/source/binary manifest、expected slot 和外部 seal
必须共同传入/保留。模型 raw response、私有 gold 不能放入 public fixture 或 worker request。
独立 verifier 在 worker 清理后运行，返回 PASS/FAIL/UNKNOWN；不能修正计划。

N3 driver：`LinuxFS(delegated_root, approval=...)`、`Driver(fs, run_id, Limits(...))`。
approval 对象必须由下一次业主批准的精确主机计划产生；当前没有任何可用 approval 文件。
当前 WSL 用户服务仅观察到 cpu/memory/pids，缺少 io；不写共享父组、不改 user@ 服务或 root cgroup。
新组必须独占、零起点、限制先写并重读，再迁入 child 后 exec；controller/verifier 在组外。
cgroup.kill→等 cgroup.events populated=0→final counters→remove；失败保留目录/证据，不假装清理成功。

下一阶段先冻结独立 host 配置、真正的校准 workload source/binary 与 expected manifest，
再执行批准的 per-run 操作。校准需覆盖 CPU 额度、短峰 memory.peak、后代、OOM、timeout/cancel，
以及 100ms sampler on/off 随机配对、3% 开销目标。N0–N3 不声称这些校准已通过。
全局/父设施 OOM 不能只凭 SIGKILL 或 oom_kill 增量记成任务 memory.max 失败。

资源条件对照已在 specs/native001/test_manifest.json 预登记。保留算法 pair、seed、规模、k、
内存条件及重复数；不要看过计时后改数据挑胜例。该计划是后续实验设计，不是当前执行授权。
heap 的辅助结构界与 worker 整体 RAM 分列；published row buffer 的 RAII 容量/存活面积为诊断量，
不包括 parser 临时对象、allocator 元数据或库内复制，不能代替 memory.peak。

目前无需安装 C++ 工具：可继续用已核验 CI 项目二进制做 WSL 本地执行。若需要 WSL 本机编译，
应在下一阶段单列编译器版本和安装提案，不默认获准。Windows gcloud/MCP/云账号均不涉及本接口。

整个工程票 formal_ready=false；正式 6 模型 / 480 开发 / 960 测试与三项主比较不变。
