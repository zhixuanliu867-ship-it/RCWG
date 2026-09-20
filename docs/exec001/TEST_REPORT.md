# RCWG-EXEC-001 参考实现与测试报告

日期：2026-09-19。检查点：REFERENCE_CORE。当前完成一个可运行的F1工程参考闭环，完整EXEC-001还需Codex按ACCEPTANCE.md落实监督器、日志/封存与集成门禁。

## 1. 实际交付范围

5种算子，8个参考分发分支：scan:sequential；filter:scalar/vectorized（有界批mask的Python reference）；project:column_view/copy；top_k:full_sort/streaming_heap；emit:json_artifact。读取真实开发JSONL，经现有B编译器、trusted source注册、runner、artifact和独立verifier，连接B的expected manifest/event/sidecar身份。

PROFILE=RCWG_EXEC001_F1_REFERENCE_SERIAL_PULL_0.1。仅单根链。合法但不受支持的DAG/regions/storage/after等返回设施能力缺口；不悄悄删除节点或优化计划。运行时仍为Python参考，未实现正式C++20/Arrow公平效率内核。

## 2. 实际运行环境和结果

| 检查 | 本次实测 |
|---|---|
| 审查解释器 | Linux / Python3.13.5 |
| 全部测试 | 662/662 PASS，旧585+新增77；子用例不重复计为方法 |
| 旧测试/哨兵文件字节 | 16个冻结B测试/验收文件散列匹配 |
| 原27个compiler哨兵 | 27/27 PASS |
| 原BOOT / formal | BOOT_CHECK_PASS；BLOCKED_NOT_FROZEN(exit2) |
| 新reference gate | EXEC001_REFERENCE_CORE_PASS |
| guard / compileall / bash-n | PASS |
| 目标Python3.12.14新增验收 | PENDING，不以3.13.5替代 |
| 真实API/云/IAM/系统设置修改 | 0 |
| full_exec001_accepted / formal_ready | false / false |

原B官方完整验收的版本限制保持；其6项突变由用户3.12.14/独立CI记录支持，在本轮3.13.5环境也单独重放检出。新代码不宣称在3.12.14已运行。

## 3. 真正跑通的三个工程案例

独立生成257条开发记录；其中171条eligible，k=20，实际JSONL为10341字节。三个案例分别读取实际文件并生成结果/事件，结果如下：

| WorkIR | 运行终态 | 独立输出验收 | top-k候选frame峰值 |
|---|---|---|---:|
| streaming_heap | COMPLETED | PASS | 20 |
| full_sort | COMPLETED | PASS | 171 |
| 删除eligibility筛选 | COMPLETED | FAIL | 20 |

两个正确方案的结果SHA256同为
`68242d53015aa64025ef3f7554b95321d616b96457504db1c3190d6c21121ccf`。

候选frame峰值是算法持有对象的数量，不是整个流水线/RAM字节。filter的有界批、上游引用及解释器还占资源，禁止把20/171直接换算为整机内存加速比。故意删filter案例证明静态合法与实际语义成功被分开，没有证明真实模型经常犯此错。

## 4. 有意保留的待实现项

当前参考执行仍在单进程内，没有完整独立worker与硬截止/取消/崩溃监督。日志在正常结束或可捕获错误后封存，完整增量journal/进程被杀后的证据恢复需Codex补齐。private store采用新目录、独占文件与fsync；跨文件原子事务、metadata完整绑定与crash-cut验证需要最终门禁。

verifier是独立F1 recipe，不调用kernel排序/过滤函数；仅承诺当前明确配方，未知配方UNKNOWN。它不是泛化到六任务族的语义判真系统。所有数据为工程开发夹具，不改变正式template/count/split。

recorded CPU和elapsed取实际进程时钟；生命周期ru_maxrss仅诊断，worker_memory_peak_bytes=null、budget_within=null。动态timeout是参考执行合作式检查，不能代替未来父进程硬deadline。没有cgroup隔离/权限变更，没有论文资源校准结果。

## 5. 验收证据位置

包内 evidence/reference/ACCEPTANCE.json、unittest.txt、actual-demo/三个完整case及其hash/artifact/event/sidecar；编译和shell语法日志。PATCH_PROOF.json另记录在干净受审B树上的apply和重跑。CODEX_TASK.md规定WSL/CI证据、完整EXEC gate与停止点，不能把REFERENCE_CORE成功直接改名成完整EXEC成功。
