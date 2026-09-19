# 给 Codex 的执行任务：RCWG-SPEC-001B

## 目标和授权

继续现有 RCWG 仓库，实现完整 WorkIR 静态验证与全族 TaskInput / P0-P1 消息组装。研究负责人已批准本目录的 DECISIONS.md 与 operator_contract_worklist.json；常规类型/错误处理/测试决定直接落实，报告变更。完成静态阶段后交付 EXEC-001 所需接口，当前不执行真实模型和云资源。

先读取 AGENTS.md、PROJECT_STATE.md、docs/spec001a/SPEC-001_DECISIONS.md、METROLOGY-001.md、docs/spec001b/DECISIONS.md、ACCEPTANCE.md、A_REVIEW.md。

## 0. 接入已审基线

已审 PR #2 head=6afd48490094d716dc65cf84fe822e45216fcac3，tree=e09ee3a93b46192d3e88775fda5e24bade771f4d。审查时 PR open，main=08b1ecff...。PR #2 可由所有者合并；先核对现状，不假称已合并。
从包含已审 A 代码的 main 建立 rcwg/spec-001b。merge/squash 会改变 commit ID，若 ancestry 不同，用 27 受测文件清单和变更 diff 核实继承的修复；不要回退 main。工作树非空先保存和解释，禁止 reset --hard、clean -fd、force push。
本轮用户已导入最终 A 分支，勿重复应用 A 最终补丁。应用本次 FOUNDATION.patch 前 git apply --check；已存在相同内容则检验并跳过。

## 1. 起始包验收

本起始包包含 2 个已实现模块、63 个新增测试、32 项契约工作清单、27 个完整编译器集成哨兵。标准测试当前应为 194=131+63。
脚本 `bash scripts/accept_spec001b_foundation.sh` 使用已安装的 Python 3.12.14/uv offline frozen。没有 compiler.py 时，独立哨兵明确返回 BLOCKED_IMPLEMENTATION_GAP / exit 2，这一预期结果只允许 FOUNDATION_PASS。
先暂存本票明确允许的代码/测试/规范路径，再运行 public guard；guard检查的是暂存字节。runs/、.venv/、密钥与原始私有响应保持不入库。

## 2. 按三个代码提交推进本票，不再拆出新的审批票

B1 静态协议核心：TaskInput tagged union、schema/type代数、完整32算子参数/端口推导、作用域/控制语义和动态guard计划。复用 ir_structure.py 或给出等价回归证据；不得把它的 STRUCTURE_PASS 当最终编译成功。

B2 生成与证据接口：P0/P1 mock 组装、7字段逻辑契约、严格原始响应解析/私有归档、数据与执行上下文身份连接、expected manifest。在 mock 功能中分别记录请求阶段；不用客户端请求数代替23,040计划尝试数。

B3 独立验收与发布：每一算子各至少一个合法类型/参数用例和一个非法用例，所有实现分支有分发测试；控制结构/组合测试覆盖 ACCEPTANCE.md。全部原测试继续通过；CI新增完整SPEC检查与哨兵。补齐实际覆盖矩阵、命令/退出码、受测代码hash、私有日志hash、PR和README操作示例。

## 3. 必须保留的性质

- 原件33文件逐字节保持，原研究矩阵/主比较不变。
- 用户任务与模型计划不原地改写；raw/canonical hash区分；节点数组序列化顺序保留。
- 通过条件来自真实schema/类型/参数检查；输出声明不是证据；未知参数明确失败。
- 同一上下文下低效/语义错但类型合法计划仍交给runtime/verifier，勿静态“帮模型优化”。
- 设施缺口=IMPLEMENTATION_GAP；不得记作模型错误。所有预期输入异常有结构化错误；内部bug单列。
- 无网络 / 无真实模型 / 无云 / 无IAM / 无正式门禁开启。系统软件安装及付费动作保持所有者批准。
- 原评分计算核仍只接受ENGINEERING_ONLY，完整统计推断/正式计量不顺手冒充已完成。

## 4. 命令接口与退出码

新增 validate_workflow(task,plan,stage=...) API，具体报表见 DECISIONS.md。CLI新命令可追加，不覆盖旧接口。
`python acceptance/spec001b/run_compiler_sentinels.py --output <new-run-path>`：实现后应27/27、exit0；实现缺失exit2；实现存在但错误exit1。
完整 acceptance 脚本由本票实现：不得仅以27哨兵通过宣布验收。应核实32算子矩阵、全部实现分支、region组合、P0/P1、身份、原件与formal退出码。

## 5. 提交前独立审查

至少对已通过实现进行一次负向检查：删掉端口校验、篡改类型、删除一个expected record、改变cache/runtime hash、尝试隐藏gold输入、将子区域输入直接引用外层。测试应检测这些回归。不要上传被故意破坏的实现，保留独立测试证据摘要。

## 6. 最终交付

交付一个PR（rcwg/spec-001b → main），由研究负责人/所有者复核合并。提供：
1. 本轮可读验收报告：实际完成项、修改及依据、实际Python、测试方法数与子用例区分、仍待后续项。
2. 机器可读证据JSON：base/head/tree、受测源码散列、各命令和退出码、完整覆盖矩阵、静态gap列表（验收时应空）、runtime readiness保留。
3. WSL原始日志ZIP（私有）与独立CI状态/日志，二者分开。
4. 最终补丁、SHA256清单，验证干净应用并与远端tree一致。
5. EXEC-001接口卡：typed_graph、input binding、runtime obligations、state/events、artifact注册和独立输出验证入口。

只完成部分时准确写IN_PROGRESS及可复现阻塞原因；不要为了达到测试数而删规则、skip测试或把contract状态直接全部改VALIDATED。
