# EXEC-001 → 下一阶段接口卡

交接范围：F1 Python reference，5 operators / 8 branches，固定 root chain、可信 JSONL 开发数据、严格 TaskInput/WorkIR 编译、每次独立 worker、私有结果和独立 verifier。完整 WorkIR、正式计量与真实 API 尚未开门。保持 `BLOCKED_NOT_FROZEN`。

## API-001 小规模接入

依赖独立审查 EXEC-001 精确提交和 X00–X15 证据。复用 B 的 request/generation/repeat 身份、公开请求组装和严格解析；复用 `run_f1_supervised`，禁止在 provider 返回后替换计划。实际 provider adapter 需另实现请求前持久预算预留、transport retry 与 generation retry 分账、token/价格/请求 ID 留档、私有响应归档和错误归因。

进入真实请求前冻结具体模型版本、地域、价格快照、输入/输出上限、单次与累计预算、最大请求数量、凭据来源和失败停止条件，并获得对应花费授权。当前接口中 mock 请求数不可记为真实调用；未知 provider usage 保持 null。gold/recipe/隐藏标签不得进入请求。本票未创建真实模型、云或 IAM 操作能力。

## Native 执行器子票

按既定 C++20/Arrow 路线先实现同一 F1 profile，冻结编译器、依赖/lock、构建镜像与算子修订。用本票独立 verifier 和相同数据/WorkIR 做差分。随后逐票扩展 DAG、fanout、after、regions、graph/document、disk 与 backpressure，每项增加 preflight 能力声明和实际运行义务，不静默删除节点或替换算法。

`column_view`/copy 的物理 buffer ID、共享引用、最后消费者释放、峰值占用与复制字节需要原生实现和观测。当前 row-frame/object 计数只作逻辑诊断。Python 时间与原生时间不得合表声称公平效率。

## 计量与环境子票

依赖受控 Linux CPU worker、经批准的 delegated cgroup、固定 CPU/memory 配额、进程树归属、采样/事件开销校准、冷/热缓存协议、OOM 证据和失败截尾规则。取得授权前只读诊断，不写根 cgroup、不以 RLIMIT_AS 替代 RAM.max，不更改系统 Python、WSL 网络、Docker、IAM 或云账户。

父进程 deadline 含启动与完整性核对；kernel wall 和 verifier wall 已分账。下一阶段需冻结正式 estimand 的计时区间，并单列工程 wall 与正式效率指标。RAM 未知时 `budget_within=null`，不得报告 Success@Budget=1。

## 接收物

DELIVERY_EVIDENCE、独立 WSL/CI 证据、私有日志、固定 expected attempts、实际 runtime/dispatch/obligation/testID 矩阵、FINAL.patch、干净应用 tree 证明和 SHA256。审核只覆盖该交付 SHA；后续新 head 不自动继承审核结论。
