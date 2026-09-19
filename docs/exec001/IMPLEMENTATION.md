# EXEC-001 实现与证据边界

本票完成 F1 root-chain 的工程参考闭环。REFERENCE_CORE 入口仍表示原子检查点。完整离线入口为 `scripts/accept_exec001.py`，只有加上独立 CI、最终补丁干净应用证明和交付校验后，才可将整票登记为 `EXEC001_F1_ENGINEERING_ACCEPTED`。

E1 导入原 reference 核心并实现独立 worker、父进程 deadline 和进程组清理。持久化是监督器恢复所需的基础，因此 E1 同时引入增量 journal、原子 artifact 写入与重读。E2 增加生成集成和固定多案例分母。E3 补充故障、实际运行覆盖、源码闭包和交付验收。这一提交划分保留三个可检视实现节点。

## 调用与固定分母

`rcwg_exec.supervisor.run_f1_supervised` 接受可信 TaskInput、模型 WorkIR、FileRegistry、私有 recipe 和新输出目录。静态非法计划和合法但超出 profile 的计划在 worker 前返回；`rcwg_exec.campaign.run_campaign` 将其保留在预先冻结的 attempt 清单。campaign 只接受受信任开发案例和 mock bytes；运行中不存在真实 provider 调用入口。

P0/P1 调用原 `rcwg_spec.generation.run_mock_generation`，执行其唯一的 `plan` 返回值。P0 一次 mock 请求，P1 两次；P1 logical 非法时止于第一请求。同一 generation ID 的执行重复必须具有相同公开 task/protocol/response 身份，重用已解析结果，新增 mock 请求记 0。generation ID、attempt ID、repeat ID 分开记录。缺失记录重读为 UNKNOWN，并保持分母。

## 实际运行与度量

每次执行使用相同目标解释器启动新的 `-I -B` worker。父进程先写 expected manifest，再创建 worker。worker 环境采用显式非敏感允许列表，未继承 API/cloud 凭据。受支持 WorkIR 只调用五类固定内核，没有动态执行模型代码、任意 shell 或模型 URI 转文件路径的入口。

父进程 wall 从冻结后的 `run_started` 开始，含进程启动、计算、输出、退出、进程组清理和完整性核对，到 verifier 前结束。登记为 `parent_launch_cleanup_and_integrity_checks_excludes_verifier`。它与 REFERENCE_CORE 的纯 in-process execution wall 不可直接混比。worker 内核 wall、worker process CPU、父进程 CPU、verifier wall/CPU 分开。父进程未取得 worker 最终报告时，其 CPU/RSS 仍为 null，原因是没有最终观测；不能冒称取得完整失败进程资源。

节点事件来自实际 pull 请求与 iterator 活动：queued → ready → running → finished。嵌套区间表示包含上游等待的 iterator 活动，不表示物理并发，也不能相加为总 CPU。标量与 bounded-batch mask、真实 heap 与 full sort、对象 view 与 mapping copy 均保留实际分支与计数。

worker 的 process_cpu_ns 是实际内核区间的 process_time_ns 差值，排除启动、编译与 verifier，不能解释为整个 worker 生命周期 CPU。该范围在 metadata 与字段 validator 中固定。worker_peak_ram、物理复制字节、块 I/O 和预算内判定保持 null。RSS 是独立 worker 的进程生命周期高水位，仍包含解释器、编译等开销。没有 cgroup 隔离或正式校准。单计算线程不是 OS CPU quota 证明。

## 封存、归因与独立验证

父/子 journal 使用真实 monotonic clock、PID、序号、前序 hash，并逐事件 fsync。失败时保留有效前缀、坏完整记录或半行原始字节。父进程只将有效事件投影到 B 账本；损坏 journal 对应设施失败，不能 PASS。正常结束必须拥有完整节点轨迹与 worker 终结事件。

文件以 0600、目录以 0700 创建，使用独占临时文件和原子、不覆盖的 link 发布。manifest、plan、task、artifact bytes、metadata、execution binding、sidecar、verification 和所有日志由外部保留的 seal hash 互相绑定。重读检查文件集合与每项 hash，拒绝跨计划/数据/上下文替换、部分写入和符号链接。安全路径打开逐层 O_NOFOLLOW，FIFO 等非普通文件不会阻塞注册。

独立 verifier 只共享安全文件打开与 canonical 编码；不导入执行 comparator/filter，也不依据模型 plan 推导 gold。私有 recipe 只在父进程 verifier 使用。运行错误答案为 COMPLETED + FAIL；动态算术违约为 MODEL_FAILURE；deadline 为 TIMEOUT；取消为 UNKNOWN/OWNER_CANCELLED；解释器、保护上限和数据故障为 INFRA_FAILURE；不支持的合法计划为设施 gap。formal 门禁保持关闭。

## 复算

在 WSL 仓库根目录、所有受测文件暂存后执行：

```bash
uv run --offline --frozen --python 3.12.14 python scripts/accept_exec001.py --output runs/exec001-new-unique-name
```

入口在精确 3.12.14 下分别运行原 B 完整门禁和 reference 门禁，保留原 585+77 方法与字节、27 哨兵和六突变。新方法另列固定 ID。之后实际运行 34 个固定案例，输出计划、源内容 hash、真实节点 dispatch、原声明 runtime obligations 和逐项验证范围。RAM 未知义务被如实列出，不能仅凭矩阵总数宣布正式运行就绪。

公共 CI 仅上传合成案例的摘要、散列、覆盖矩阵与测试日志。完整数据、recipe、原始响应和 worker 产物留在本机私有 runs 及交付日志包。原 33 个参考文件、72 模板、六模型槽与主要比较保持原件。
