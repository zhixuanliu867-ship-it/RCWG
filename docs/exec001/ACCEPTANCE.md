# EXEC-001 完整验收矩阵

本文件是 Codex 的完成定义。`accept_exec001_reference.py` 只验 REFERENCE_CORE，成功后也必须 `full_exec001_accepted=false`。原 585 方法 + 本包 77 方法继续保留；以下新增覆盖按真实方法 ID 登记，不以凑总数代替覆盖。

| Gate | 必须实现/实际验证 | 证据 |
|---|---|---|
| X00 | 确认 #2/#3 的已审 SHA 和最终 merge；或真实权限阻断时登记 stacked 开发基线 | PR状态、head、main、merge tree/祖先 |
| X01 | 8 reference 分支实际 dispatch；读真实开发数据；profile能力声明与 preflight 一致 | 正/反/dispatch 方法；临时数据hash |
| X02 | 空数据、不足k、k0、并列、逆序、重复记录/ID、负分、布尔/数值/空值边界 | 独立 gold 与多个固定种子差分 |
| X03 | 模型 choices 保留，缺filter/错k/错keys/错projection 实际执行且独立FAIL；合法低效fullsort保留成本 | 原计划hash、节点日志、输出artifact |
| X04 | 独立worker、父deadline、终结、进程组清理；退出后不遗留子进程 | 正常、timeout、受控取消、崩溃/非零退出日志 |
| X05 | 运行前 manifest固定；出错case不消失；父/子实际时间与来源明确 | manifest hash、实际attempt清单、时间/状态机校验 |
| X06 | artifact独占原子封存和重读；内容/metadata/execution绑定互检；断写/篡改不能PASS | 内容/尺寸/sha/identity/error回归 |
| X07 | source白名单、revision、schema、内容检查；中途修改、符号链接、越界、duplicate JSON、编码错误 | 注册与实际读验证对照 |
| X08 | 真实事件 incremental journal；start/ready/start/finish顺序与重复/缺失检查；partial保留 | 篡改、重排、丢事件、worker异常终止 |
| X09 | 独立verifier不共享kernel比较器/过滤函数；任务recipe不依赖plan；私有gold不进入生成 | PASS/FAIL/UNKNOWN对照；代码依赖审查 |
| X10 | 完成时延与截尾elapsed分开；CPU/内存scope与缺测明确；失败内存不写0 | 测量字段validator与失败样例 |
| X11 | unsupported DAG/regions/impl/storage 为设施gap，不静默替换或删除节点 | profile覆盖矩阵 + 原静态合法样例 |
| X12 | P0/P1 mock响应 → B compiler → actual F1 runner；请求、尝试、重复分离 | P0=1/P1=2 mock request账本；真实请求0 |
| X13 | 原585+新77全部保留，原27哨兵与六突变原入口仍过；新关键运行故障注入确实检出 | 3.12.14 WSL与独立CI分开；无skip/xfail |
| X14 | 受测源码包括rcwg_exec及实际worker/verifier闭包；工作树/暂存/提交散列一致 | 前后源码清单、testIDs、source/runtime hash |
| X15 | 完整补丁干净应用tree一致；可读报告、机器证据、日志、SHA256、后续接口卡 | 原始命令、退出码和独立apply证明 |

受支持范围是已声明 F1 root-chain profile，8个reference分支。通用图/文档/控制内核和正式native计量继续待办。本票通过状态 `EXEC001_F1_ENGINEERING_ACCEPTED`，`formal_ready=false`。未满足的Gate留 IN_PROGRESS；不要只把reference脚本改成宣告全部通过。

## 资源和设施失败归因

模型计划的确定性运行违约（如动态除零）MODEL_FAILURE；计算完成但答案错 COMPLETED + verification FAIL；预注册deadline触发 TIMEOUT且完成时延null；解释器/保护行数/数据变更/不支持内核等设施故障INFRA_FAILURE或runtime_gap；用户取消独立reason且不当作模型错误。未知RAM使预算判定UNKNOWN。对 B 中静态非法计划在进入worker前记录既有 PLAN_INVALID；不要伪造运行日志证明它被执行。

## 原语与buffer

堆/全排序分别验证实际算法与最大候选frame数。scalar/vectorized reference两条路径必须分别被测试；后者确有 bounded batches。行视图要保留原对象，copy产生新对象。只有实际可观测/可解释的量才能填值；Python映射复制次数不能当 memcpy bytes。物理buffer/global memory在native/计量票再验收。
